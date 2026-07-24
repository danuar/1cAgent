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
import subprocess
import urllib.request
from pathlib import Path


def find_1c_platform() -> str:
    """Ищет 1cv8.exe в стандартных папках установки платформы. Новейшая версия — первая."""
    candidates = []
    for base in (r"C:\Program Files\1cv8", r"C:\Program Files (x86)\1cv8"):
        candidates += glob.glob(base + r"\*\bin\1cv8.exe")
    candidates.sort(reverse=True)
    return candidates[0] if candidates else ""


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
    Создаёт ПУСТУЮ файловую ИБ по пути cfg["compiler_db"], если её там ещё нет —
    нужна только для сборки .epf (LoadExternalDataProcessorOrReportFromFiles),
    никакой конфигурации/данных ей не требуется. Идемпотентно: если каталог уже
    не пуст, ничего не делает.
    """
    path = Path(cfg["compiler_db"])
    if path.exists() and any(path.iterdir()):
        return {"ok": True, "created": False}
    path.mkdir(parents=True, exist_ok=True)
    cmd = f'"{cfg["path_1c"]}" CREATEINFOBASE File="{path}" /DisableStartupMessages'
    r = subprocess.run(cmd, shell=True, timeout=timeout)
    return {"ok": r.returncode == 0, "created": True, "returncode": r.returncode}


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


def _ensure_lmstudio(cfg: dict) -> dict:
    lms = cfg.get("lms_exe", "")
    if not lms or not Path(lms).exists():
        return {"ok": False, "backend": "lmstudio", "reason": f"lms.exe не найден: {lms!r} — поставьте LM Studio (lmstudio.ai)"}

    result = {"ok": True, "backend": "lmstudio", "steps": []}
    try:
        subprocess.run([lms, "server", "start", "-p", str(cfg["fixer_model_port"])],
                        capture_output=True, timeout=30)
        result["steps"].append("server_start")
    except Exception as e:
        return {"ok": False, "backend": "lmstudio", "reason": f"lms server start: {e!r}"}

    # #58 (найдено вживую): lms ps показывает УЖЕ ЗАГРУЖЕННЫЕ модели — не
    # перезагружаем то, что и так работает (иначе на каждый рестарт сервера
    # модель бы перегружалась заново, теряя время без нужды).
    try:
        loaded = subprocess.run([lms, "ps"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        loaded = ""

    if cfg.get("autostart_fixer_model") and cfg["fixer_model_lms_key"] not in loaded:
        try:
            subprocess.run([lms, "load", cfg["fixer_model_lms_key"], "-y",
                             "-c", str(cfg["fixer_model_context"])],
                            capture_output=True, timeout=180)
            result["steps"].append("fixer_loaded")
        except Exception as e:
            result["steps"].append(f"fixer_load_failed: {e!r}")
    elif cfg.get("autostart_fixer_model"):
        result["steps"].append("fixer_already_loaded")

    if cfg.get("autostart_embed_model") and cfg["embed_model_lms_key"] not in loaded:
        try:
            subprocess.run([lms, "load", cfg["embed_model_lms_key"], "-y"],
                            capture_output=True, timeout=120)
            result["steps"].append("embed_loaded")
        except Exception as e:
            result["steps"].append(f"embed_load_failed: {e!r}")
    elif cfg.get("autostart_embed_model"):
        result["steps"].append("embed_already_loaded")

    return result


def _ensure_llama_server(cfg: dict) -> dict:
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

    if cfg.get("autostart_fixer_model"):
        if _http_ok(f"http://127.0.0.1:{cfg['fixer_model_port']}/health"):
            result["steps"].append("fixer_already_running")
        else:
            args = [exe, "-hf", cfg["fixer_model_hf_repo"], "-p", str(cfg["fixer_model_port"]),
                    "-c", str(cfg["fixer_model_context"]), "--host", "127.0.0.1"]
            try:
                subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result["steps"].append("fixer_launched")
            except Exception as e:
                result["steps"].append(f"fixer_launch_failed: {e!r}")

    if cfg.get("autostart_embed_model"):
        if _http_ok(f"http://127.0.0.1:{cfg['embed_model_port']}/health"):
            result["steps"].append("embed_already_running")
        else:
            args = [exe, "-hf", cfg["embed_model_hf_repo"], "-p", str(cfg["embed_model_port"]),
                    "--embeddings", "--host", "127.0.0.1"]
            try:
                subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result["steps"].append("embed_launched")
            except Exception as e:
                result["steps"].append(f"embed_launch_failed: {e!r}")

    return result


def ensure_models_running(cfg: dict) -> dict:
    """
    #60: автозапуск ИИ-моделей вместе с сервером — вызывается ОДИН РАЗ из
    mcp_server.py при каждом старте, ДО mcp.run(). Best-effort и НИКОГДА не
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
    try:
        backend = cfg.get("model_backend", "lmstudio")
        if backend == "llama_server":
            return _ensure_llama_server(cfg)
        return _ensure_lmstudio(cfg)
    except Exception as e:
        return {"ok": False, "reason": f"ensure_models_running упал неожиданно: {e!r}"}
