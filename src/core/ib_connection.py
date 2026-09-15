#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Разбор декларативной строки подключения 1С в аргументы командной строки
DESIGNER/ENTERPRISE. Строка передаётся ЯВНО на каждый вызов (Клод указывает,
к какой базе обращаться, по тому, что сказал человек в чате) — принципиально
НЕ хардкодится в config.py, т.к. один MCP-сервер работает то с базой-
компилятором (пустая, только сборка epf), то с тестовой/рабочей базой, и это
может меняться между сессиями/проектами.

Синтаксис — стандартный 1С (как в диалоге добавления базы):
    File="C:\\Users\\danua\\Documents\\gosNas";
    Srvr="server-name";Ref="baseName";Usr="Admin";Pwd="secret";
Usr/Pwd — опциональны, нужны только для баз с аутентификацией.
"""
import re


def parse_connection_string(conn: str) -> dict:
    """'Key="value";Key2="value2";' -> {"Key": "value", "Key2": "value2"}."""
    parts = {}
    for m in re.finditer(r'(\w+)\s*=\s*"((?:[^"]|"")*)"', conn or ""):
        key, val = m.group(1), m.group(2).replace('""', '"')
        parts[key] = val
    return parts


def cli_connection_str(conn: str) -> str:
    """
    Строка подключения -> готовый фрагмент командной строки 1cv8.exe:
    '/F "путь"' или '/S "сервер\\база"', плюс '/N "юзер"' '/P "пароль"' если заданы.
    ValueError, если не удалось разобрать (нет ни File, ни Srvr+Ref).
    """
    p = parse_connection_string(conn)
    ws = p.get("ws") or p.get("WS") or p.get("Ws")
    frag = []
    if p.get("File"):
        frag.append(f'/F "{p["File"]}"')
    elif p.get("Srvr") and p.get("Ref"):
        frag.append(f'/S "{p["Srvr"]}\\{p["Ref"]}"')
    elif ws:
        # веб-база (тонкий клиент через HTTP-публикацию). ТОЛЬКО ENTERPRISE:
        # КОНФИГУРАТОР по ws не подключается в принципе — все DESIGNER-инструменты
        # (deploy_*, dump_*) с такой строкой не работают.
        frag.append(f'/WS "{ws}"')
    else:
        raise ValueError(
            f'не удалось разобрать строку подключения: {conn!r} — нужно '
            f'File="путь"; или Srvr="сервер";Ref="база";'
        )
    if p.get("Usr"):
        frag.append(f'/N "{p["Usr"]}"')
    if p.get("Pwd"):
        frag.append(f'/P "{p["Pwd"]}"')
    return " ".join(frag)
