<#
.SYNOPSIS
    Разовый установщик зависимостей 1cAgent — РАЗВЁРТЫВАНИЕ, не запуск сервера
    (запуск/автозагрузка моделей — src/onec/bootstrap.py::ensure_models_running,
    вызывается из mcp_server.py при каждом старте, сюда не входит).

.DESCRIPTION
    Что умеет ставить сам (проверенные публичные источники, версии подтверждены
    вживую на реальном GitHub API на момент написания). ВСЁ качается НАПРЯМУЮ
    С ОФИЦИАЛЬНЫХ ИСТОЧНИКОВ (GitHub Releases своих проектов / Hugging Face) —
    #59: НИКАКОГО собственного облака/зеркала не нужно (обсуждали в чате
    self-host на статик IP+FTP — отказались; после того, как выяснилось, что
    и LM Studio (`lms get`), и голый `llama-server -hf` одинаково умеют качать
    ПРЯМО с Hugging Face, необходимость в промежуточном зеркале отпала
    целиком — просто клонируете репозиторий и запускаете этот скрипт):
      - Tesseract OCR (официальный инсталлятор, tesseract-ocr/tesseract releases)
      - BSL Language Server (1c-syntax/bsl-language-server releases, *-exec.jar)
      - YAxUnit (bia-technologies/yaxunit releases, .cfe)
      - 2 ИИ-модели — НАПРЯМУЮ С HUGGING FACE: через LM Studio (`lms get
        <полный HF URL>`), если она найдена на диске; ИНАЧЕ отдельный
        `llama-server.exe` (ggml-org/llama.cpp releases) с флагом `-hf
        <repo>` (та же прямая закачка с HF, без LM Studio вообще).

    Что НЕ умеет и не должен (лицензионная стена, см. обсуждение в чате):
      - Платформу 1С:Предприятие (1cv8.exe) — только детект + инструкция.
      - Конфигурацию 1С:ERP АПК (эталонный корпус для search_reference*) —
        только детект + инструкция (выгрузка из ЛИЧНОЙ лицензионной базы).

    ЧЕСТНО: путь "LM Studio НЕ найдена -> голый llama-server" НЕ протестирован
    вживую (на машине автора LM Studio уже стоит) — структура download-логики
    подтверждена реальными URL (curl HEAD, 302), но сам запуск llama-server.exe
    как поднявшегося сервера — только по документации разработчика llama.cpp,
    не проверено. Если на машине друга это не сработает с первого раза — см.
    комментарии у Install-StandaloneLlamaServer ниже, там же лежит запасной
    план (руками поставить LM Studio, она гарантированно проверена в этом
    проекте весь текущий сезон работы).

.NOTES
    Запуск: powershell -ExecutionPolicy Bypass -File install.ps1
#>

[CmdletBinding()]
param(
    # Пропустить шаги, если не нужны (например, повторный запуск после сбоя на
    # каком-то шаге — не перекачивать то, что уже встало).
    [switch]$SkipTesseract,
    [switch]$SkipBslLs,
    [switch]$SkipYAxUnit,
    [switch]$SkipModels,

    # #58: ИИ-модели — это несколько ГБ, спрашиваем интерактивно, ставить ли,
    # если запускающий явно НЕ сказал -SkipModels И НЕ дал -Yes (для
    # автоматических/неинтерактивных прогонов, например из CI — без -Yes там
    # Read-Host зависнет, ждать некому).
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RootDir = $PSScriptRoot
$ToolsDir = Join-Path $RootDir "tools"
$ModelsDir = Join-Path $RootDir "tools\models"

function Write-Step($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Write-Ok($text) {
    Write-Host "  [OK] $text" -ForegroundColor Green
}

function Write-Warn($text) {
    Write-Host "  [!] $text" -ForegroundColor Yellow
}

function Write-Err($text) {
    Write-Host "  [X] $text" -ForegroundColor Red
}

# ---------- 1. Платформа 1С — ТОЛЬКО детект, лицензионная стена ----------
function Test-1CPlatform {
    Write-Step "Платформа 1С:Предприятие"
    $candidates = @()
    foreach ($base in @("C:\Program Files\1cv8", "C:\Program Files (x86)\1cv8")) {
        if (Test-Path $base) {
            $candidates += Get-ChildItem -Path $base -Filter "1cv8.exe" -Recurse -ErrorAction SilentlyContinue
        }
    }
    if ($candidates.Count -gt 0) {
        # #57 (найдено вживую — та же категория бага, что и в Test-Java): на
        # машине оказалось ДВЕ версии платформы (8.3.24.1624 и 8.3.26.1498) —
        # без сортировки порядок Get-ChildItem не гарантирует новейшую версию
        # первой (совпало в этот раз, но полагаться на это нельзя).
        $newest = $candidates | Sort-Object FullName -Descending | Select-Object -First 1
        Write-Ok "найдена: $($newest.FullName)"
        return $true
    }
    Write-Err "1cv8.exe НЕ найден в стандартных папках установки."
    Write-Host "  Платформу нужно поставить САМОСТОЯТЕЛЬНО — это лицензионный" -ForegroundColor Yellow
    Write-Host "  продукт 1С, публичного дистрибутива для автоскачивания нет." -ForegroundColor Yellow
    Write-Host "  Получить: личный кабинет портала 1С (releases.1c.ru) при" -ForegroundColor Yellow
    Write-Host "  наличии действующей лицензии/подписки." -ForegroundColor Yellow
    return $false
}

# ---------- 2. Эталонный корпус 1С:ERP АПК — ТОЖЕ только детект ----------
function Test-ReferenceConfig {
    Write-Step "Эталонная конфигурация 1С:ERP АПК (для search_reference*)"
    $configPath = Join-Path $RootDir "src\core\config.py"
    $hint = Select-String -Path $configPath -Pattern '_REFERENCE_CONFIG_HINT\s*=\s*r"([^"]+)"' -ErrorAction SilentlyContinue
    $path = if ($hint) { $hint.Matches[0].Groups[1].Value } else { $null }
    if ($path -and (Test-Path $path)) {
        Write-Ok "найдена: $path"
        return $true
    }
    Write-Warn "Не найдена — ОПЦИОНАЛЬНО (search_reference/search_reference_semantic не заработают без неё, остальной сервер работает нормально)."
    Write-Host "  Это ТОЖЕ лицензионный продукт 1С, публично не распространяется." -ForegroundColor Yellow
    Write-Host "  Получить можно, выгрузив ИЗ СВОЕЙ лицензионной ERP-базы:" -ForegroundColor Yellow
    Write-Host "  Конфигуратор -> Конфигурация -> Выгрузить конфигурацию в файлы." -ForegroundColor Yellow
    Write-Host "  Затем прописать путь в src/core/config.py (_REFERENCE_CONFIG_HINT)." -ForegroundColor Yellow
    return $false
}

# ---------- 3. Tesseract OCR ----------
function Install-Tesseract {
    Write-Step "Tesseract OCR"
    $existing = Get-ChildItem -Path "C:\Program Files\Tesseract-OCR", "C:\Program Files (x86)\Tesseract-OCR" `
                    -Filter "tesseract.exe" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Ok "уже установлен: $($existing[0].FullName)"
        return
    }
    # #57: URL подтверждён вживую (curl -I -> 302 на реальный релиз), см. докстринг файла.
    $url = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe"
    $installer = Join-Path $env:TEMP "tesseract-ocr-setup.exe"
    Write-Host "  Скачиваю $url ..."
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    Write-Host "  Устанавливаю тихо (может занять минуту)..."
    # /S — тихая установка (NSIS-инсталлятор), стандартный флаг для этого билда.
    Start-Process -FilePath $installer -ArgumentList "/S" -Wait
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
    if (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe") {
        Write-Ok "установлен."
    } else {
        Write-Err "установка не подтвердилась — проверьте руками (C:\Program Files\Tesseract-OCR)."
    }
}

# ---------- 4. BSL Language Server ----------
function Install-BslLanguageServer {
    Write-Step "BSL Language Server"
    $dest = Join-Path $ToolsDir "bsl-language-server.jar"
    if (Test-Path $dest) {
        Write-Ok "уже скачан: $dest"
        return
    }
    # #57: версия/имя ассета подтверждены реальным GitHub API на момент написания —
    # если к моменту запуска вышла новая версия, замените v1.0.5 на актуальную
    # (github.com/1c-syntax/bsl-language-server/releases/latest).
    $url = "https://github.com/1c-syntax/bsl-language-server/releases/download/v1.0.5/bsl-language-server-1.0.5-exec.jar"
    New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
    Write-Host "  Скачиваю $url ..."
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Ok "скачан: $dest"
}

# ---------- 5. YAxUnit ----------
function Install-YAxUnit {
    Write-Step "YAxUnit"
    $dest = Join-Path $ToolsDir "YAxUnit.cfe"
    if (Test-Path $dest) {
        Write-Ok "уже скачан: $dest"
        return
    }
    # #57: подтверждено реальным GitHub API — актуальная версия на момент написания.
    $url = "https://github.com/bia-technologies/yaxunit/releases/download/25.12/YAxUnit-25.12.cfe"
    New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
    Write-Host "  Скачиваю $url ..."
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    Write-Ok "скачан: $dest"
}

# ---------- 6. Java (нужна для BSL Language Server, 17+) ----------
function Get-JavaMajorVersion($javaExe) {
    # "java version "21.0.8"" -> 21 (современная схема, 9+); "java version
    # "1.8.0_51"" -> 8 (старая схема ДО Java 9, первое число ВСЕГДА "1").
    #
    # #57 (найдено вживую, ТРЕТИЙ баг в этой же функции): `& $javaExe -version
    # 2>&1` СРАЗУ падал в catch и тихо возвращал 0 для ЛЮБОЙ версии — потому
    # что java -version пишет в stderr, PowerShell 5.1 заворачивает КАЖДУЮ
    # строку stderr от нативного exe в ErrorRecord при 2>&1, а глобальный
    # $ErrorActionPreference = "Stop" (см. верх файла) превращает это в
    # ЗАВЕРШАЮЩЕЕ исключение — try/catch с пустым catch{} проглатывал его
    # молча, никакой ошибки не было видно вообще. Обход — прогнать через
    # cmd /c: тогда слияние stdout+stderr происходит НА УРОВНЕ cmd.exe ДО
    # того, как PowerShell вообще видит вывод — обычные строки, не ErrorRecord.
    try {
        $lines = cmd /c "`"$javaExe`" -version 2>&1"
        $versionLine = $lines | Where-Object { $_ -match 'version "[\d.]+' } | Select-Object -First 1
        if ($versionLine -match 'version "(\d+)\.(\d+)') {
            $first = [int]$Matches[1]
            $second = [int]$Matches[2]
            if ($first -eq 1) { return $second }
            return $first
        }
    } catch {}
    return 0
}

function Test-Java {
    Write-Step "Java (нужна BSL Language Server, JDK 17+)"
    $candidates = @()
    foreach ($base in @("C:\Program Files\Java", "C:\Program Files\Eclipse Adoptium", "C:\Program Files\Zulu")) {
        if (Test-Path $base) {
            $candidates += Get-ChildItem -Path $base -Filter "java.exe" -Recurse -ErrorAction SilentlyContinue
        }
    }
    if ($candidates.Count -eq 0) {
        Write-Warn "Java НЕ найдена — lint_module/verify_* с lint-шагом не заработают."
        Write-Host "  Поставьте JDK 17+ (например Eclipse Adoptium/Temurin: adoptium.net)." -ForegroundColor Yellow
        return $false
    }
    # #57 (найдено вживую, ДВАЖДЫ — первая попытка "отсортировать имя папки"
    # тоже оказалась неверной): на машине автора реально стоят jdk-11,
    # jdk-11.0.0.1, jdk-19, jdk-21.0.8, jdk-26.0.1, javafx-sdk-22.0.1,
    # jre1.8.0_51 вперемешку. Сортировка ИМЕНИ ПАПКИ ненадёжна в принципе —
    # ни как обычная строка (без сортировки просто взяло jdk-11 первым), ни
    # как "похоже на версию" (jre1.8.0_51 > jdk-26.0.1 лексикографически,
    # т.к. 'r' > 'd' — сортировка по имени взяла БЕСПОЛЕЗНЫЙ JRE 8). Единственный
    # НАДЁЖНЫЙ способ — реально спросить каждый java.exe -version и сравнить
    # РЕАЛЬНЫЕ номера версий, не имена папок.
    $withVersions = $candidates | ForEach-Object {
        [PSCustomObject]@{ Path = $_.FullName; Major = Get-JavaMajorVersion $_.FullName }
    }
    $best = $withVersions | Sort-Object Major -Descending | Select-Object -First 1
    if ($best.Major -ge 17) {
        Write-Ok "найдена подходящая: $($best.Path) (Java $($best.Major))"
        return $true
    }
    Write-Warn "Лучшая найденная — Java $($best.Major) ($($best.Path)), это < 17 — BSL Language Server не запустится."
    Write-Host "  Поставьте JDK 17+ (например Eclipse Adoptium/Temurin: adoptium.net)." -ForegroundColor Yellow
    return $false
}

# ---------- 7. Модели: LM Studio, если есть, иначе голый llama-server ----------
function Find-LmStudioCli {
    $lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
    if (Test-Path $lms) { return $lms }
    return $null
}

function Install-ModelsViaLmStudio($lmsPath) {
    Write-Host "  LM Studio найдена ($lmsPath) — качаю модели через её CLI." -ForegroundColor Green
    # #58 (найдено вживую — короткая форма "owner/repo" НЕ работала): `lms get`
    # по умолчанию ищет по СОБСТВЕННОМУ каталогу "staff picks" LM Studio, а не
    # напрямую в Hugging Face — короткие идентификаторы вида
    # "qwen/qwen2.5-coder-7b-instruct"/"ggml-org/embeddinggemma-300M-GGUF"
    # ОБА падали с "Failed to resolve artifact... does not exist or you do not
    # have permission". Нужен ПОЛНЫЙ URL Hugging Face (это и в `lms get --help`
    # написано отдельной строкой, я изначально пропустил) — с ним оба резолвятся
    # и корректно распознают уже скачанное ("Model already downloaded").
    # Q4_K_M выбирается автоматически как модель-фиксер этого проекта весь сезон.
    & $lmsPath get "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF" -y --gguf
    & $lmsPath get "https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF" -y --gguf
    Write-Ok "модели загружены через LM Studio."
}

function Get-GpuBackend {
    # #57: НЕ протестировано вживую (на машине автора уже LM Studio+CUDA) —
    # логика детекта по документации Get-CimInstance Win32_VideoController,
    # см. докстринг файла про честную оговорку.
    $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
    if ($gpus | Where-Object { $_.Name -match "NVIDIA" }) { return "cuda-12.4" }
    if ($gpus | Where-Object { $_.Name -match "AMD|Radeon" }) { return "hip-radeon" }
    return "vulkan"   # безопасный fallback — работает почти на любой видеокарте с современными драйверами
}

function Install-StandaloneLlamaServer {
    Write-Warn "LM Studio не найдена — ставлю отдельный llama-server.exe (ЭТОТ ПУТЬ НЕ ПРОВЕРЕН ЖИВЬЮ, см. докстринг файла)."
    $backend = Get-GpuBackend
    Write-Host "  Определён backend по видеокарте: $backend"

    $releaseInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -UseBasicParsing
    $tag = $releaseInfo.tag_name
    $binAsset = $releaseInfo.assets | Where-Object { $_.name -like "llama-$tag-bin-win-$backend-x64.zip" } | Select-Object -First 1
    if (-not $binAsset) {
        Write-Err "Не нашёл сборку под backend='$backend' в релизе $tag — ставьте LM Studio руками (проверенный путь), см. HANDOFF."
        return $null
    }

    $llamaDir = Join-Path $ToolsDir "llama-server"
    New-Item -ItemType Directory -Path $llamaDir -Force | Out-Null
    $zipPath = Join-Path $env:TEMP "llama-server.zip"
    Write-Host "  Скачиваю $($binAsset.browser_download_url) ..."
    Invoke-WebRequest -Uri $binAsset.browser_download_url -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $llamaDir -Force
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

    # CUDA-сборка отдельно требует cudart-рантайм (см. докстринг файла) — без
    # него llama-server.exe не запустится (недостающие DLL).
    if ($backend -like "cuda*") {
        $cudartAsset = $releaseInfo.assets | Where-Object { $_.name -like "cudart-llama-bin-win-$backend-x64.zip" } | Select-Object -First 1
        if ($cudartAsset) {
            $cudartZip = Join-Path $env:TEMP "cudart.zip"
            Write-Host "  Скачиваю CUDA runtime: $($cudartAsset.browser_download_url) ..."
            Invoke-WebRequest -Uri $cudartAsset.browser_download_url -OutFile $cudartZip -UseBasicParsing
            Expand-Archive -Path $cudartZip -DestinationPath $llamaDir -Force
            Remove-Item $cudartZip -Force -ErrorAction SilentlyContinue
        }
    }

    $exe = Join-Path $llamaDir "llama-server.exe"
    if (Test-Path $exe) {
        Write-Ok "llama-server.exe установлен: $exe"
        return $exe
    }
    Write-Err "llama-server.exe не найден после распаковки — проверьте $llamaDir руками."
    return $null
}

function Install-ModelViaLlamaServerHf($llamaServerExe, $hfRepo, $port, $extraArgs) {
    # #59: llama-server -hf <repo> сам качает GGUF НАПРЯМУЮ с Hugging Face —
    # та же механика, что в официальной карточке модели ("llama-server -hf
    # ggml-org/embeddinggemma-300M-GGUF --embeddings"), кэширует в стандартный
    # кэш HF (~/.cache/huggingface), повторный запуск НЕ перекачивает. Держим
    # процесс, пока порт не откликнется (значит, модель уже загружена в
    # память, скачивание точно завершено) или пока не истечёт таймаут, потом
    # останавливаем — здесь ТОЛЬКО прогрев кэша на этапе развёртывания
    # (обсуждали в чате: качать при установке, не при каждом запуске сервера)
    # — сам ПОСТОЯННЫЙ запуск при каждом старте mcp_server.py делает отдельно
    # src/onec/bootstrap.py::ensure_models_running.
    Write-Host "  Качаю/кэширую $hfRepo через llama-server -hf (может занять время на первой закачке)..."
    $argList = "-hf `"$hfRepo`" -p $port $extraArgs"
    $proc = Start-Process -FilePath $llamaServerExe -ArgumentList $argList -PassThru -WindowStyle Hidden
    $ready = $false
    $deadline = (Get-Date).AddMinutes(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if ($proc.HasExited) { break }
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($ready) {
        Write-Ok "$hfRepo закэширован."
    } else {
        Write-Err "$hfRepo — llama-server не ответил в срок (см. процесс/лог вручную, порт $port)."
    }
}

function Install-ModelsViaLlamaServer($llamaServerExe) {
    Install-ModelViaLlamaServerHf $llamaServerExe "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF" 8090 ""
    Install-ModelViaLlamaServerHf $llamaServerExe "ggml-org/embeddinggemma-300M-GGUF" 8091 "--embeddings"
}

function Install-Models {
    Write-Step "ИИ-модели (Qwen2.5-Coder-7B фиксер + embeddinggemma-300M эмбеддинги) — напрямую с Hugging Face"
    $lms = Find-LmStudioCli
    if ($lms) {
        Install-ModelsViaLmStudio $lms
    } else {
        $llamaExe = Install-StandaloneLlamaServer
        if ($llamaExe) {
            Install-ModelsViaLlamaServer $llamaExe
        }
    }
}

# ---------- main ----------
Write-Host "1cAgent — установка зависимостей" -ForegroundColor Magenta
Write-Host "Корень проекта: $RootDir"

$platformOk = Test-1CPlatform
Test-ReferenceConfig | Out-Null
Test-Java | Out-Null

if (-not $SkipTesseract) { Install-Tesseract }
if (-not $SkipBslLs) { Install-BslLanguageServer }
if (-not $SkipYAxUnit) { Install-YAxUnit }

# #58: ИИ-модели — несколько ГБ, спрашиваем явно (кроме -SkipModels/-Yes,
# см. параметры выше). Пустой ввод (просто Enter) = да, по умолчанию ставим —
# так удобнее для обычного запуска руками, отказ — только явным "n".
$installModels = $false
if ($SkipModels) {
    Write-Host ""
    Write-Host "ИИ-модели пропущены (-SkipModels)." -ForegroundColor Yellow
} elseif ($Yes) {
    $installModels = $true
} else {
    Write-Host ""
    $answer = Read-Host "Установить ИИ-модели? Qwen2.5-Coder-7B (фиксер, ~4.5-5ГБ) + embeddinggemma-300M (эмбеддинги, ~0.3ГБ) [Y/n]"
    $installModels = ($answer -eq "") -or ($answer -match "^[YyДд]")
}
if ($installModels) { Install-Models }

Write-Step "Итог"
if (-not $platformOk) {
    Write-Err "Платформа 1С НЕ найдена — сервер не заработает, пока не поставите её вручную."
} else {
    Write-Ok "Платформа 1С на месте — можно запускать mcp_server.py."
}
Write-Host ""
Write-Host "Дальше: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Cyan
Write-Host "Затем: claude_desktop_config.example.json -> ваш реальный конфиг Claude Desktop." -ForegroundColor Cyan
