#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Распаковка контейнера 1С (.cfe/.cf/.epf-как-контейнер) ЧИСТЫМ PYTHON — без
конфигуратора и без базы.

Зачем, если есть extension_deploy.dump_extension: тот работает ТОЛЬКО через
`1cv8.exe DESIGNER /DumpConfigToFiles`, то есть требует и локальный
конфигуратор, и живую `ib_connection`. Когда база на ЧУЖОЙ машине (обычный
случай: раннер ходит по HTTP, а конфигуратора к той базе у нас нет), состав
расширения прочитать было НЕЧЕМ — реальный тупик, стоивший половины сессии
09.09.2026 при разборе роли «Логист».

Что даёт: элементы контейнера как файлы. Формат ВНУТРЕННИЙ (скобочный формат
1С), а НЕ XML, как у DumpConfigToFiles — имена объектов и права из него
читаются грепом (см. extract_names), но полноценного XML тут не будет.

Формат контейнера:
    заголовок файла         16 байт  (next_page_addr, page_size, version, reserved)
    заголовок блока         31 байт  "\\r\\n<8 hex data_size> <8 hex page_size> <8 hex next_page> \\r\\n"
    оглавление              записи по 12 байт: (header_addr, data_addr, 0x7FFFFFFF)
    заголовок элемента      20 байт дат/резерва, далее имя в UTF-16LE, далее нули
    данные элемента         часто сжаты raw-deflate (zlib с wbits=-15)
"""
import os
import re
import struct
import zlib

CONTAINER_SIGNATURE = b'\xff\xff\xff\x7f'
_EMPTY = 0x7FFFFFFF


def _read_block(f, addr: int) -> bytes:
    """Читает блок по адресу, склеивая страницы, и обрезает до объявленного data_size."""
    out = b''
    need = None
    seen = set()
    while addr not in (_EMPTY, 0xFFFFFFFF):
        if addr in seen:  # защита от зацикленных ссылок в битом контейнере
            break
        seen.add(addr)
        f.seek(addr)
        hdr = f.read(31)
        if len(hdr) < 31 or hdr[:2] != b'\r\n':
            break
        try:
            data_size = int(hdr[2:10], 16)
            page_size = int(hdr[11:19], 16)
            next_addr = int(hdr[20:28], 16)
        except ValueError:
            break
        if need is None:
            need = data_size
        out += f.read(page_size)
        if len(out) >= need:
            break
        addr = next_addr
    if need is None:
        return b''
    return out[:need]


def _elem_name(elem_hdr: bytes, fallback: str) -> str:
    """
    Имя элемента: 20 байт служебных, дальше UTF-16LE до первого нуль-символа.

    В черновике имя резалось по b'\\x00\\x00\\x00\\x00' ПО БАЙТАМ — и обрезало
    имена на 34 символах (файл прав роли получал имя без последнего символа,
    из-за чего два разных элемента выглядели как один). Декодируем целиком и
    режем по нуль-СИМВОЛУ — так корректно.
    """
    raw = elem_hdr[20:]
    if len(raw) % 2:
        raw = raw[:-1]
    name = raw.decode('utf-16-le', 'ignore').split('\x00')[0].strip()
    # \/:*?"<>| недопустимы в именах файлов Windows
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', name)
    return name or fallback


def is_container(data: bytes) -> bool:
    return len(data) >= 16 and data[:4] == CONTAINER_SIGNATURE


def unpack(path: str, out_dir: str, recurse: bool = True, _depth: int = 0) -> list:
    """
    Распаковывает контейнер в out_dir. Возвращает список dict:
    {"name", "size", "path", "nested"}.

    recurse=True — вложенные контейнеры (элемент, который сам является
    контейнером) распаковываются в одноимённый подкаталог. Глубина ограничена:
    контейнеры 1С реально вкладываются на 2-3 уровня, больше — признак битого
    файла или зацикливания.
    """
    os.makedirs(out_dir, exist_ok=True)
    result = []
    if _depth > 4:
        return result

    with open(path, 'rb') as f:
        toc = _read_block(f, 16)
        for i in range(len(toc) // 12):
            hdr_addr, data_addr, _tail = struct.unpack('<III', toc[i * 12:(i + 1) * 12])
            if hdr_addr == _EMPTY:
                continue
            elem_hdr = _read_block(f, hdr_addr)
            if len(elem_hdr) < 20:
                continue
            name = _elem_name(elem_hdr, f'unnamed_{i}')
            data = _read_block(f, data_addr)
            try:
                data = zlib.decompress(data, -15)
            except zlib.error:
                pass  # элемент хранится без сжатия — это норма

            dest = os.path.join(out_dir, name)
            with open(dest, 'wb') as o:
                o.write(data)

            nested = []
            if recurse and is_container(data):
                nested = unpack(dest, dest + '.dir', recurse, _depth + 1)
            result.append({"name": name, "size": len(data), "path": dest,
                           "nested": len(nested)})
    return result


def extract_names(out_dir: str, limit: int = 500) -> list:
    """
    Имена объектов/реквизитов из распакованных файлов — то, ради чего обычно и
    лезут в расширение (какие объекты заимствованы, как называется роль).
    Во внутреннем формате они лежат строковыми литералами в кавычках.
    """
    names = set()
    pattern = re.compile(r'"([А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z0-9_]{3,60})"')
    for root, _dirs, files in os.walk(out_dir):
        for fn in files:
            try:
                with open(os.path.join(root, fn), encoding='utf-8-sig', errors='ignore') as fh:
                    names.update(pattern.findall(fh.read()))
            except OSError:
                continue
            if len(names) > limit * 4:
                break
    return sorted(names)[:limit]


def has_record_level_restrictions(out_dir: str) -> dict:
    """
    Есть ли в правах ролей ограничения на уровне записей (RLS).

    Практический смысл: роль расширения может раздавать объектные права и при
    этом НЕ нести никаких RLS — и тогда разграничение (например по организации)
    ею не обеспечивается, сколько её ни правь. Ровно этот вопрос решался
    09.09.2026 по роли «Логист».
    """
    markers = ('ЗначенияДоступа', '#ПоЗначениям', 'ГДЕ ', 'ВЫБРАТЬ')
    hits = {m: 0 for m in markers}
    for root, _dirs, files in os.walk(out_dir):
        for fn in files:
            try:
                with open(os.path.join(root, fn), encoding='utf-8-sig', errors='ignore') as fh:
                    text = fh.read()
            except OSError:
                continue
            for m in markers:
                hits[m] += text.count(m)
    return {"found": any(v for v in hits.values()), "hits": hits}
