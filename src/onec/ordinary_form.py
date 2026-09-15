#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Правка МОДУЛЯ ОБЫЧНОЙ ФОРМЫ внутри плоской выгрузки .epf.

Зачем. У управляемой формы модуль лежит отдельным .txt (см. epf_build.py) и
правится тривиально. У ОБЫЧНОЙ формы вся форма — один бинарный файл
"<Имя>.Form.<ИмяФормы>.Form", и модуль спрятан внутри него. Из-за этого
раннер для обычного приложения пришлось делать вовсе без формы, а это дало
занятый намертво сеанс 1С ("окно не отвечает", закрыть можно только через
диспетчер).

Формат контейнера (разобран живьём на форме, сделанной в конфигураторе):

    \r\n<8 hex datalen> <8 hex allocated> <8 hex flags> \r\n   <- заголовок, 31 байт
    <данные, добитые нулями до allocated>

Блоки идут подряд; в самом первом блоке лежит ОГЛАВЛЕНИЕ — пары 4-байтовых
адресов (адрес блока с именем, адрес блока с данными). Имя блока модуля —
строка "module" в UTF-16LE, имя разметки — "form".

ПОЭТОМУ: пока новый текст модуля влезает в allocated (у пустого модуля это
512 байт), менять нужно ТОЛЬКО datalen и сами данные — адреса в оглавлении
остаются верными. Если не влезает, блок надо расширять и двигать все
последующие адреса; этот случай реализован отдельно и требует пересчёта
оглавления, поэтому по умолчанию запрещён (raise), чтобы не портить файл молча.
"""
import re
from pathlib import Path

_HEADER = re.compile(rb"\r\n([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8}) \r\n")
_HEADER_LEN = 31
_BOM = b"\xef\xbb\xbf"


def _blocks(data: bytes):
    """-> [(header_start, data_start, datalen, allocated)] в порядке следования."""
    out = []
    for m in _HEADER.finditer(data):
        datalen = int(m.group(1), 16)
        allocated = int(m.group(2), 16)
        out.append((m.start(), m.end(), datalen, allocated))
    return out


def find_module_block(data: bytes):
    """
    Блок с текстом модуля формы: содержимое начинается с BOM и содержит
    ключевые слова BSL. Имя "module" лежит в ОТДЕЛЬНОМ блоке перед ним, но
    опираться на порядок ненадёжно — ищем по самому содержимому.
    """
    for hdr, start, datalen, allocated in _blocks(data):
        chunk = data[start:start + datalen]
        if not chunk.startswith(_BOM):
            continue
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "Процедура" in text or "Функция" in text or text.strip() == _BOM.decode("utf-8"):
            # разметка формы тоже начинается с BOM, но она вида "{27,\r\n{18,..."
            if text.lstrip("\ufeff").lstrip().startswith("{"):
                continue
            return hdr, start, datalen, allocated
    return None


def read_module(form_path: str) -> str:
    data = Path(form_path).read_bytes()
    found = find_module_block(data)
    if not found:
        raise ValueError(f"в {form_path} не нашёл блок модуля формы")
    _, start, datalen, _ = found
    return data[start:start + datalen].decode("utf-8").lstrip("\ufeff")


def write_module(form_path: str, module_text: str, allow_grow: bool = False) -> dict:
    """
    Заменяет текст модуля обычной формы. Возвращает {"ok", "old_len", "new_len",
    "allocated", "grown"}. Перевод строк приводится к \r\n — так пишет сам
    конфигуратор.
    """
    path = Path(form_path)
    data = path.read_bytes()
    found = find_module_block(data)
    if not found:
        raise ValueError(f"в {form_path} не нашёл блок модуля формы")
    hdr, start, datalen, allocated = found

    text = module_text.replace("\r\n", "\n").replace("\n", "\r\n")
    payload = _BOM + text.encode("utf-8")

    if len(payload) > allocated:
        if not allow_grow:
            raise ValueError(
                f"модуль не влезает в блок: {len(payload)} байт при allocated={allocated}. "
                f"Расширение блока сдвигает последующие блоки и требует пересчёта "
                f"оглавления — включайте allow_grow=True осознанно."
            )
        return _write_grown(path, data, hdr, start, datalen, allocated, payload)

    new_header = b"\r\n%08x %08x %08x \r\n" % (len(payload), allocated, 0x7fffffff)
    assert len(new_header) == _HEADER_LEN, len(new_header)
    body = payload + b"\x00" * (allocated - len(payload))
    path.write_bytes(data[:hdr] + new_header + body + data[start + allocated:])
    return {"ok": True, "old_len": datalen, "new_len": len(payload),
            "allocated": allocated, "grown": False}


def _write_grown(path: Path, data: bytes, hdr: int, start: int, datalen: int,
                 allocated: int, payload: bytes) -> dict:
    """
    Расширение блока модуля: все блоки ПОСЛЕ него сдвигаются, поэтому адреса в
    оглавлении (первый блок) надо увеличить на величину сдвига. Адреса — little
    endian uint32; трогаем только те, что указывают ЗА наш блок.
    """
    new_alloc = len(payload)
    shift = new_alloc - allocated
    new_header = b"\r\n%08x %08x %08x \r\n" % (len(payload), new_alloc, 0x7fffffff)
    rebuilt = bytearray(data[:hdr] + new_header + payload + data[start + allocated:])

    toc_blocks = _blocks(bytes(data))
    if toc_blocks:
        _, toc_start, toc_len, _ = toc_blocks[0]
        for off in range(toc_start, toc_start + toc_len - 3, 4):
            value = int.from_bytes(data[off:off + 4], "little")
            if value == 0x7fffffff or value <= hdr:
                continue
            rebuilt[off:off + 4] = (value + shift).to_bytes(4, "little")
    path.write_bytes(bytes(rebuilt))
    return {"ok": True, "old_len": datalen, "new_len": len(payload),
            "allocated": new_alloc, "grown": True, "shift": shift}
