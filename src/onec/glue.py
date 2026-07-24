#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Склейка (heal-петля): build/run -> errors1c -> extractor -> fixer.
Раннер ПОДКЛЮЧАЕМЫЙ: run(code) -> (status, errors[], output).
  - fake_run: игрушечный "компилятор" (проверка логики без 1С, но с реальным Qwen).
  - Real1CRunner: боевой; возвращает вывод прогона как ДЕЛЬТУ logs.txt.
Рядом: fixer.py, errors1c.py, extractor.py.  Самопроверка (нужен LM Studio): python glue.py
"""
import re, subprocess, time
from pathlib import Path

from src.onec.fixer import delint, qwen_fix, get_model, qwen_available
from src.onec.extractor import extract_function, replace_span
from src.core.errors1c import parse_1c_errors
from src.onec.bootstrap import ensure_compiler_db


# ============ ЯДРО: петля заживления ============
def heal(code: str, run, max_iters: int = 3, model=None):
    """
    run(code) -> (status, errors[], output).  Возвращает отчёт для дирижёра.
    Глобальный delint -> прогон -> при compile/runtime вырезаем функцию по строке
    -> Qwen чинит только её -> вклеиваем -> повтор. test_failed и ошибка в теле
    модуля -> эскалация к Клоду (не к локалке).

    ГРАЦИОЗНАЯ ДЕГРАДАЦИЯ: если LM Studio не поднят (qwen_available() лжёт),
    Qwen вообще не трогаем — прогоняем код через 1С ОДИН раз (delint всё равно
    применяем, он бесплатный) и возвращаем результат прогона Клоду напрямую,
    с explicit reason="qwen_unavailable", вместо того чтобы упасть на get_model().
    """
    code, _ = delint(code)
    if model is None and not qwen_available():
        status, errors, output = run(code)
        step = {"iter": 1, "status": status, "errors": len(errors)}
        if status == "ok":
            return {"ok": True, "code": code, "iters": 1, "trace": [step], "output": output}
        return {"ok": False, "reason": "qwen_unavailable: LM Studio не поднят — правь код сам "
                                        "(errors ниже) и перепроверяй через run_module",
                "errors": errors, "code": code, "trace": [step], "output": output}
    if model is None:
        model = get_model()
    trace, output = [], ""
    for it in range(1, max_iters + 1):
        status, errors, output = run(code)
        step = {"iter": it, "status": status, "errors": len(errors)}
        if status == "ok":
            trace.append(step)
            return {"ok": True, "code": code, "iters": it, "trace": trace, "output": output}
        if status == "test_failed":
            trace.append(step)
            return {"ok": False, "reason": "test_failed -> к Клоду", "errors": errors,
                    "code": code, "trace": trace, "output": output}
        if not errors:
            trace.append(step)
            return {"ok": False, "reason": f"{status}: структурных ошибок нет, смотри output -> к Клоду",
                    "code": code, "trace": trace, "output": output}
        err = errors[0]
        func = extract_function(code, err["line"])
        if func is None:
            trace.append(step)
            return {"ok": False, "reason": "ошибка в теле модуля -> к Клоду", "errors": errors,
                    "code": code, "trace": trace, "output": output}
        fixed, _u = qwen_fix(func["text"], err["text"], model)
        code = replace_span(code, func["start"], func["end"], fixed)
        code, _ = delint(code)
        step["fixed_func"] = func["name"]
        trace.append(step)
    return {"ok": False, "reason": "исчерпан лимит -> к Клоду", "code": code, "trace": trace, "output": output}


# ============ Игрушечный раннер (без 1С) ============
def fake_run(code: str):
    for i, ln in enumerate(code.splitlines(), start=1):
        if "Каждного" in ln:
            return "compile_error", [{"line": i, "text": "ожидается ключевое слово 'Каждого'", "kind": "code"}], ""
        if re.search(r"\bВернуть\b", ln):
            return "compile_error", [{"line": i, "text": "Неопознанный оператор (Вернуть)", "kind": "code"}], ""
        if re.search(r"\bКонецДля\b", ln):
            return "compile_error", [{"line": i, "text": "Ожидается 'КонецЦикла'", "kind": "code"}], ""
    return "ok", [], "демо: ГОТОВО"


# ============ Боевой раннер к 1С ============
class Real1CRunner:
    def __init__(self, cfg: dict):
        self.c = cfg

    def _build(self):
        c = self.c
        ensure_compiler_db(c)  # #15/#19: портативность — создаст пустую ИБ, если её ещё нет (иначе no-op)
        cmd = (f'"{c["path_1c"]}" DESIGNER /F "{c["compiler_db"]}" '
               f'/LoadExternalDataProcessorOrReportFromFiles "{c["xml"]}" "{c["epf_build"]}" /Out "{c["compile_log"]}"')
        subprocess.run(cmd, shell=True)          # пакует .epf; синтаксис НЕ проверяет

    _LOGS_MAX_BYTES = 200_000  # #53: предохранитель от неограниченного роста logs.txt (см. ниже)

    def __call__(self, code: str):
        c = self.c
        Path(c["src_bsl"]).write_text(code, encoding="utf-8")
        self._build()
        logs = Path(c["logs_txt"])
        if logs.exists() and logs.stat().st_size > self._LOGS_MAX_BYTES:
            # #53 (найдено вживую по вопросу пользователя): BSL-сторона (ЗаписатьВЛог
            # в форме раннера) на КАЖДУЮ запись читает+перезаписывает ФАЙЛ ЦЕЛИКОМ —
            # O(текущий_размер) на вызов, без этого предохранителя logs.txt растёт
            # НЕОГРАНИЧЕННО за всю историю проекта, и каждый прогон дорожает.
            # ВАЖНО: обрезаем ИМЕННО ЗДЕСЬ, ДО того как посчитан before ниже — если
            # бы обрезка происходила ВНУТРИ самого BSL-вызова (между тем, как before
            # запомнен, и тем, как дельта прочитана), before мог бы оказаться БОЛЬШЕ
            # нового (обрезанного) размера файла, и срез [before:] тихо вернул бы
            # ПУСТО вместо реального вывода прогона — гонка с BSL не тронута, потому
            # что раннер в этот момент простаивает (ждёт "WAIT"), логи никто не пишет.
            tail = logs.read_bytes()[-self._LOGS_MAX_BYTES:]
            logs.write_bytes(tail)
        before = logs.stat().st_size if logs.exists() else 0     # запомнили хвост лога
        Path(c["error_txt"]).write_text("WAIT", encoding="utf-8")
        raw = self._wait(c["error_txt"])
        # дельта logs.txt = ЛогВыполнения ИМЕННО этого прогона (Сообщить/итоги/тексты ошибок)
        output = ""
        if logs.exists():
            output = logs.read_bytes()[before:].decode("utf-8-sig", errors="replace").strip()
        head = (raw or "").strip()
        # парсим error.txt + свежую дельту (она не кумулятивна -> безопасно)
        status, errors = parse_1c_errors((raw or "") + "\n" + output)
        tgt = c.get("target_module", "МодульОбъекта")
        errors = [e for e in errors if e["module"].endswith(tgt)]
        if errors:
            return status, errors, output
        if head.upper().startswith("OK") or "ГОТОВО" in output:
            return "ok", [], output
        if head == "TIMEOUT":
            return "timeout", [], output
        return "needs_review", [], output

    def warmup(self):
        """Холодный старт DESIGNER платный — гоняем тривиальный прогон заранее."""
        return self('Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт\n'
                    '    ЛогВыполнения = "ГОТОВО";\n'
                    'КонецПроцедуры\n')

    @staticmethod
    def _wait(path, timeout=50, poll=1.5):      # < таймаута клиента MCP: вернём "timeout" сами
        t0 = time.time()
        while time.time() - t0 < timeout:
            txt = Path(path).read_text(encoding="utf-8-sig").strip() if Path(path).exists() else ""
            if txt and txt != "WAIT":
                return txt
            time.sleep(poll)
        return "TIMEOUT"


# ============ демо ============
if __name__ == "__main__":
    BROKEN = (
        "Перем Кэш;\n\n"
        "&НаСервере\n"
        "Функция ПолучитьСумму(Товары)\n"
        "    Сумма = 0;\n"
        "    Для Каждного Стр Из Товары Цикл\n"
        "        Сумма = Сумма + Стр.Цена;\n"
        "    КонецДля;\n"
        "КонецФункции\n"
    )
    print("=== СТАРТ ===")
    res = heal(BROKEN, fake_run, max_iters=3)
    print("trace:", res["trace"])
    print("ok:", res["ok"], "| причина:", res.get("reason", "-"))
    print("=== ИТОГ ===")
    print(res["code"])
