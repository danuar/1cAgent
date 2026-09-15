#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#70: HTTP-транспорт заданий — альтернатива обмену через общую папку.

ЗАЧЕМ. Не ради скорости: узкое место (сборка .epf, ~3.4с) уже устранено
быстрым путём #67, и локальный HTTP-запрос стоит миллисекунды против
миллисекунд файловой операции. HTTP нужен ради ДОСТИЖИМОСТИ: раннер может
жить на чужом сервере, куда не протянуть ни файловую шару, ни VPN, а
выставлять SMB (порт 445) в интернет нельзя — через него в базу с
выключенным безопасным режимом уезжает произвольный исполняемый BSL.

ГДЕ ЖИВЁТ. Потоком ВНУТРИ процесса MCP-сервера: Claude запускает
mcp_server.py как дочерний процесс по stdio (см.
%APPDATA%/Roaming/Claude/claude_desktop_config.json), отдельная служба не
нужна. Пока агент не работает — раннер получает отказ соединения и спокойно
ждёт дальше, это нормальное состояние.

ПРОТОКОЛ (раннер — КЛИЕНТ, ходит сам; сервер его не дёргает):
    GET  /task?wait=2   -> 200 {"seq","mode":"exec"|"epf","code"|"epf_b64"}
                           204, если заданий нет (длинный опрос истёк)
    POST /result        <- {"seq","status","log"}
    GET  /ping          -> 200 {"ok":true} (проверка связи и токена)
Везде обязателен заголовок X-Agent-Token.

ПРО ДЛИННЫЙ ОПРОС. Обработчик ожидания в 1С СИНХРОННЫЙ — он блокирует сессию
на время запроса, поэтому wait ограничен сверху (_MAX_WAIT). И на keep-alive
рассчитывать НЕЛЬЗЯ: 1С не гарантирует переиспользование соединения, каждый
опрос — новое рукопожатие, поэтому лучше один запрос с ожиданием 2с, чем два
мгновенных.
"""
import base64
import json
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_MAX_WAIT = 5.0          # потолок длинного опроса, см. докстринг
_RUNNER_ALIVE_SEC = 15.0  # раннер считается живым, если стучался недавно


class TaskBoard:
    """
    Точка встречи двух потоков: агент кладёт задание и ждёт результат, раннер
    забирает задание и приносит результат. Одно задание за раз — ровно как в
    файловом протоколе (там роль доски играл error.txt).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._task = None
        self._task_ready = threading.Event()
        self._result = None
        self._result_ready = threading.Event()
        self._seq = 0
        self._last_seen = 0.0
        self._served = 0
        self._last_client = ""   # #77: откуда пришёл раннер — 127.0.0.1 значит
                                 # напрямую, 172.x/host-gateway значит через Caddy
        self._last_wait = None   # #72: какой wait просит раннер — видно, живёт ли
                                 # он в длинном опросе (новая сборка) или дёргает
                                 # короткими запросами (старая)

    # ---- сторона агента ----
    def submit(self, mode: str, code: str = "", epf_bytes: bytes = b"", timeout: float = 60.0,
               on_client: bool = False) -> dict:
        with self._lock:
            self._seq += 1
            seq = self._seq
            # #90: client=True — раннер обязан исполнить задание в КЛИЕНТСКОМ контексте
            # (иначе ОткрытьФорму/ПолучитьФорму недоступны в клиент-серверной базе).
            self._task = {"seq": seq, "mode": mode, "code": code, "epf": epf_bytes,
                          "client": bool(on_client)}
            self._result = None
        self._result_ready.clear()
        self._task_ready.set()
        got = self._result_ready.wait(timeout)
        with self._lock:
            res = self._result
            self._task = None
            self._task_ready.clear()
        if not got or not res:
            return {"ok": False, "timeout": True}
        return {"ok": True, **res}

    def runner_alive(self, within: float = _RUNNER_ALIVE_SEC) -> bool:
        return (time.time() - self._last_seen) < within

    def stats(self) -> dict:
        return {"last_seen_ago": round(time.time() - self._last_seen, 1) if self._last_seen else None,
                "tasks_served": self._served, "runner_alive": self.runner_alive(),
                "last_wait": self._last_wait, "last_client": self._last_client}

    # ---- сторона раннера ----
    def take(self, wait: float, client: str = "") -> dict:
        self._last_seen = time.time()
        self._last_wait = wait
        if client:
            self._last_client = client
        if not self._task_ready.wait(min(max(wait, 0.0), _MAX_WAIT)):
            return {}
        with self._lock:
            return dict(self._task) if self._task else {}

    def put_result(self, seq: int, status: str, log: str) -> bool:
        with self._lock:
            if not self._task or self._task["seq"] != seq:
                return False    # опоздал/чужой результат — молча игнорируем
            self._result = {"status": status, "log": log}
            self._served += 1
        self._result_ready.set()
        return True


BOARD = TaskBoard()


def _token_path(cfg: dict) -> Path:
    return Path(cfg["work_dir"]) / "http_token.txt"


def ensure_token(cfg: dict) -> str:
    """Токен доступа. Генерится один раз и лежит в work/http_token.txt —
    оттуда его копируют в поле раннера."""
    p = _token_path(cfg)
    if p.exists():
        tok = p.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(24)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok, encoding="utf-8")
    return tok


class _Handler(BaseHTTPRequestHandler):
    server_version = "1cAgent/1"
    token = ""

    def log_message(self, *args):
        pass    # не засоряем stdout: по нему идёт MCP-протокол

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.headers.get("X-Agent-Token", "") == self.token:
            return True
        self._json(401, {"error": "нужен заголовок X-Agent-Token"})
        return False

    def do_GET(self):
        if not self._authorized():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/ping":
            BOARD._last_seen = time.time()
            return self._json(200, {"ok": True})
        if parsed.path == "/status":
            # #78: посмотреть состояние доски СНАРУЖИ процесса. Без этого
            # нельзя отличить "раннер не стучится" от "стучится, но я смотрю
            # не в тот процесс" — ровно на этом потеряли время.
            return self._json(200, BOARD.stats())
        if parsed.path != "/task":
            return self._json(404, {"error": "нет такого пути"})

        wait = float((parse_qs(parsed.query).get("wait") or ["2"])[0] or 2)
        task = BOARD.take(wait, client=self.client_address[0] if self.client_address else "")
        if not task:
            self.send_response(204)
            self.end_headers()
            return
        payload = {"seq": task["seq"], "mode": task["mode"], "client": bool(task.get("client"))}
        if task["mode"] == "exec":
            payload["code"] = task["code"]
        else:
            payload["epf_b64"] = base64.b64encode(task["epf"]).decode("ascii")
        self._json(200, payload)

    def do_POST(self):
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path == "/submit":
            # #83: задание от СОСЕДНЕГО экземпляра MCP-сервера, который не смог
            # занять порт. Наружу этот путь НЕ проксируется (в Caddyfile его нет)
            # — он только для локальных процессов агента.
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                data = json.loads(raw.decode("utf-8-sig"))
            except Exception as e:
                return self._json(400, {"error": f"не разобрал тело: {e!r}"})
            epf = base64.b64decode(data["epf_b64"]) if data.get("epf_b64") else b""
            res = BOARD.submit(str(data.get("mode", "exec")), code=str(data.get("code", "")),
                               epf_bytes=epf, timeout=float(data.get("timeout", 60)),
                               on_client=bool(data.get("client")))
            return self._json(200, res)
        if path != "/result":
            return self._json(404, {"error": "нет такого пути"})
        # utf-8-sig, а не utf-8: 1С в УстановитьТелоИзСтроки(..., КодировкаТекста.UTF8)
        # добавляет BOM, и json.loads на нём падает — раннер получал 400 "не разобрал
        # тело", молча считал задание выполненным и брал его снова, зациклившись.
        # Поймано на раннере для обычного приложения (УПП 1.3); utf-8-sig читает и
        # тело без BOM, так что для управляемого раннера ничего не меняется.
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            data = json.loads(raw.decode("utf-8-sig"))
        except Exception as e:
            return self._json(400, {"error": f"не разобрал тело: {e!r}"})
        ok = BOARD.put_result(int(data.get("seq", 0)), str(data.get("status", "")),
                              str(data.get("log", "")))
        self._json(200, {"accepted": ok})


_SERVER = {"httpd": None, "thread": None, "host": "", "port": 0, "mode": None, "token": ""}


def _local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _ask_local(port: int, token: str, path: str, payload: dict = None, timeout: float = 5.0):
    """Запрос к УЖЕ РАБОТАЮЩЕМУ эндпоинту на этой машине (режим клиента)."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(_local_url(port) + path, data=data,
                                 headers={"X-Agent-Token": token,
                                          "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else {}


def _who_holds(port: int) -> str:
    """Кто занял порт — PID и имя процесса. Best-effort, только для сообщения."""
    try:
        import subprocess
        ps = ("$p=(Get-NetTCPConnection -State Listen -LocalPort %d -ErrorAction SilentlyContinue"
              " | Select-Object -First 1).OwningProcess;"
              " if ($p) { $x=Get-Process -Id $p -ErrorAction SilentlyContinue;"
              " Write-Output ($p.ToString() + ' ' + $x.ProcessName) }" % port)
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=10)
        return r.stdout.decode("cp866", errors="replace").strip() or "не определено"
    except Exception:
        return "не определено"


def start(cfg: dict, host: str = "127.0.0.1", port: int = 1533) -> dict:
    """
    Поднять сервер в фоновом потоке. host="127.0.0.1" — только эта машина
    (безопасное умолчание); "0.0.0.0" открывает наружу, делать это осознанно
    и вместе с TLS-прокси, потому что токен по чистому HTTP идёт открытым.

    #83 (найдено вживую): Claude запускает mcp_server.py в ДВУХ экземплярах
    одновременно. Порт может занять только один, и раньше второй молча оставался
    без эндпоинта: раннер стучался в доску заданий ПЕРВОГО процесса, а задания
    от инструментов попадали в пустую доску ВТОРОГО — run_module отваливался по
    таймауту без единого намёка на причину. Теперь проигравший гонку экземпляр
    становится КЛИЕНТОМ победителя и отдаёт ему задания через локальный /submit.
    """
    if _SERVER["mode"] is not None:
        return {"ok": True, "already": True, "mode": _SERVER["mode"],
                "url": f"http://{_SERVER['host']}:{_SERVER['port']}", "token": ensure_token(cfg)}
    token = ensure_token(cfg)
    handler = type("_H", (_Handler,), {"token": token})
    # #79 (стоило часа диагностики): на Windows allow_reuse_address, включённый
    # у ThreadingHTTPServer по умолчанию, позволяет ВТОРОМУ процессу занять УЖЕ
    # занятый порт. bind проходит, start рапортует ok=True, но запросы забирает
    # процесс, занявший порт ПЕРВЫМ. Выглядело как "раннер не стучится", хотя он
    # исправно стучался — в чужую доску заданий.
    class _Server(ThreadingHTTPServer):
        allow_reuse_address = False

    try:
        httpd = _Server((host, port), handler)
    except OSError as e:
        # порт занят — возможно, НАШИМ ЖЕ эндпоинтом из соседнего экземпляра
        try:
            _ask_local(port, token, "/ping")
        except Exception:
            # #90 (D2): порт занят чем-то ЧУЖИМ. Назвать виновника — иначе
            # разбирательство "кто держит порт" стоит нескольких ходов.
            return {"ok": False, "reason": f"не смог занять {host}:{port}: {e}",
                    "port_held_by": _who_holds(port)}
        _SERVER.update({"httpd": None, "thread": None, "host": "127.0.0.1",
                        "port": port, "mode": "client", "token": token})
        return {"ok": True, "mode": "client", "url": _local_url(port), "token": token,
                "note": "порт держит соседний экземпляр MCP-сервера — работаем через него"}
    t = threading.Thread(target=httpd.serve_forever, daemon=True, name="agent-http")
    t.start()
    _SERVER.update({"httpd": httpd, "thread": t, "host": host, "port": port,
                    "mode": "owner", "token": token})
    return {"ok": True, "mode": "owner", "url": f"http://{host}:{port}", "token": token,
            "token_file": str(_token_path(cfg))}


def stop() -> dict:
    httpd = _SERVER["httpd"]
    _SERVER.update({"mode": None})
    if httpd is None:
        return {"ok": True, "already_stopped": True}
    httpd.shutdown()
    httpd.server_close()
    _SERVER.update({"httpd": None, "thread": None})
    return {"ok": True}


def runner_alive(cfg: dict = None) -> bool:
    """Есть ли ЖИВОЙ раннер — неважно, наша это доска или соседнего экземпляра."""
    if _SERVER["mode"] == "owner":
        return BOARD.runner_alive()
    if _SERVER["mode"] == "client":
        try:
            return bool(_ask_local(_SERVER["port"], _SERVER["token"], "/status").get("runner_alive"))
        except Exception:
            return False
    return False


def submit(mode: str, code: str = "", epf_bytes: bytes = b"", timeout: float = 60.0,
           on_client: bool = False) -> dict:
    """
    Отдать задание раннеру. Владелец порта кладёт на свою доску, остальные —
    через локальный /submit владельцу (#83). Вызывающему разница не видна.
    """
    if _SERVER["mode"] == "owner":
        return BOARD.submit(mode, code=code, epf_bytes=epf_bytes, timeout=timeout,
                            on_client=on_client)
    if _SERVER["mode"] == "client":
        payload = {"mode": mode, "code": code, "timeout": timeout,
                   "client": bool(on_client),
                   "epf_b64": base64.b64encode(epf_bytes).decode("ascii") if epf_bytes else ""}
        try:
            return _ask_local(_SERVER["port"], _SERVER["token"], "/submit", payload,
                              timeout=timeout + 10)
        except Exception as e:
            return {"ok": False, "timeout": True, "reason": f"локальный эндпоинт не ответил: {e!r}"}
    return {"ok": False, "timeout": True, "reason": "HTTP-транспорт не запущен"}


def status(cfg: dict) -> dict:
    res = {"running": _SERVER["mode"] is not None, "mode": _SERVER["mode"],
           "url": (f"http://{_SERVER['host']}:{_SERVER['port']}" if _SERVER["mode"] else ""),
           "token_file": str(_token_path(cfg))}
    if _SERVER["mode"] == "client":
        try:
            res.update(_ask_local(_SERVER["port"], _SERVER["token"], "/status"))
        except Exception as e:
            res["reason"] = f"сосед не отвечает: {e!r}"
        return res
    res.update(BOARD.stats())
    return res
