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
from src.onec.designer_run import run_watched
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


def _screen_hint(cfg: dict) -> str:
    """
    #66: текст ВИДИМОГО окна 1С (OCR), best-effort. Нужен, чтобы run_module на
    таймауте возвращал ПРИЧИНУ, а не глухое "timeout": сегодня дважды теряли
    время на том, что раннер молчал, а на экране висело модальное окно, о
    котором в ответе не было ни слова. Ищем среди ВСЕХ процессов 1С — конкретная
    база здесь неизвестна (раннер живёт своей сессией).
    """
    try:
        from src.onec.sessions import list_1c_processes
        from src.core.screenshot_1c import find_1c_window, capture_window, ocr_text
        pids = {p["ProcessId"] for p in list_1c_processes() if p.get("ProcessId")}
        win = find_1c_window(pids) if pids else None
        if win is None:
            return ""
        png = capture_window(win["hwnd"])
        if png is None:
            return ""
        return (ocr_text(cfg, png) or "").strip()[:300]
    except Exception:
        return ""   # диагностика не должна ронять основной путь


# #87 (пункт B3 плана): вывод раннера приходил с мусором, и он ехал в контекст
# на КАЖДЫЙ прогон. Два источника:
#   1) метка времени 1С в начале каждой записи логa ("29.08.2026 18:26:28: ");
#   2) битый первый символ — logs.txt читается СРЕЗОМ БАЙТ с прошлой позиции
#      (logs.read_bytes()[before:]), и срез запросто рассекает UTF-8 символ
#      пополам, давая U+FFFD и обрывки вроде "а]" в начале вывода.
_LOG_TS_RE = re.compile(r"(?m)^\d{2}\.\d{2}\.\d{4} \d{1,2}:\d{2}:\d{2}:\s*")


def _tail_since(path, before: int) -> str:
    """
    Дельта файла лога с байтовой позиции `before`. #87: позиция байтовая, а
    кириллица в UTF-8 занимает два байта — срез запросто рассекал символ
    пополам, и вывод начинался с обрывка вроде "а]". Сдвигаем начало среза до
    ближайшего НАЧАЛА символа: продолжающие байты UTF-8 всегда 0x80..0xBF.
    """
    data = Path(path).read_bytes()[before:]
    i = 0
    while i < len(data) and 0x80 <= data[i] <= 0xBF:
        i += 1
    return data[i:].decode("utf-8-sig", errors="replace").strip()


def _clean_log(text: str) -> str:
    if not text:
        return ""
    text = _LOG_TS_RE.sub("", text)
    text = text.replace("�", "")
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    # схлопываем подряд идущие пустые строки — они ничего не несут, а место в
    # бюджете вывода занимают
    out, blank = [], False
    for ln in lines:
        if not ln.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out)


# #67: БЫСТРЫЙ ПУТЬ. Пересборка AgentCode.epf конфигуратором — это ~3.4с из
# ~5с полного цикла run_module (замерено). Если задание не объявляет своих
# процедур/функций, его тело можно отдать раннеру ТЕКСТОМ и выполнить через
# Выполнить() — конфигуратор не запускается вовсе.
_TASK_RE = re.compile(
    r"^\s*Процедура\s+ВыполнитьЗадачу\s*\([^)]*\)\s*Экспорт\s*;?(.*)КонецПроцедуры\s*$",
    re.S | re.I)
_DECL_RE = re.compile(r"(?im)^\s*(Процедура|Функция)\s")
# #84 (поймано вживую): в Выполнить() код исполняется В КОНТЕКСТЕ вызывающей
# функции, поэтому оператор Возврат там НЕДОПУСТИМ — прогон падает, причём
# раньше молча (см. _finish). Задания с ранним выходом гоним через .epf.
_RETURN_RE = re.compile(r"(?im)^\s*Возврат\s*;")


def _direct_body(code: str) -> str:
    """
    Тело ЕДИНСТВЕННОЙ процедуры ВыполнитьЗадачу — или "", если код сложнее и
    его надо гнать старым путём через .epf. Ограничения не наши, а платформы:
    Выполнить() не принимает ни объявления процедур/функций, ни Возврат.
    """
    m = _TASK_RE.match((code or "").strip())
    if not m:
        return ""
    body = m.group(1)
    if _DECL_RE.search(body) or _RETURN_RE.search(body):
        return ""
    return body.strip()


# ============ Боевой раннер к 1С ============
class Real1CRunner:
    def __init__(self, cfg: dict):
        self.c = cfg

    def _build(self) -> dict:
        """
        #66: раньше здесь был ГОЛЫЙ subprocess.run(cmd, shell=True) БЕЗ таймаута
        вообще — то есть модальное окно конфигуратора (например "Неизвестная
        версия формата" или рассинхрон базы) вешало сборку НАВСЕГДА, а run_module
        снаружи выглядел как необъяснимый "timeout". run_watched (#45, уже
        применён в metadata_deploy/module_deploy/extension_deploy, но сюда так и
        не дошёл) поллит процесс, параллельно смотрит на экран и убивает ДЕРЕВО
        процессов — на Windows subprocess.run(timeout=) убивает только cmd.exe,
        а сам 1cv8.exe остаётся висеть осиротевшим.
        Возвращает словарь run_watched (см. designer_run.py).
        """
        c = self.c
        ensure_compiler_db(c)  # #15/#19: портативность — создаст пустую ИБ, если её ещё нет (иначе no-op)
        # #63: собираем ПЛАТФОРМОЙ СБОРКИ (обычно самой младшей из
        # установленных), а не самой свежей: .epf, собранный 8.5.1, не
        # откроется в базе на 8.3.24, а собранный 8.3.24 — откроется везде.
        cmd = (f'"{c.get("path_1c_build") or c["path_1c"]}" DESIGNER /F "{c["compiler_db"]}" '
               f'/LoadExternalDataProcessorOrReportFromFiles "{c["xml"]}" "{c["epf_build"]}" /Out "{c["compile_log"]}"')
        # пакует .epf; синтаксис НЕ проверяет
        return run_watched(cmd, c.get("build_timeout", 120), c, f'File="{c["compiler_db"]}"')

    _LOGS_MAX_BYTES = 200_000  # #53: предохранитель от неограниченного роста logs.txt (см. ниже)

    def _runner_protocol(self) -> int:
        """
        Какой протокол объявил ЖИВОЙ раннер (файл runner.txt, пишется им при
        открытии). 1 = старый, понимает только "WAIT" с готовым .epf;
        2 = понимает быстрый путь "WAIT_EXEC" с текстом задания.
        """
        try:
            txt = Path(self.c["runner_txt"]).read_text(encoding="utf-8-sig")
        except Exception:
            return 1
        m = re.search(r"protocol\s*=\s*(\d+)", txt)
        return int(m.group(1)) if m else 1

    @staticmethod
    def _http_board():
        """
        #70/#83: модуль HTTP-транспорта, ЕСЛИ к нему прямо сейчас подключён живой
        раннер (стучался за последние ~15с). Иначе None — работаем через папку
        обмена, как раньше. Переключать ничего не надо: чем раннер подключился,
        тем и общаемся.

        Спрашиваем именно МОДУЛЬ, а не BOARD напрямую: порт может держать
        соседний экземпляр MCP-сервера (Claude запускает их два), и тогда живая
        доска — у него, а мы работаем через него клиентом.
        """
        try:
            from src.onec import http_transport as ht
            return ht if ht.runner_alive() else None
        except Exception:
            return None

    def _finish(self, head: str, output: str):
        """Общий разбор ответа раннера — одинаков для файлов и для HTTP."""
        output = _clean_log(output)
        status, errors = parse_1c_errors((head or "") + chr(10) + output)
        tgt = self.c.get("target_module", "МодульОбъекта")
        errors = [e for e in errors if e["module"].endswith(tgt)]
        if errors:
            return status, errors, output or (head or "")
        if (head or "").strip().upper().startswith("OK") or "ГОТОВО" in output:
            return "ok", [], output
        # #84: раньше здесь возвращался ПУСТОЙ output, если раннер прислал текст
        # ошибки в статусе, а сообщений не было — снаружи это выглядело как
        # "needs_review" вообще без объяснений. Ответ раннера НИКОГДА не должен
        # теряться: он и есть единственная причина, по которой прогон не "ok".
        head = (head or "").strip()
        if not output and head and head.upper() != "START":
            return "runtime_error", [], head
        return "needs_review", [], output or head

    def _run_via_http(self, board, code: str, direct: str, on_client: bool = False):
        """Задание уходит по HTTP: тот же выбор быстрый/через .epf, что и в файлах."""
        c = self.c
        if on_client and not direct:
            # #90: на клиенте задание исполняется через Выполнить(), а он не
            # принимает ни объявлений процедур/функций, ни Возврат — .epf-путь
            # клиентским быть не может (ВнешниеОбработки.Подключить серверный).
            return ("client_unavailable", [],
                    "для on_client=True код должен быть ОДНОЙ процедурой ВыполнитьЗадачу "
                    "без вложенных процедур/функций и без Возврат")
        if direct:
            res = board.submit("exec", code=direct, timeout=c.get("http_timeout", 60),
                               on_client=on_client)
        else:
            Path(c["src_bsl"]).write_text(code, encoding="utf-8")
            built = self._build()
            if built.get("dialog") or built.get("timed_out"):
                why = ("конфигуратор встал на модальном окне: " + (built.get("hint") or "")
                       if built.get("dialog")
                       else f"сборка .epf не уложилась в {c.get('build_timeout', 120)}с")
                return "build_failed", [], why
            res = board.submit("epf", epf_bytes=Path(c["epf_build"]).read_bytes(),
                               timeout=c.get("http_timeout", 60))
        if not res.get("ok"):
            return "timeout", [], "раннер по HTTP не ответил вовремя"
        return self._finish(res.get("status", ""), res.get("log", "") or "")

    def __call__(self, code: str, allow_direct: bool = True, on_client: bool = False):
        c = self.c
        board = self._http_board()
        direct = _direct_body(code) if allow_direct else ""
        if board is not None:
            return self._run_via_http(board, code, direct, on_client)
        if on_client:
            # #90: клиентский контекст живёт ТОЛЬКО в HTTP-протоколе — файловый
            # обмен признака не несёт, старый раннер о нём не знает.
            return ("client_unavailable", [],
                    "клиентское исполнение доступно только по HTTP-транспорту, "
                    "а сейчас задания идут через папку обмена")
        if direct and self._runner_protocol() >= 2:
            return self._run_direct(code, direct)
        direct = ""
        Path(c["src_bsl"]).write_text(code, encoding="utf-8")
        built = self._build()
        if built.get("dialog") or built.get("timed_out"):
            # #66: НЕ идём дальше ждать раннер 50с — задание ему всё равно не
            # положено, .epf не собран. Возвращаем причину, а не глухой timeout.
            why = ("конфигуратор встал на модальном окне: " + (built.get("hint") or "")
                   if built.get("dialog")
                   else f"сборка .epf не уложилась в {c.get('build_timeout', 120)}с")
            return "build_failed", [], why
        self._built_rc = built.get("returncode")
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
            output = _tail_since(logs, before)
        head = (raw or "").strip()
        if head == "TIMEOUT":
            # #66: раннер не ответил за отведённое время. Сам по себе "timeout"
            # ничего не объясняет — добираем то, что видно на экране.
            output = _clean_log(output)
            hint = _screen_hint(c)
            if hint:
                output = (output + chr(10) + "[что на экране 1С] " + hint).strip()
            return "timeout", [], output
        # #87/D3: разбор ответа — ТОЛЬКО через _finish, один на все транспорты.
        # Раньше здесь и в _run_direct были две почти одинаковые копии, и правка
        # в одной (например чистка лога) не попадала в другую.
        return self._finish(head, output)

    def warmup(self):
        """Холодный старт DESIGNER платный — гоняем тривиальный прогон заранее."""
        return self('Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт\n'
                    '    ЛогВыполнения = "ГОТОВО";\n'
                    'КонецПроцедуры\n')

    def _run_direct(self, code: str, body: str):
        """
        #67: задание уходит ТЕКСТОМ (task.bsl + маркер WAIT_EXEC), конфигуратор
        не запускается. Ждём КОРОТКО: если раннер на самом деле старый (файл
        runner.txt протух от прошлой сессии), незачем висеть полные 50с —
        забываем протокол и честно повторяем через сборку .epf.
        """
        c = self.c
        Path(c["task_bsl"]).write_text(body, encoding="utf-8")
        logs = Path(c["logs_txt"])
        before = logs.stat().st_size if logs.exists() else 0
        Path(c["error_txt"]).write_text("WAIT_EXEC", encoding="utf-8")
        raw = self._wait(c["error_txt"], timeout=c.get("direct_timeout", 15), marker="WAIT_EXEC")

        if (raw or "").strip() == "TIMEOUT":
            try:
                Path(c["runner_txt"]).unlink()
            except OSError:
                pass
            return self(code, allow_direct=False)

        output = ""
        if logs.exists():
            output = _tail_since(logs, before)
        return self._finish((raw or "").strip(), output)

    @staticmethod
    def _wait(path, timeout=50, poll=1.5, marker="WAIT"):   # < таймаута клиента MCP: вернём "timeout" сами
        """
        #69: опрос АДАПТИВНЫЙ, а не фиксированные 1.5с. Замер показал, что на
        быстром пути (#67) весь прогон занимал ровно 1.50с — то есть время
        уходило не на работу, а на гранулярность ожидания. Начинаем с 0.1с и
        плавно растём до poll: короткие задания отвечают почти мгновенно, а
        длинные не долбят диск (важно, когда папка обмена СЕТЕВАЯ — там каждая
        проверка это обращение по SMB, а не к локальному диску).
        """
        t0 = time.time()
        step = 0.1
        while time.time() - t0 < timeout:
            txt = Path(path).read_text(encoding="utf-8-sig").strip() if Path(path).exists() else ""
            if txt and txt != marker:
                return txt
            time.sleep(step)
            step = min(poll, step * 1.6)
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
