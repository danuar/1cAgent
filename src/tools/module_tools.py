#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Группа A: warmup/run_module/heal_module/fix_snippet/describe_*/query_data/read_module/lint_module/get_guide/check_setup."""
import json
from pathlib import Path

from src.tools.core import mcp, CFG, MAX_CODE_INLINE, MAX_OUTPUT, _clip, _spawn
from src.onec.glue import heal, Real1CRunner
from src.onec.fixer import delint, qwen_fix, get_model, qwen_available
from src.onec.metadata_tool import (ALL_KINDS, bsl_census, parse_census, bsl_index, parse_index,
                            bsl_detail, parse_detail, bsl_query, parse_query_rows,
                            bsl_common_module_detail, parse_common_module_detail)
from src.onec.bsl_ls import lint as bsl_lint
from src.onec.guides import get_guide_text as _get_guide_text
from src.onec.bootstrap import check_setup as _check_setup
from src.onec.module_reader import outline as _outline, extract_procedure as _extract_procedure


@mcp.tool()
def get_guide(topic: str = "") -> str:
    """Справочник по теме; без параметра — список тем. Читать только когда нужно: yaxunit_tests (перед тестовым модулем), extension_files (формат файлов расширения), extension_forms (события/реквизиты форм в расширении), main_config_* (объекты основной конфигурации)."""
    return _get_guide_text(topic)


@mcp.tool()
def check_setup() -> dict:
    """Что найдено на диске: path_1c/java/jar/cfe/epf_runner/ocr. Нехватка — ручная установка человеком."""
    return _check_setup(CFG)


@mcp.tool()
def warmup() -> dict:
    """Холодный старт раннера. Первый вызов группы A в сессии (preflight его заменяет)."""
    status, _e, output = Real1CRunner(CFG).warmup()
    return {"status": status, "output": _clip(output, 400)}


@mcp.tool()
def run_module(code: str, on_client: bool = False) -> dict:
    """Прогнать BSL в живой 1С → {status, errors[], output}. Задание: Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт, без вложенных Процедура/Функция и Возврат, в конце Сообщить("ГОТОВО").
    on_client=True — клиентский контекст (формы: ОткрытьФорму/.Открыть()); только HTTP-транспорт и быстрый путь, иначе status=client_unavailable. Вывод на клиенте писать в ЛогВыполнения (ЛогВыполнения = ЛогВыполнения + Символы.ПС + ...), Сообщить() там не собирается."""
    status, errors, output = Real1CRunner(CFG)(code, on_client=on_client)
    return {"status": status, "errors": errors[:12], "output": _clip(output, MAX_OUTPUT)}


@mcp.tool()
def run_module_batch(codes: list) -> dict:
    """Несколько заданий одним вызовом (экономит ходы). codes — список текстов заданий. → {results:[{n,status,output,errors}], all_ok}. На сбое не останавливается."""
    if not codes:
        return {"error": "пустой список заданий"}
    runner = Real1CRunner(CFG)
    results = []
    for n, code in enumerate(codes, 1):
        status, errors, output = runner(code)
        results.append({"n": n, "status": status, "errors": errors[:6],
                        "output": _clip(output, MAX_OUTPUT // max(1, min(len(codes), 4)))})
    return {"results": results, "all_ok": all(r["status"] == "ok" for r in results)}


def _heal_impl(code, max_iters):
    res = heal(code, Real1CRunner(CFG), max_iters=max_iters)
    out = {"ok": res["ok"], "iters": res.get("iters"), "trace": res["trace"],
           "reason": res.get("reason"), "output": _clip(res.get("output", ""), MAX_OUTPUT),
           "src": CFG["src_bsl"]}
    if not res["ok"]:
        out["errors"] = res.get("errors", [])[:8]
    c = res.get("code", "")
    out["code"] = c if len(c) <= MAX_CODE_INLINE else f"(велик: {len(c)} симв. — read_module)"
    return out


@mcp.tool()
def heal_module(code: str, max_iters: int = 3) -> dict:
    """Async. Петля run→делинт→Qwen-фикс→повтор (LM Studio :1235; без него один прогон, reason=qwen_unavailable). Формат задания как у run_module."""
    jid = _spawn(_heal_impl, code, max_iters)
    return {"job_id": jid, "status": "running", "hint": "через ~15-60с вызови job_status(job_id)"}


def _fix_impl(code, error):
    code2, dl = delint(code)
    if not qwen_available():
        return {"delint": dl, "fixed": code2, "qwen": "unavailable",
                "hint": "LM Studio не поднят — Qwen не звали. fixed = код после ДЕЛИНТА "
                        "(детерминированные замены типа Вернуть->Возврат), саму ошибку "
                        "почини сам и проверь через run_module"}
    fixed, usage = qwen_fix(code2, error, get_model())
    return {"delint": dl, "fixed": fixed, "usage": usage}


@mcp.tool()
def fix_snippet(code: str, error: str) -> dict:
    """Async. Точечный Qwen-фикс code по тексту error. Без LM Studio — только делинт ({qwen:'unavailable', fixed})."""
    jid = _spawn(_fix_impl, code, error)
    return {"job_id": jid, "status": "running", "hint": "через ~5-30с вызови job_status(job_id)"}


@mcp.tool()
def read_module(path: str = "", procedure: str = "", outline: bool = False) -> str:
    """Прочитать .bsl (по умолчанию текущий ObjectModule). outline=True — список процедур со строками; procedure='Имя' — только её тело (не найдена → outline). Большие модули целиком не читать."""
    text = Path(path or CFG["src_bsl"]).read_text(encoding="utf-8-sig")
    if outline:
        return json.dumps(_outline(text), ensure_ascii=False)
    if procedure:
        block = _extract_procedure(text, procedure)
        if block is not None:
            return block
        return ("Процедура/Функция не найдена: " + procedure + "\n\nOutline:\n" +
                json.dumps(_outline(text), ensure_ascii=False))
    return text


@mcp.tool()
def describe_metadata(kind: str = "", name: str = "") -> dict:
    """Метаданные компактно (группа A, чтение). ('','') → census по видам; (kind,'') → имена вида с реквизитами; (kind,name) → полная схема объекта. kind: Документы, Справочники, РегистрыСведений, РегистрыНакопления, РегистрыБухгалтерии, РегистрыРасчета, Перечисления, ПланыВидовХарактеристик, ПланыСчетов, ПланыОбмена, БизнесПроцессы, Задачи, Обработки, Отчеты, Константы."""
    if not kind:
        code = bsl_census()
    elif kind not in ALL_KINDS:
        return {"error": f"неизвестный вид: {kind}", "kinds": ALL_KINDS}
    elif not name:
        code = bsl_index(kind)
    else:
        try:
            code = bsl_detail(kind, name)
        except ValueError as e:
            return {"error": str(e)}

    status, errors, output = Real1CRunner(CFG)(code)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    if not kind:
        return {"status": "ok", "census": parse_census(output)}
    if not name:
        return {"status": "ok", "kind": kind, "index": parse_index(output)}
    return {"status": "ok", "kind": kind, "name": name, **parse_detail(output)}


@mcp.tool()
def describe_common_module(module_name: str) -> dict:
    """Флаги общего модуля: Server/Client/ВызовСервера/Привилегированный (группа A, чтение). «Переменная не определена» при вызове одного общего модуля из другого → сначала сверить флаги обоих."""
    try:
        code = bsl_common_module_detail(module_name)
    except ValueError as e:
        return {"error": str(e)}
    status, errors, output = Real1CRunner(CFG)(code)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", "module": module_name, **parse_common_module_detail(output)}


@mcp.tool()
def query_data(query_text: str, limit: int = 20) -> dict:
    """Чтение. Запрос 1С → строки «поле=значение|...». limit режет ответ, не запрос — ставь ПЕРВЫЕ N в тексте."""
    code = bsl_query(query_text, limit)
    status, errors, output = Real1CRunner(CFG)(code)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", **parse_query_rows(output)}


# #68: коды, которые к работоспособности кода отношения не имеют — при
# errors_only их не показываем, чтобы реальный ParseError не тонул в стиле.
_STYLE_ONLY_CODES = {"DeprecatedCurrentDate", "InvalidCharacterInFile",
                     "DeprecatedFind", "DeprecatedMessage"}


@mcp.tool()
def lint_module(code: str, errors_only: bool = True, include_style: bool = False) -> dict:
    """Статический линт BSL LS без 1С (~2с) → {ok, compiles, diagnostics[], error}. errors_only=True — только severity=Error (ParseError = не компилируется); include_style=True — всё. Нет java/jar → ok=None (гейт недоступен). Не ловит недоступность метода в клиентском контексте."""
    res = bsl_lint(code, CFG["bsl_ls_jar"], java_exe=CFG.get("java_exe", "java"))
    if include_style or not isinstance(res, dict):
        return res
    diags = res.get("diagnostics") or []
    if errors_only:
        diags = [d for d in diags
                 if d.get("severity") == "Error" and d.get("code") not in _STYLE_ONLY_CODES]
    parse_errors = [d for d in diags if d.get("code") == "ParseError"]
    return {"ok": not parse_errors, "compiles": not parse_errors,
            "diagnostics": diags, "total_before_filter": len(res.get("diagnostics") or []),
            "error": res.get("error")}
