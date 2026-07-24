#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер ошибок 1С из вывода РАННЕРА (ВнешниеОбработки.Создать/исполнение).
ВАЖНО: compile.log от LoadExternalDataProcessorOrReportFromFiles НЕ содержит
синтаксических ошибок — он только пакует .epf. Реальные ошибки даёт раннер при
инициализации модуля. Этот модуль превращает его текст в result.errors[] по контракту.
Самопроверка:  python3 errors1c.py
"""
import re, json

# {Путь.Модуль(стр,кол)}: текст     или    {...(стр)}: текст
_ERR = re.compile(
    r"\{(?P<module>[^}]+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\}\s*:\s*(?P<text>.*)"
)
_CATEGORY = {
    "ОшибкаКомпиляцииВстроенногоЯзыка": "compile_error",
    "ОшибкаВоВремяВыполненияВстроенногоЯзыка": "runtime_error",
}
_TEST_PREFIX = "ОШИБКА ТЕСТА:"


def parse_1c_errors(text: str):
    """(status, errors[]). errors: {module,line,col,text,source,kind}. С дедупом."""
    lines = text.splitlines()
    errors, seen = [], set()
    marker_status = None
    test_failed = False

    for i, raw in enumerate(lines):
        s = raw.strip()

        m_cat = re.fullmatch(r"\[(\w+)\]", s)
        if m_cat and m_cat.group(1) in _CATEGORY:
            marker_status = _CATEGORY[m_cat.group(1)]
            continue

        is_test = s.startswith(_TEST_PREFIX)
        body = s[len(_TEST_PREFIX):].strip() if is_test else s

        m = _ERR.search(body)
        if not m:
            continue

        # исходник с кареткой <<?>>: на этой же строке или на следующей
        src = ""
        if "<<?>>" in body:
            src = body
        elif i + 1 < len(lines) and "<<?>>" in lines[i + 1]:
            src = lines[i + 1].strip()

        line = int(m.group("line"))
        txt = m.group("text").replace("<<?>>", "").strip()
        key = (line, m.group("col"), txt)
        if key in seen:      # дедуп — раннер повторяет одну ошибку много раз
            continue
        seen.add(key)

        errors.append({
            "module": m.group("module"),
            "line": line,
            "col": int(m.group("col")) if m.group("col") else None,
            "text": txt,
            "source": src.replace("<<?>>", "⟦тут⟧").strip(),
            "kind": "test" if is_test else "code",
        })
        if is_test:
            test_failed = True

    # приоритет статуса: компиляция/рантайм > тест > дефолт
    if marker_status:
        status = marker_status
    elif test_failed:
        status = "test_failed"
    elif errors:
        status = "compile_error"
    else:
        status = "ok"
    return status, errors


SAMPLE = r"""{ВнешняяОбработка.ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта(1,6)}: Неопознанный оператор
Ниже <<?>>представлен переработанный программный код.
{ВнешняяОбработка.ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта(3,2)}: Ожидается оператор препроцессора
#<<?>>## Архитектурная рефлексия
[ОшибкаКомпиляцииВстроенногоЯзыка]
ОШИБКА ТЕСТА: {ВнешняяОбработка.ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта(308)}: Поле объекта не обнаружено (Наименование)
{ВнешняяОбработка.ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта(143,12)}: Неопознанный оператор
			КонецДля<<?>>;
{ВнешняяОбработка.ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта(144,3)}: Ожидается ключевое слово 'КонецЦикла' ('EndDo')
		<<?>>Иначе
{ВнешняяОбработка.ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта(143,12)}: Неопознанный оператор
			КонецДля<<?>>;"""


if __name__ == "__main__":
    st, errs = parse_1c_errors(SAMPLE)
    print(json.dumps({"status": st, "count": len(errs), "errors": errs},
                     ensure_ascii=False, indent=2))
