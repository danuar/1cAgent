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
