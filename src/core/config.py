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

from src.onec.bootstrap import (find_1c_platform, find_1c_platforms, pick_platform,
                                find_java, find_tesseract)

# #21: WORK теперь ВНУТРИ проекта (было на Desktop\vkr\diploma, человек попросил
# консолидировать) — считается ОТНОСИТЕЛЬНО расположения этого файла, так что
# перенос/переименование папки проекта ничего не ломает.
# #29: файл переехал в src/core/ — до КОРНЯ проекта теперь на 2 уровня выше.
_ROOT = Path(__file__).resolve().parent.parent.parent
WORK = str(_ROOT / "work")
TOOLS = str(_ROOT / "tools")   # сторонние bin/jar/cfe, не 1С-проект

# #63: КОРНИ поиска платформ. Стандартные (Program Files) зашиты в
# bootstrap._DEFAULT_PLATFORM_ROOTS, здесь — только нестандартные: без этой
# строки папка на D: находилась ТОЛЬКО через хардкод _PATH_1C_HINT ниже.
PLATFORM_ROOTS = [r"D:\1сБазы\платформы"]

# #63: РАЗВЯЗКА "чем собирать" и "чем запускать" — раньше это был один path_1c,
# и он делал две несовместимые работы.
#   BUILD — платформа, которой собирается AgentCode.epf. Обработка, собранная
#           МЛАДШЕЙ платформой, открывается во всех СТАРШИХ, наоборот нет —
#           поэтому для работы в старых базах сюда ставят версию постарше.
#           База-компилятор создаётся ЭТОЙ ЖЕ платформой (ensure_compiler_db)
#           и пересоздаётся при смене версии.
#           ГРАБЛЯ (поймана вживую, #63): указать здесь младшую платформу
#           НЕДОСТАТОЧНО. Исходник work\ВнешняяОбработкаВыполнение.xml
#           имеет СВОЮ версию формата выгрузки (сейчас 2.19 — её пишет 8.5.1),
#           и конфигуратор 8.3.24 такой файл не читает вовсе: "Неизвестная
#           версия формата 2.19", модальное окно, сборка не проходит. Чтобы
#           реально собирать младшей платформой, XML надо ПЕРЕВЫГРУЗИТЬ ею же
#           (DumpExternalDataProcessorOrReportToFiles). Пока это не сделано —
#           оставляйте "" (самая свежая), иначе сборка сломается.
#   RUN   — платформа, которой запускается клиент/конфигуратор. "" = самая
#           свежая. Для веб-баз (ws=) нужен ТОНКИЙ клиент 1cv8c.exe той же
#           версии: толстый по ws не подключается в принципе.
# Значение — точная версия или её начало ("8.3.24" подойдёт к "8.3.24.1624").
# #81: HTTP-эндпоинт для раннера поднимается ВМЕСТЕ с MCP-сервером, то есть
# работает ровно пока запущен Claude — раннеру не нужно ничего включать руками.
# Хост "0.0.0.0" нужен, если перед агентом стоит Caddy в Docker: контейнер
# ходит на host.docker.internal, а это НЕ петля. Если прокси не используете —
# ставьте "127.0.0.1".
HTTP_AUTOSTART = True
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 1533

BUILD_PLATFORM_VERSION = ""
RUN_PLATFORM_VERSION = ""

_PATH_1C_HINT = r"D:\1сБазы\платформы\8.5.1.1343\bin\1cv8.exe"
_JAVA_HINT = r"C:\Program Files\Java\jdk-21.0.8\bin\java.exe"
PATH_1C = _PATH_1C_HINT if Path(_PATH_1C_HINT).exists() else (find_1c_platform() or _PATH_1C_HINT)

_PLATFORMS = find_1c_platforms(PLATFORM_ROOTS)
# oldest=False: умолчание "" = САМАЯ СВЕЖАЯ, то есть поведение как до #63.
# Младшая платформа включается только явным BUILD_PLATFORM_VERSION — и только
# вместе с перевыгрузкой XML, см. грабли выше.
_BUILD = pick_platform(_PLATFORMS, BUILD_PLATFORM_VERSION)
_RUN = pick_platform(_PLATFORMS, RUN_PLATFORM_VERSION)
# fallback на PATH_1C: если платформ не нашли вовсе (или заданная версия не
# установлена) — ведём себя ровно как раньше, а не падаем на старте.
PATH_1C_BUILD = _BUILD.get("exe") or PATH_1C
PATH_1C_RUN = _RUN.get("exe") or PATH_1C
PATH_1C_RUN_THIN = _RUN.get("thin") or str(Path(PATH_1C_RUN).with_name("1cv8c.exe"))
BUILD_PLATFORM_RESOLVED = _BUILD.get("version", "")
RUN_PLATFORM_RESOLVED = _RUN.get("version", "")
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

# #61 (реальный случай на машине друга): install.ps1 ставит llama-server.exe
# ("движок"), но `-hf <repo>` докачка GGUF с Hugging Face иногда не работает
# (сеть/регион) — тогда gguf передают отдельно (диск/облако) и кладут руками
# сюда. bootstrap.py::_ensure_llama_server проверяет файл по этому пути и, если
# он есть, запускает llama-server с `-m <путь>` вместо `-hf <repo>` (без сети
# вообще). Если файла нет — как раньше, автозакачка через -hf.
FIXER_MODEL_LOCAL_GGUF = TOOLS + r"\models\qwen2.5-coder-7b-instruct.gguf"
EMBED_MODEL_LOCAL_GGUF = TOOLS + r"\models\embeddinggemma-300M.gguf"


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
    # #63: см. BUILD_PLATFORM_VERSION/RUN_PLATFORM_VERSION выше.
    "path_1c_build": PATH_1C_BUILD,
    "path_1c_run":   PATH_1C_RUN,
    "path_1c_run_thin": PATH_1C_RUN_THIN,
    "build_platform": BUILD_PLATFORM_RESOLVED,
    "run_platform":  RUN_PLATFORM_RESOLVED,
    "platform_roots": PLATFORM_ROOTS,
    "compiler_db":   WORK + r"\CompilerDB",
    "xml":           WORK + r"\ВнешняяОбработкаВыполнение.xml",
    # ВАЖНО: это ДВА РАЗНЫХ .epf, не путать (см. HANDOFF.md "Ключевые уроки"):
    #   epf_build  — headless-обработка БЕЗ формы, которую glue.py пересобирает
    #                НА КАЖДЫЙ run_module/heal_module/warmup из xml+src_bsl выше.
    #   epf_runner — обработка С ФОРМОЙ (кнопка/таймер), которую человек открывает
    #                вручную или через start_runner — НИКОГДА не пересобирается
    #                кодом, трогать её файл на диск нельзя.
    "epf_build":     WORK + r"\AgentCode.epf",
    "epf_runner":    str(_ROOT / "ВнешняяОбработка" / "ВнешняяОбработка.epf"),
    "epf_runner_src": str(_ROOT / "ВнешняяОбработка"),  # распакованный исходник (Dump/LoadExternalDataProcessorOrReportToFiles)
    #   epf_runner_ordinary — раннер для конфигураций с ОБЫЧНЫМ ПРИЛОЖЕНИЕМ
    #                (УПП 1.3 и прочие «восьмёрки-двойки»). Там управляемая
    #                форма epf_runner не открывается ВООБЩЕ, поэтому этот
    #                раннер сделан БЕЗ ФОРМЫ: ENTERPRISE /Execute выполняет
    #                тело модуля объекта, и цикл опроса крутится прямо в нём.
    #                Работает ТОЛЬКО по HTTP-транспорту (папки обмена не знает),
    #                адрес агента принимает через /C<https://хост#токен>.
    #                Собирается из исходника ПЛАТФОРМОЙ НЕ НОВЕЕ целевой базы.
    "epf_runner_ordinary": str(_ROOT / "ВнешняяОбработкаОбычная" / "РаннерОбычный.epf"),
    "epf_runner_ordinary_src": str(_ROOT / "ВнешняяОбработкаОбычная"),
    # #21: папка, которую start_runner передаёт форме через /C — форма читает
    # её из ПараметрЗапуска и строит error.txt/logs.txt/AgentCode.epf от неё,
    # вместо хардкода. См. Forms/Форма/Ext/Form/Module.bsl внутри epf_runner_src.
    "work_dir":      WORK,
    "src_bsl":       WORK + r"\ВнешняяОбработкаВыполнение\Ext\ObjectModule.bsl",
    "error_txt":     WORK + r"\error.txt",
    "logs_txt":      WORK + r"\logs.txt",
    "compile_log":   WORK + r"\compile.log",
    # #66: потолок на ОДИН запуск конфигуратора при сборке .epf. Раньше сборка
    # шла вообще без таймаута — модальное окно вешало run_module навсегда.
    "build_timeout": 120,
    # #67 быстрый путь: код задания текстом (без сборки .epf) + объявление
    # протокола живым раннером. direct_timeout короткий НАМЕРЕННО — если раннер
    # старый, откат на сборку должен быть быстрым, а не через полные 50с.
    "task_bsl":      WORK + r"\task.bsl",
    "runner_txt":    WORK + r"\runner.txt",
    "direct_timeout": 15,
    # #70: сколько ждём ответ раннера, пришедшего по HTTP (он сам держит связь,
    # поэтому потолок общий, а не отдельный на быстрый/медленный путь).
    "http_timeout": 60,
    "http_autostart": HTTP_AUTOSTART,
    "http_host": HTTP_HOST,
    "http_port": HTTP_PORT,
    "target_module": "ВнешняяОбработкаВыполнение.МодульОбъекта",

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
    # Куда upload_file_to_runner кладёт файлы НА МАШИНЕ РАННЕРА. Рабочие базы
    # подключаются удалённо, поэтому сервер 1С не видит локальных путей агента
    # (ОшибкаДоступаКЛокальномуФайлу) — файл надо сперва перелить туда.
    # ПУСТО = временный каталог СЕРВЕРА (КаталогВременныхФайлов(), вычисляется
    # на той стороне): существует всегда, прав хватает, следов не оставляет.
    # Свой путь — сюда; на один вызов перекрывается параметром remote_dir.
    "remote_upload_dir": "",
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
    "fixer_model_base_url": FIXER_MODEL_BASE_URL,
    "embed_model_base_url": EMBED_MODEL_BASE_URL,
    "lm_key":               LM_KEY,
    "lms_exe":               LMS_EXE,
    "llama_server_exe":     LLAMA_SERVER_EXE,
    "fixer_model_local_gguf": FIXER_MODEL_LOCAL_GGUF,
    "embed_model_local_gguf": EMBED_MODEL_LOCAL_GGUF,
}
