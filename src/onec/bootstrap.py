#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#15/#19: портативность — не хардкодить путь к платформе 1С/Java под одну
машину. config.py сначала проверяет захардкоженный путь (не трогаем то, что
уже работает на этой машине), и только если его нет на диске — ищет здесь.
Так же — ленивое автосоздание пустой compiler_db (нужна ТОЛЬКО для сборки
.epf через ВнешниеОбработки, см. glue.Real1CRunner._build; никакая
конфигурация в неё не грузится).
"""
import glob
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


# Стандартные места установки платформы. Нестандартные (например
# D:\1сБазы\платформы на машине автора) добавляются через CFG["platform_roots"] —
# раньше такая папка находилась ТОЛЬКО потому, что путь был захардкожен в
# config.py, автопоиск её не видел вообще.
_DEFAULT_PLATFORM_ROOTS = (r"C:\Program Files\1cv8", r"C:\Program Files (x86)\1cv8")


def _version_key(ver: str) -> tuple:
    """'8.3.24.1624' -> (8, 3, 24, 1624) — сравнивать надо ЧИСЛАМИ: строкой
    '8.3.9' > '8.3.24', что неверно."""
    return tuple(int(c) if c.isdigit() else 0 for c in (ver or "").split("."))


def find_1c_platforms(roots=None) -> list:
    """
    Все установленные платформы: [{"version", "exe" (толстый 1cv8.exe),
    "thin" (тонкий 1cv8c.exe, "" если рядом нет)}], СТАРШАЯ первой.
    Раскладка у всех одинаковая: корень / версия / bin / 1cv8.exe.
    """
    found = {}
    for base in (tuple(roots) if roots else ()) + _DEFAULT_PLATFORM_ROOTS:
        for exe in glob.glob(str(Path(base) / "*" / "bin" / "1cv8.exe")):
            version = Path(exe).parent.parent.name
            if version in found:
                continue
            thin = str(Path(exe).with_name("1cv8c.exe"))
            found[version] = {"version": version, "exe": exe,
                              "thin": thin if Path(thin).exists() else ""}
    return sorted(found.values(), key=lambda p: _version_key(p["version"]), reverse=True)


def pick_platform(platforms: list, version_prefix: str = "", oldest: bool = False) -> dict:
    """
    Выбор платформы из списка. version_prefix — точная версия или её начало
    ("8.3.24" подходит к "8.3.24.1624"). Пусто -> самая старшая, а при
    oldest=True самая младшая: так выбирается платформа СБОРКИ .epf —
    собранная младшей платформой обработка открывается и во всех старших,
    наоборот нет. {} если ничего не подошло.
    """
    if not platforms:
        return {}
    if version_prefix:
        for p in platforms:
            if p["version"] == version_prefix or p["version"].startswith(version_prefix + "."):
                return p
        return {}
    return platforms[-1] if oldest else platforms[0]


def find_1c_platform() -> str:
    """Путь к 1cv8.exe самой свежей найденной платформы ("" если не нашли).
    Оставлен ради обратной совместимости с CFG["path_1c"]."""
    platforms = find_1c_platforms()
    return platforms[0]["exe"] if platforms else ""


def find_java() -> str:
    """Ищет java.exe в стандартных папках установки JDK. Предпочитает старшую версию
    (BSL Language Server требует 17+ — class file 61; более старые JDK не подойдут,
    но найденную самую свежую всё равно стоит проверить при первом использовании)."""
    candidates = []
    for base in (r"C:\Program Files\Java", r"C:\Program Files\Eclipse Adoptium",
                 r"C:\Program Files\Zulu", r"C:\Program Files\Microsoft\jdk*"):
        candidates += glob.glob(base + r"\*\bin\java.exe")
    candidates.sort(reverse=True)
    return candidates[0] if candidates else ""


def find_tesseract() -> str:
    """Ищет tesseract.exe (#39) в стандартных папках установки Tesseract-OCR —
    штатный инсталлятор НЕ добавляет его в PATH автоматически."""
    candidates = []
    for base in (r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR"):
        candidates += glob.glob(base + r"\tesseract.exe")
    return candidates[0] if candidates else ""


def ensure_compiler_db(cfg: dict, timeout: int = 60) -> dict:
    """
    Создаёт ПУСТУЮ файловую ИБ по пути cfg["compiler_db"] — она нужна только
    для сборки .epf (LoadExternalDataProcessorOrReportFromFiles), никакой
    конфигурации/данных ей не требуется.

    #63: создаётся ПЛАТФОРМОЙ СБОРКИ (path_1c_build), а не самой свежей.
    Причина: конфигуратор 8.3.24 не откроет базу, созданную 8.5.1 — версия
    базы новее. Версия-создатель пишется в маркер `.built_by`; если настройка
    BUILD_PLATFORM_VERSION изменилась, база пересоздаётся (терять там нечего,
    она заведомо пустая — но сносим ТОЛЬКО каталог, который сами же и создали,
    см. проверку маркера/1Cv8.1CD ниже).
    """
    path = Path(cfg["compiler_db"])
    exe = cfg.get("path_1c_build") or cfg["path_1c"]
    version = cfg.get("build_platform", "") or Path(exe).parent.parent.name
    marker = path / ".built_by"

    if path.exists() and any(path.iterdir()):
        was = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
        if was == version:
            return {"ok": True, "created": False, "platform": version}
        # чужая версия (или маркера нет — база от старых версий агента):
        # пересоздаём, но только если это действительно наша пустая ИБ
        looks_like_ib = (path / "1Cv8.1CD").exists() or marker.exists()
        if not looks_like_ib:
            return {"ok": False, "created": False, "platform": version,
                    "reason": f"{path} не похож на базу-компилятор (нет 1Cv8.1CD/.built_by) — "
                              f"не трогаю каталог автоматически, разберитесь руками"}
        shutil.rmtree(path, ignore_errors=True)

    path.mkdir(parents=True, exist_ok=True)
    cmd = f'"{exe}" CREATEINFOBASE File="{path}" /DisableStartupMessages'
    r = subprocess.run(cmd, shell=True, timeout=timeout)
    ok = r.returncode == 0
    if ok:
        marker.write_text(version, encoding="utf-8")
    return {"ok": ok, "created": True, "platform": version, "returncode": r.returncode}



def check_setup(cfg: dict) -> dict:
    """Диагностика окружения для новой машины/чата — что найдено/чего не хватает."""
    out = {}
    out["path_1c"] = {"value": cfg.get("path_1c", ""), "exists": Path(cfg.get("path_1c", "")).exists()}
    out["java_exe"] = {"value": cfg.get("java_exe", ""), "exists": Path(cfg.get("java_exe", "")).exists()}
    out["compiler_db"] = {"value": cfg.get("compiler_db", ""),
                           "exists": Path(cfg.get("compiler_db", "")).exists()}
    out["bsl_ls_jar"] = {"value": cfg.get("bsl_ls_jar", ""), "exists": Path(cfg.get("bsl_ls_jar", "")).exists()}
    out["yaxunit_cfe"] = {"value": cfg.get("yaxunit_cfe", ""), "exists": Path(cfg.get("yaxunit_cfe", "")).exists()}
    out["epf_runner"] = {"value": cfg.get("epf_runner", ""), "exists": Path(cfg.get("epf_runner", "")).exists()}
    missing = [k for k, v in out.items() if not v["exists"]]
    out["ok"] = not missing
    out["missing"] = missing

    # screenshot_1c_window (#35/#36): pywin32+Pillow — не блокирует ok/missing
    # выше (не нужны для базового цикла run_module/deploy_*), но полезно знать
    # заранее, не дожидаясь ImportError внутри screenshot_1c_window.
    try:
        import win32gui, win32process, win32ui  # noqa: F401
        from PIL import Image as _PILImage  # noqa: F401
        out["screenshot_1c_window"] = {"available": True}
    except ImportError as e:
        out["screenshot_1c_window"] = {"available": False, "reason": repr(e)}
    # OCR (#39): winsdk (Windows OCR) не собирается под текущий Python в этом venv
    # (нет wheel, сборка из исходников требует Visual Studio) — используем Tesseract
    # вместо него, если он реально установлен на диске (штатный инсталлятор Windows
    # PATH не трогает, поэтому проверяем cfg["tesseract_exe"] напрямую, не shutil.which).
    tess_path = cfg.get("tesseract_exe", "")
    tess_exists = bool(tess_path) and Path(tess_path).exists()
    try:
        import pytesseract  # noqa: F401
        pytesseract_ok = True
    except ImportError:
        pytesseract_ok = False
    if tess_exists and pytesseract_ok:
        tessdata = Path(tess_path).parent / "tessdata"
        langs = sorted(p.stem for p in tessdata.glob("*.traineddata")) if tessdata.is_dir() else []
        out["ocr"] = {"available": True, "engine": "tesseract", "tesseract_exe": tess_path, "languages": langs}
    else:
        out["ocr"] = {"available": False, "engine": None,
                       "reason": f"tesseract.exe {'не найден' if not tess_exists else 'найден'} "
                                 f"({tess_path or 'не настроен'}), pytesseract {'ok' if pytesseract_ok else 'НЕ установлен'}"}
    return out


# ---------- #60: автозапуск ИИ-моделей вместе с сервером ----------
# НЕ импортирует fixer.py/embeddings_client.py специально — оба ОНИ импортируют
# config.py, а config.py уже импортирует ЭТОТ модуль (find_1c_platform и т.п.) —
# импорт в обратную сторону дал бы цикл config->bootstrap->fixer->config.
# Поэтому здесь только urllib/subprocess напрямую, без переиспользования их
# HTTP-хелперов.

def _http_ok(url: str, headers: dict = None, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# ============ #62: замок и честная проверка "модель уже загружена" ============
# Найдено вживую (пользователь): модели поднимались ПО НЕСКОЛЬКУ РАЗ. Две
# причины, обе лечатся здесь:
#   1) ensure_models_running звался на КАЖДОМ старте MCP-сервера (то есть на
#      каждый новый чат), даже если фиксер/эмбеддинги в этой сессии не нужны
#      ни разу. Лечится ленивым вызовом со стороны fixer/embeddings_client.
#   2) проверка "уже загружено" шла ПОДСТРОКОЙ по выводу `lms ps`. Пока
#      `lms load` ещё грузит модель, в `ps` её НЕ ВИДНО —два параллельных
#      процесса оба решали, что грузить надо, и LM Studio послушно поднимала
#      ВТОРУЮ копию (lms load без --identifier это позволяет). Лечится
#      межпроцессным замком + проверкой по /v1/models самого сервера.
_MODELS_LOCK_STALE_SEC = 300


def _models_lock_path(cfg: dict) -> Path:
    return Path(cfg.get("work_dir", ".")) / ".models_autostart.lock"


def _acquire_models_lock(cfg: dict, wait_sec: int = 180):
    """
    Межпроцессный замок вокруг загрузки моделей. Возвращает файловый
    дескриптор (снимать через _release_models_lock) или None, если ждали
    дольше wait_sec — в этом случае вызывающий код НЕ грузит ничего сам,
    а просто перепроверяет, что там уже поднял сосед.
    Протухший замок (процесс умер, не сняв) снимается по возрасту файла.
    """
    p = _models_lock_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time()}".encode())
            return fd
        except FileExistsError:
            try:
                age = time.time() - p.stat().st_mtime
            except OSError:
                age = 0.0
            if age > _MODELS_LOCK_STALE_SEC:
                try:
                    p.unlink()
                except OSError:
                    pass
                continue
            if time.time() - t0 > wait_sec:
                return None
            time.sleep(1.0)


def _release_models_lock(cfg: dict, fd) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        _models_lock_path(cfg).unlink()
    except OSError:
        pass


def _server_alive(base_url: str, key: str, timeout: float = 3.0) -> bool:
    """
    Отвечает ли локальный LLM-сервер вообще. ВАЖНО (проверено вживую): у LM
    Studio /v1/models перечисляет ВСЕ СКАЧАННЫЕ модели, а НЕ загруженные в
    память (при включённом JIT она грузит модель на первый запрос), поэтому
    как признак "модель уже в памяти" этот эндпоинт НЕ ГОДИТСЯ — для этого
    только `lms ps`, см. _lms_loaded_keys.
    """
    try:
        req = urllib.request.Request(base_url + "/models",
                                     headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _lms_loaded_keys(lms: str, timeout: int = 15) -> str:
    """
    Вывод `lms ps` — честный ответ на вопрос "что сейчас загружено в память"
    (в отличие от /v1/models, см. _server_alive).

    #62, КОРЕНЬ ПРОБЛЕМЫ "модели грузятся по нескольку раз": раньше читался
    ТОЛЬКО .stdout, а `lms ps` пишет в .stderr — проверено вживую, при пустом
    списке rc=0, stdout='', stderr='No models are currently loaded.'. То есть
    проверка "уже загружено" НИКОГДА не срабатывала, и `lms load` звался
    безусловно на каждый старт MCP-сервера. Читаем ОБА потока.
    """
    try:
        r = subprocess.run([lms, "ps"], capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""


def _ensure_lmstudio(cfg: dict, need: set) -> dict:
    lms = cfg.get("lms_exe", "")
    if not lms or not Path(lms).exists():
        return {"ok": False, "backend": "lmstudio", "reason": f"lms.exe не найден: {lms!r} — поставьте LM Studio (lmstudio.ai)"}

    base_url = cfg.get("fixer_model_base_url") or f"http://localhost:{cfg['fixer_model_port']}/v1"
    key = cfg.get("lm_key", "")
    result = {"ok": True, "backend": "lmstudio", "need": sorted(need), "steps": []}

    # сервер поднимаем, только если порт молчит — иначе это лишний внешний вызов
    # на каждый чат (он же и дёргал окно LM Studio).
    if not _server_alive(base_url, key):
        try:
            subprocess.run([lms, "server", "start", "-p", str(cfg["fixer_model_port"])],
                            capture_output=True, timeout=30)
            result["steps"].append("server_start")
        except Exception as e:
            return {"ok": False, "backend": "lmstudio", "reason": f"lms server start: {e!r}"}
    else:
        result["steps"].append("server_already_up")
    loaded = _lms_loaded_keys(lms)

    def _load(kind: str, model_key: str, extra: list) -> None:
        nonlocal loaded
        if model_key in loaded:
            result["steps"].append(f"{kind}_already_loaded")
            return
        try:
            # --identifier фиксирует имя экземпляра: повторный load с тем же
            # идентификатором не плодит вторую копию модели (см. #62).
            subprocess.run([lms, "load", model_key, "-y", "--identifier", model_key, *extra],
                            capture_output=True, timeout=180)
            loaded = _lms_loaded_keys(lms)   # вторую модель сверяем уже со свежим ps
            result["steps"].append(f"{kind}_loaded")
        except Exception as e:
            result["steps"].append(f"{kind}_load_failed: {e!r}")

    if "fixer" in need and cfg.get("autostart_fixer_model"):
        _load("fixer", cfg["fixer_model_lms_key"], ["-c", str(cfg["fixer_model_context"])])
    if "embed" in need and cfg.get("autostart_embed_model"):
        _load("embed", cfg["embed_model_lms_key"], [])

    return result


def _ensure_llama_server(cfg: dict, need: set) -> dict:
    """
    #59 (ЧЕСТНО НЕ ПРОТЕРЕНО ЖИВЬЮ — на машине автора LM Studio уже стоит, эту
    ветку прогнать не на чем, см. install.ps1 про ту же оговорку). Один
    llama-server.exe = одна модель — фиксер и эмбеддинги на РАЗНЫХ портах
    (в отличие от LM Studio, где оба на одном). Запуск НЕ блокирующий
    (Popen, не run) — модель может докачиваться/грузиться минуты, весь
    MCP-сервер не должен из-за этого зависать на старте; готовность модели
    дальше проверяют сами fixer.qwen_available()/embeddings_client.
    embeddings_available() при первом реальном вызове (та же грациозная
    деградация, что уже была для LM Studio).
    """
    exe = cfg.get("llama_server_exe", "")
    if not exe or not Path(exe).exists():
        return {"ok": False, "backend": "llama_server",
                "reason": f"llama-server.exe не найден: {exe!r} — запустите install.ps1"}

    result = {"ok": True, "backend": "llama_server", "steps": []}

    def _source_args(hf_repo: str, local_gguf: str) -> tuple:
        # #61: если модель скачана вручную (докачка -hf не сработала на
        # машине друга) и лежит по local_gguf — грузим её файлом, без сети.
        if local_gguf and Path(local_gguf).exists():
            return ["-m", local_gguf], "local"
        return ["-hf", hf_repo], "hf"

    if "fixer" in need and cfg.get("autostart_fixer_model"):
        if _http_ok(f"http://127.0.0.1:{cfg['fixer_model_port']}/health"):
            result["steps"].append("fixer_already_running")
        else:
            src_args, src = _source_args(cfg["fixer_model_hf_repo"], cfg.get("fixer_model_local_gguf", ""))
            args = [exe, *src_args, "-p", str(cfg["fixer_model_port"]),
                    "-c", str(cfg["fixer_model_context"]), "--host", "127.0.0.1"]
            try:
                subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result["steps"].append(f"fixer_launched_{src}")
            except Exception as e:
                result["steps"].append(f"fixer_launch_failed: {e!r}")

    if "embed" in need and cfg.get("autostart_embed_model"):
        if _http_ok(f"http://127.0.0.1:{cfg['embed_model_port']}/health"):
            result["steps"].append("embed_already_running")
        else:
            src_args, src = _source_args(cfg["embed_model_hf_repo"], cfg.get("embed_model_local_gguf", ""))
            args = [exe, *src_args, "-p", str(cfg["embed_model_port"]),
                    "--embeddings", "--host", "127.0.0.1"]
            try:
                subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result["steps"].append(f"embed_launched_{src}")
            except Exception as e:
                result["steps"].append(f"embed_launch_failed: {e!r}")

    return result


def ensure_models_running(cfg: dict, need=None) -> dict:
    """
    #60/#62: автозапуск ИИ-моделей. ЛЕНИВЫЙ: зовётся не при старте
    MCP-сервера, а из fixer.qwen_available()/embeddings_client.
    embeddings_available() в момент, когда модель реально понадобилась —
    сессия, не трогавшая фиксер, моделей не поднимает вообще. need —
    подмножество {"fixer", "embed"}, None = обе. Best-effort и НИКОГДА не
    бросает исключение наружу — если модели не поднялись, heal_module/
    fix_snippet/search_reference_semantic просто вернут "недоступно" при
    первом реальном вызове (та же грациозная деградация, что уже
    задокументирована для LM Studio в целом, см. HANDOFF "Опциональный
    Qwen"), СЕРВЕР В ЦЕЛОМ продолжает работать даже если эта функция
    полностью провалилась.

    Отключается конфигом (AUTOSTART_FIXER_MODEL/AUTOSTART_EMBED_MODEL в
    config.py) — если обе выключены, ничего не делает вообще (для тех, кто
    предпочитает поднимать модели вручную).
    """
    if not cfg.get("autostart_fixer_model") and not cfg.get("autostart_embed_model"):
        return {"ok": True, "skipped": True, "reason": "AUTOSTART_FIXER_MODEL/AUTOSTART_EMBED_MODEL оба выключены"}
    need = {"fixer", "embed"} if need is None else set(need)
    fd = _acquire_models_lock(cfg)
    if fd is None:
        # сосед грузит дольше, чем мы готовы ждать — не грузим параллельно
        # (иначе получим вторую копию модели, см. #62), пусть вызывающий код
        # сам решит по своей проверке доступности.
        return {"ok": True, "skipped": True, "reason": "загрузку моделей уже выполняет другой процесс"}
    try:
        backend = cfg.get("model_backend", "lmstudio")
        if backend == "llama_server":
            return _ensure_llama_server(cfg, need)
        return _ensure_lmstudio(cfg, need)
    except Exception as e:
        return {"ok": False, "reason": f"ensure_models_running упал неожиданно: {e!r}"}
    finally:
        _release_models_lock(cfg, fd)
