#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Забрать .cfe расширения ИЗ БАЗЫ ЧЕРЕЗ РАННЕР (пользовательский режим), без
конфигуратора и без доступа к файловой системе сервера.

Почему это отдельный путь, а не extension_deploy.dump_extension: тот требует
`1cv8.exe DESIGNER` + `ib_connection`, то есть локальный конфигуратор к ТОЙ
базе. Раннер же ходит к нам сам по HTTP — и `РасширенияКонфигурации.Получить()`
с `ПолучитьДанные()` доступны прямо из встроенного языка. Проверено вживую
09.09.2026 на БП 3.0.205.22: 37 расширений, `ПолучитьДанные()` вернул 73 763
байта.

Почему НЕ через run_module: тот обрезает вывод до MAX_OUTPUT (6000 символов),
а base64 даже небольшого расширения — десятки тысяч. Здесь Real1CRunner
вызывается напрямую, результат НИКОГДА не возвращается в контекст модели, а
пишется на диск — возвращаются только путь и размер.
"""
import base64
import os
import re

from src.onec.glue import Real1CRunner

# Размер куска в СИМВОЛАХ base64-строки за один прогон раннера. 40k — с запасом
# под лимиты HTTP-транспорта; расширение на 73 КБ (~99k символов) укладывается
# в 3 прогона.
CHUNK = 40000
_BEGIN = "<<<B64BEGIN"
_END = "B64END>>>"
_B64_ALPHABET = re.compile(r'[^A-Za-z0-9+/=]')

_BSL_LEN = '''Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт
	Отбор = Новый Структура("Имя", "{name}");
	Список = РасширенияКонфигурации.Получить(Отбор);
	Если Список.Количество() = 0 Тогда
		Сообщить("ERR:НЕ НАЙДЕНО");
		Возврат;
	КонецЕсли;
	Дан = Список[0].ПолучитьДанные();
	Сообщить("BYTES:" + Формат(Дан.Размер(), "ЧГ=0"));
	Сообщить("LEN:" + Формат(СтрДлина(Base64Строка(Дан)), "ЧГ=0"));
	Сообщить("ГОТОВО");
КонецПроцедуры'''

_BSL_CHUNK = '''Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт
	Отбор = Новый Структура("Имя", "{name}");
	Список = РасширенияКонфигурации.Получить(Отбор);
	Дан = Список[0].ПолучитьДанные();
	Стр = Base64Строка(Дан);
	Сообщить("{begin}");
	Сообщить(Сред(Стр, {start}, {length}));
	Сообщить("{end}");
	Сообщить("ГОТОВО");
КонецПроцедуры'''


def _between(text: str) -> str:
    """Вырезает полезную нагрузку между маркерами и чистит всё, что не base64."""
    start = text.find(_BEGIN)
    stop = text.find(_END)
    if start == -1 or stop == -1 or stop < start:
        return ""
    return _B64_ALPHABET.sub('', text[start + len(_BEGIN):stop])


def fetch_extension(cfg: dict, ext_name: str, out_path: str = "") -> dict:
    """
    Скачивает расширение ext_name из базы через раннер и кладёт .cfe на диск.

    Раннер должен быть уже поднят (см. http_transport_status.runner_alive).
    Возвращает {"ok", "path", "size", "chunks"} либо {"ok": False, "error"}.
    """
    runner = Real1CRunner(cfg)

    status, _errors, output = runner(_BSL_LEN.format(name=ext_name))
    if status not in ("ok", "needs_review"):
        return {"ok": False, "error": f"раннер не отработал: {status}", "output": output[:600]}
    if "ERR:НЕ НАЙДЕНО" in output:
        return {"ok": False, "error": f"расширение {ext_name!r} не найдено в базе"}

    m_len = re.search(r'LEN:([\d\s ]+)', output)
    m_bytes = re.search(r'BYTES:([\d\s ]+)', output)
    if not m_len:
        return {"ok": False, "error": "не удалось получить длину base64", "output": output[:600]}
    total = int(re.sub(r'\D', '', m_len.group(1)))
    expect_bytes = int(re.sub(r'\D', '', m_bytes.group(1))) if m_bytes else 0

    parts, pos, chunks = [], 1, 0
    while pos <= total:
        status, _errors, out = runner(_BSL_CHUNK.format(
            name=ext_name, start=pos, length=CHUNK, begin=_BEGIN, end=_END))
        if status not in ("ok", "needs_review"):
            return {"ok": False, "error": f"сбой на куске {chunks + 1}: {status}",
                    "output": out[:600]}
        piece = _between(out)
        if not piece:
            return {"ok": False, "error": f"пустой кусок {chunks + 1} (маркеры не найдены)",
                    "output": out[:600]}
        parts.append(piece)
        pos += CHUNK
        chunks += 1

    try:
        blob = base64.b64decode("".join(parts))
    except Exception as e:
        return {"ok": False, "error": f"base64 не декодируется: {e!r}"}

    if expect_bytes and len(blob) != expect_bytes:
        return {"ok": False, "error": f"размер не сошёлся: получено {len(blob)}, "
                                      f"база сообщила {expect_bytes}"}

    if not out_path:
        out_path = os.path.join(cfg["runtime_dir"], "ext_cfe", f"{ext_name}.cfe")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(blob)

    return {"ok": True, "path": out_path, "size": len(blob), "chunks": chunks}
