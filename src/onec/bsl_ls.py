#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#6 (часть 1): статический гейт BSL Language Server (1c-syntax/bsl-language-server).
Линтует .bsl-текст БЕЗ платформы 1С и без живого раннера — быстрый предфильтр
перед run_module/heal_module (которые стоят ~10-20с холодного DESIGNER).

CLI подтверждён по официальным докам (v1.0.2):
    java -jar bsl-language-server.jar --analyze --srcDir <src> --reporter json --outputDir <out>
Отчёт: <out>/bsl-json.json, схема AnalysisInfo:
    {date, sourceDir, fileinfos: [{path, mdoRef, diagnostics: [
        {range:{start:{line,character},end:{...}}, severity, code, source, message, tags}
    ], metrics}]}

Требует Java + сам jar НА МАШИНЕ, где крутится mcp_server.py (путь — CFG["bsl_ls_jar"]).
Скачать: https://github.com/1c-syntax/bsl-language-server/releases/latest
         (файл *-exec.jar — самодостаточный, со всеми зависимостями).
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


# #29: файл переехал в src/onec/ — tools/ лежит в корне проекта, на 2 уровня выше.
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "tools" / "bsl-language-server.json"


def lint(code: str, jar_path: str, timeout: int = 30, java_exe: str = "java") -> dict:
    """
    Прогоняет один .bsl-модуль через BSL LS analyze.
    Возвращает {"ok": bool|None, "diagnostics": [...], "error": str|None}.
      ok=True  — нет диагностик уровня Error.
      ok=False — есть хотя бы одна диагностика уровня Error.
      ok=None  — сам линтер не смог отработать (нет java/jar, таймаут и т.п.);
                 это НЕ значит, что код плохой — просто гейт недоступен.

    ВАЖНО (пойман вживую): "ok": false НЕ значит "код не скомпилируется в 1С" —
    BSL LS по умолчанию считает Error-severity рядом диагностик, которые реально
    исполняются нормально (например, MissingCodeTryCatchEx — пустой блок
    Исключение...КонецПопытки, в этом проекте намеренный паттерн-заглушка).
    tools/bsl-language-server.json понижает такие диагностики до Information —
    не удаляет их из вывода, просто не роняет "ok". При разборе diagnostics
    смотри на конкретный "code" и "severity", а не только на итоговый ok.

    java_exe — путь к java (по умолчанию берёт из PATH). BSL LS v1.0.2 собран под
    Java 17+ (class file version 61) — если системный `java` старее (например,
    JDK 11 из class file version 55), укажите путь к более новому JDK явно через
    CFG["java_exe"], не трогая системный PATH (на машине бывает несколько JDK
    сразу под разные задачи).
    """
    if not jar_path or not Path(jar_path).exists():
        return {"ok": None, "diagnostics": [],
                "error": f"jar не найден: {jar_path!r} (скачайте bsl-language-server*-exec.jar)"}

    tmp = Path(tempfile.mkdtemp(prefix="bslls_"))
    try:
        src_dir = tmp / "src"
        out_dir = tmp / "out"
        src_dir.mkdir()
        out_dir.mkdir()
        (src_dir / "Module.bsl").write_text(code, encoding="utf-8-sig")

        cmd = [java_exe, "-jar", jar_path, "--analyze",
               "--srcDir", str(src_dir), "--reporter", "json",
               "--outputDir", str(out_dir)]
        if _CONFIG_PATH.exists():
            cmd += ["-c", str(_CONFIG_PATH)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return {"ok": None, "diagnostics": [], "error": f"java не найден: {java_exe!r}"}
        except subprocess.TimeoutExpired:
            return {"ok": None, "diagnostics": [], "error": f"таймаут {timeout}с"}

        report = out_dir / "bsl-json.json"
        if not report.exists():
            tail = ((proc.stderr or "") + (proc.stdout or ""))[-500:]
            return {"ok": None, "diagnostics": [],
                    "error": f"нет отчёта (код возврата {proc.returncode}): {tail}"}

        data = json.loads(report.read_text(encoding="utf-8"))
        diags = []
        for fi in data.get("fileinfos", []):
            for d in fi.get("diagnostics", []):
                diags.append({
                    "severity": d.get("severity"),
                    "code": d.get("code"),
                    "message": d.get("message"),
                    "line": (d.get("range") or {}).get("start", {}).get("line"),
                })
        has_error = any(d["severity"] == "Error" for d in diags)
        return {"ok": not has_error, "diagnostics": diags, "error": None}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- самопроверка (нужен java + CFG["bsl_ls_jar"]) ----
if __name__ == "__main__":
    from src.core.config import CFG
    sample = (
        "Функция ПолучитьСумму(Товары)\n"
        "    Сумма = 0;\n"
        "    Для Каждого Стр Из Товары Цикл\n"
        "        Сумма = Сумма + Стр.Цена;\n"
        "    КонецЦикла;\n"
        "КонецФункции\n"
    )
    print(json.dumps(lint(sample, CFG.get("bsl_ls_jar", ""), java_exe=CFG.get("java_exe", "java")),
                      ensure_ascii=False, indent=2))
