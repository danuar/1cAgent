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
    """
    Справочник по темам, которые дорого нащупывать заново с нуля (без параметра —
    список доступных тем). Вызывай ТОЛЬКО когда реально нужно (эти тексты не
    зашиты в описания других инструментов специально, чтобы не тратить токены
    впустую): "yaxunit_tests" — перед тем как писать тестовый модуль через
    deploy_module (регистрация тестов, ассерты, грабли с тестовыми данными);
    "extension_files" — формат файлов расширения для случаев, которые
    deploy_module не покрывает (заимствование объектов основной конфигурации).
    """
    return _get_guide_text(topic)


@mcp.tool()
def check_setup() -> dict:
    """
    Диагностика окружения ДО warmup() — особенно полезно на новой машине/при
    первом подключении: что реально найдено на диске (path_1c, java_exe,
    compiler_db, bsl_ls_jar, yaxunit_cfe, epf_runner) и чего не хватает.
    compiler_db создастся сама при первом warmup/run_module, если её нет —
    остальное (bsl_ls_jar/yaxunit_cfe/epf_runner) руками (см. HANDOFF.md).
    """
    return _check_setup(CFG)


@mcp.tool()
def warmup() -> dict:
    """Прогреть 1С (холодный старт DESIGNER ~десятки сек). Вызывай ПЕРВЫМ в сессии."""
    status, _e, output = Real1CRunner(CFG).warmup()
    return {"status": status, "output": _clip(output, 400)}


@mcp.tool()
def run_module(code: str) -> dict:
    """
    Синхронный прогон BSL в живой 1С БЕЗ починки (~10-20с). status, errors[], output.
    output = ЛогВыполнения прогона (Сообщить/итоги/тексты ошибок).
    Точка входа СТРОГО: Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт; в конце "ГОТОВО".
    """
    status, errors, output = Real1CRunner(CFG)(code)
    return {"status": status, "errors": errors[:12], "output": _clip(output, MAX_OUTPUT)}


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
    """
    АСИНХРОННО. Запускает самозаживляющую петлю (build->run->delint+Qwen->повтор)
    и СРАЗУ возвращает job_id. Результат: job_status(job_id) через ~15-60с.
    Точка входа СТРОГО: Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт; в конце "ГОТОВО".
    Если LM Studio не поднят — НЕ виснет и не падает: прогоняет код ОДИН раз (без
    Qwen-починки) и возвращает результат с reason="qwen_unavailable: ..." — правь
    сам через run_module/heal_module с поднятой локалкой.
    """
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
    """
    АСИНХРОННО. Возвращает job_id; результат — job_status(job_id). Если LM Studio
    не поднят — НЕ падает и не висит: возвращает {"qwen":"unavailable", "delint":[...]}
    мгновенно (Qwen нужен только для самой починки, не для делинта).
    """
    jid = _spawn(_fix_impl, code, error)
    return {"job_id": jid, "status": "running", "hint": "через ~5-30с вызови job_status(job_id)"}


@mcp.tool()
def read_module(path: str = "", procedure: str = "", outline: bool = False) -> str:
    """
    Прочитать .bsl-модуль (по умолчанию текущий ObjectModule.bsl).

    Для больших модулей (>10-15 процедур) НЕ читай файл целиком без нужды —
    в одной из сессий модуль на 40+ тыс. симв. перечитывался Read'ом 7 раз
    целиком, хотя каждый раз правилась одна процедура:
      outline=True     -> список Процедура/Функция с номерами строк (дёшево,
                           чтобы решить, что реально нужно читать/менять).
      procedure="Имя"  -> ТОЛЬКО тело этой Процедуры/Функции (с шапкой и
                           КонецПроцедуры/КонецФункции), без остального файла.
    Если procedure не найдена — возвращается outline вместо ошибки (обычно
    из-за опечатки в имени, outline сразу подскажет верное написание).
    """
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
    """
    Компактные метаданные конфигурации вместо простыней XML. Только чтение,
    конфигурацию не меняет (~5-15с). Три уровня по параметрам:
      ("", "")     -> census: счётчики объектов по всем видам конфигурации.
      (kind, "")   -> index:  список имён вида + рекв/тч (или изм/рес/рекв, или знач).
      (kind, name) -> detail: полная схема объекта — реквизиты+типы, ТЧ+колонки.
    kind один из: Документы, Справочники, РегистрыСведений, РегистрыНакопления,
    РегистрыБухгалтерии, РегистрыРасчета, Перечисления, ПланыВидовХарактеристик,
    ПланыСчетов, ПланыОбмена, БизнесПроцессы, Задачи, Обработки, Отчеты, Константы.
    """
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
    """
    Группа A (нужна живая форма-раннер, см. start_runner). Только чтение.
    Server/Client/ВызовСервера/Привилегированный-флаги существующего ОБЩЕГО
    МОДУЛЯ (Метаданные.ОбщиеМодули.Найти) — не путать с describe_metadata
    (бизнес-объекты: справочники/документы/регистры).

    Появился после реального бага (#24, см. HANDOFF.md): deploy_module однажды
    создал модуль ОДНОВРЕМЕННО клиентским и серверным — такой модуль не резолвит
    вызовы ДРУГИХ чисто серверных общих модулей в серверном контексте (например
    YaXUnit ДобавитьСерверныйТест), падая с "Переменная не определена". Если
    видите такую ошибку при вызове ОДНОГО общего модуля из ДРУГОГО — ПЕРВЫМ ДЕЛОМ
    проверьте оба через describe_common_module, прежде чем искать проблему в
    расширениях/областях видимости.
    """
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
    """
    Только ЧТЕНИЕ. Выполняет текст запроса 1С и возвращает компактные строки
    "колонка=значение|колонка=значение" вместо XML/дампа ТаблицыЗначений.
    limit обрезает ответ (не сам запрос — используйте ПЕРВЫЕ N в тексте запроса,
    чтобы не гонять по базе лишнее).
    """
    code = bsl_query(query_text, limit)
    status, errors, output = Real1CRunner(CFG)(code)
    if status != "ok" or errors:
        return {"status": status, "errors": errors[:8], "output": _clip(output, MAX_OUTPUT)}
    return {"status": "ok", **parse_query_rows(output)}


@mcp.tool()
def lint_module(code: str) -> dict:
    """
    #6: быстрый статический линт BSL Language Server — БЕЗ живой 1С (~1-3с вместо
    10-20с run_module). Ловит явные проблемы до дорогого прогона через живую базу.
    Требует java + jar на этой машине (CFG["bsl_ls_jar"]); если их нет — вернёт
    {"ok": None, "error": "..."} — это значит "гейт недоступен", не "код плохой".
    """
    return bsl_lint(code, CFG["bsl_ls_jar"], java_exe=CFG.get("java_exe", "java"))
