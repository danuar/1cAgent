# -*- coding: utf-8 -*-
"""
Общий конфиг путей 1С — для раннера (run_live) и MCP-сервера.

#15/#19 портативность: path_1c/java_exe сначала пробуют захардкоженный путь
(не трогаем то, что уже работает на этой машине) и падают на автопоиск
(bootstrap.py) только если его нет на диске — так проект переносится на
другую машину без правки этого файла. ib_connection (тестовая/рабочая база)
принципиально НЕ хардкодится нигде — передаётся явно в каждый вызов
(см. ib_connection.py) через чат.
"""
from pathlib import Path

from src.onec.bootstrap import find_1c_platform, find_java, find_tesseract

# #21: WORK теперь ВНУТРИ проекта (было на Desktop\vkr\diploma, человек попросил
# консолидировать) — считается ОТНОСИТЕЛЬНО расположения этого файла, так что
# перенос/переименование папки проекта ничего не ломает.
# #29: файл переехал в src/core/ — до КОРНЯ проекта теперь на 2 уровня выше.
_ROOT = Path(__file__).resolve().parent.parent.parent
WORK = str(_ROOT / "work")
TOOLS = str(_ROOT / "tools")   # сторонние bin/jar/cfe, не 1С-проект

_PATH_1C_HINT = r"C:\Program Files\1cv8\8.3.26.1498\bin\1cv8.exe"
_JAVA_HINT = r"C:\Program Files\Java\jdk-21.0.8\bin\java.exe"
PATH_1C = _PATH_1C_HINT if Path(_PATH_1C_HINT).exists() else (find_1c_platform() or _PATH_1C_HINT)
JAVA_EXE = _JAVA_HINT if Path(_JAVA_HINT).exists() else (find_java() or _JAVA_HINT)

# #38: локальный дамп ПОЛНОЙ типовой конфигурации (для search_reference/
# read_reference_snippet, дешёвые маленькие XML-примеры без чтения огромных
# типовых файлов целиком) — личный выбор пользователя, автопоиска НЕТ (в
# отличие от path_1c/java_exe, это не стандартный путь установки чего-либо).
# Пусто, если папки нет на диске — search_reference тогда вернёт понятную
# ошибку вместо непонятного FileNotFoundError.
_REFERENCE_CONFIG_HINT = r"C:\Users\danua\Desktop\vkr\Конфигурация"
REFERENCE_CONFIG = _REFERENCE_CONFIG_HINT if Path(_REFERENCE_CONFIG_HINT).exists() else ""

# #39: Tesseract OCR для screenshot_1c_window — штатный инсталлятор Windows НЕ
# добавляет tesseract.exe в PATH, поэтому автопоиск по стандартным папкам
# установки нужен так же, как для path_1c/java_exe (не shutil.which).
_TESSERACT_HINT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_EXE = _TESSERACT_HINT if Path(_TESSERACT_HINT).exists() else (find_tesseract() or "")

# #60: автозапуск ИИ-моделей ВМЕСТЕ с сервером (см. bootstrap.py::
# ensure_models_running, вызывается из mcp_server.py при каждом старте) — то,
# ради чего в итоге и строился install.ps1 (#57-59). Два бэкенда:
#   "lmstudio"     — через её CLI (lms server start/load), ОБЕ модели на
#                    ОДНОМ порту FIXER_MODEL_PORT (LM Studio сама умеет
#                    держать несколько загруженных моделей одновременно).
#   "llama_server" — отдельный llama-server.exe (см. install.ps1
#                    Install-StandaloneLlamaServer) — ОДИН процесс = ОДНА
#                    модель, поэтому эмбеддинг-модели нужен СВОЙ порт
#                    (EMBED_MODEL_PORT), фиксер и эмбеддинги НЕ делят порт.
# "auto" — определяется по наличию lms.exe на диске (см. _detect_model_backend).
MODEL_BACKEND = "auto"
AUTOSTART_FIXER_MODEL = True
AUTOSTART_EMBED_MODEL = True
FIXER_MODEL_HF_REPO = "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF"
EMBED_MODEL_HF_REPO = "ggml-org/embeddinggemma-300M-GGUF"
# #58 (найдено вживую): lms load/ps используют СВОИ внутренние идентификаторы,
# НЕ совпадающие с полным HF URL, нужным для lms get — подтверждено реальным
# запросом (lms ls) на машине автора.
FIXER_MODEL_LMS_KEY = "qwen2.5-coder-7b-instruct"
EMBED_MODEL_LMS_KEY = "text-embedding-embeddinggemma-300m"
FIXER_MODEL_PORT = 1235
EMBED_MODEL_PORT = 1236   # используется, только если реально выбран backend="llama_server"
# #56 (проверено вживую, см. HANDOFF_ARCHIVE.md #54): 32К — рабочий потолок
# контекста фиксера на 8ГБ VRAM ОДНОВРЕМЕННО с эмбеддинг-моделью — на 40К уже
# были проблемы (похоже на offload в RAM). Не поднимать без причины.
FIXER_MODEL_CONTEXT = 32000
LM_KEY = "sk-lm-FQkn7Xhd:yYxzccoJ7B04iFDN8hu5"   # локальный ключ LM Studio (localhost-only, см. HANDOFF)
LMS_EXE = str(Path.home() / ".lmstudio" / "bin" / "lms.exe")
LLAMA_SERVER_EXE = TOOLS + r"\llama-server\llama-server.exe"   # см. install.ps1 Install-StandaloneLlamaServer


def _detect_model_backend() -> str:
    if MODEL_BACKEND != "auto":
        return MODEL_BACKEND
    if Path(LMS_EXE).exists():
        return "lmstudio"
    if Path(LLAMA_SERVER_EXE).exists():
        return "llama_server"
    return "lmstudio"   # ничего не нашли — безопасный default, ensure_models_running сам честно сообщит об отсутствии


MODEL_BACKEND_RESOLVED = _detect_model_backend()
FIXER_MODEL_BASE_URL = f"http://localhost:{FIXER_MODEL_PORT}/v1"
EMBED_MODEL_BASE_URL = (f"http://localhost:{EMBED_MODEL_PORT}/v1" if MODEL_BACKEND_RESOLVED == "llama_server"
                         else FIXER_MODEL_BASE_URL)

CFG = {
    "path_1c":       PATH_1C,
    "compiler_db":   WORK + r"\CompilerDB",
    "xml":           WORK + r"\ВнешняяОбработкаИИАгентВыполнение.xml",
    # ВАЖНО: это ДВА РАЗНЫХ .epf, не путать (см. HANDOFF.md "Ключевые уроки"):
    #   epf_build  — headless-обработка БЕЗ формы, которую glue.py пересобирает
    #                НА КАЖДЫЙ run_module/heal_module/warmup из xml+src_bsl выше.
    #   epf_runner — обработка С ФОРМОЙ (кнопка/таймер), которую человек открывает
    #                вручную или через start_runner — НИКОГДА не пересобирается
    #                кодом, трогать её файл на диск нельзя.
    "epf_build":     WORK + r"\AgentCode.epf",
    "epf_runner":    str(_ROOT / "ВнешняяОбработкаИИАгент" / "ВнешняяОбработкаИИАгент.epf"),
    "epf_runner_src": str(_ROOT / "ВнешняяОбработкаИИАгент"),  # распакованный исходник (Dump/LoadExternalDataProcessorOrReportToFiles)
    # #21: папка, которую start_runner передаёт форме через /C — форма читает
    # её из ПараметрЗапуска и строит error.txt/logs.txt/AgentCode.epf от неё,
    # вместо хардкода. См. Forms/Форма/Ext/Form/Module.bsl внутри epf_runner_src.
    "work_dir":      WORK,
    "src_bsl":       WORK + r"\ВнешняяОбработкаИИАгентВыполнение\Ext\ObjectModule.bsl",
    "error_txt":     WORK + r"\error.txt",
    "logs_txt":      WORK + r"\logs.txt",
    "compile_log":   WORK + r"\compile.log",
    "target_module": "ВнешняяОбработкаИИАгентВыполнение.МодульОбъекта",

    # #6: качественные гейты (см. HANDOFF.md) — скачать вручную, бинарники в репу не кладём
    # системный java (PATH) часто старее 17 (class file 61) — не трогаем системный
    # PATH, берём конкретный java.exe явно (см. PATH_1C/JAVA_EXE выше).
    "java_exe":      JAVA_EXE,
    "bsl_ls_jar":    TOOLS + r"\bsl-language-server.jar",   # releases/latest, файл *-exec.jar
    "yaxunit_cfe":   TOOLS + r"\YAxUnit.cfe",               # bia-technologies/yaxunit releases/latest
    "yaxunit_ext":   "YAXUNIT",                             # имя расширения после подключения
    "tests_report":  WORK + r"\yaxunit_report.json",
    "tests_exit":    WORK + r"\yaxunit_exit.txt",

    # #16/#18: рабочая папка для файловой правки расширений (module_deploy.py) и
    # прочего служебного — ВСЁ временное/сгенерированное живёт тут, не в корне проекта.
    "runtime_dir":   str(_ROOT / "runtime"),
    "reference_config": REFERENCE_CONFIG,
    "tesseract_exe": TESSERACT_EXE,

    # #60: автозапуск моделей — см. bootstrap.py::ensure_models_running.
    "model_backend":        MODEL_BACKEND_RESOLVED,
    "autostart_fixer_model": AUTOSTART_FIXER_MODEL,
    "autostart_embed_model": AUTOSTART_EMBED_MODEL,
    "fixer_model_hf_repo":  FIXER_MODEL_HF_REPO,
    "embed_model_hf_repo":  EMBED_MODEL_HF_REPO,
    "fixer_model_lms_key":  FIXER_MODEL_LMS_KEY,
    "embed_model_lms_key":  EMBED_MODEL_LMS_KEY,
    "fixer_model_port":     FIXER_MODEL_PORT,
    "embed_model_port":     EMBED_MODEL_PORT,
    "fixer_model_context":  FIXER_MODEL_CONTEXT,
    "lm_key":               LM_KEY,
    "lms_exe":               LMS_EXE,
    "llama_server_exe":     LLAMA_SERVER_EXE,
}
