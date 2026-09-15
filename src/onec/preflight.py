#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#85 (пункт A3 плана оптимизации): одна сводка вместо шести вызовов.

Разведка в начале сессии раньше растягивалась на check_setup + list_sessions +
http_transport_status + пробный run_module + чтение runner.txt — пять-шесть
ходов, а ход стоит ~26 тыс. единиц независимо от содержания. Здесь всё то же
самое собирается ЛОКАЛЬНО (без запуска 1С), поэтому дёшево и быстро.

probe=True дополнительно гоняет тривиальное задание через живой раннер — это
единственная часть, которая реально трогает 1С.
"""
import time
from pathlib import Path


def _runner_file_state(cfg: dict) -> dict:
    """Что известно о раннере из файлов обмена (работает и когда он на HTTP)."""
    res = {"protocol": 1, "runner_txt_age_sec": None, "last_status": ""}
    p = Path(cfg.get("runner_txt", ""))
    if p.exists():
        try:
            txt = p.read_text(encoding="utf-8-sig")
            if "protocol=2" in txt:
                res["protocol"] = 2
            res["runner_txt_age_sec"] = round(time.time() - p.stat().st_mtime, 1)
        except Exception:
            pass
    err = Path(cfg.get("error_txt", ""))
    if err.exists():
        try:
            res["last_status"] = err.read_text(encoding="utf-8-sig").strip()[:80]
        except Exception:
            pass
    return res


def preflight(cfg: dict, probe: bool = False) -> dict:
    """
    Компактная сводка готовности: платформы, база-компилятор, транспорт, раннер.
    Ничего не меняет. Возвращает ещё и "verdict" — одну строку, по которой сразу
    понятно, можно ли работать.
    """
    out = {}

    # --- платформы и сборка ---
    build = Path(cfg.get("path_1c_build") or cfg.get("path_1c", ""))
    run = Path(cfg.get("path_1c_run") or cfg.get("path_1c", ""))
    thin = Path(cfg.get("path_1c_run_thin", ""))
    out["platform"] = {
        "build": cfg.get("build_platform") or "?", "build_exists": build.exists(),
        "run": cfg.get("run_platform") or "?", "run_exists": run.exists(),
        "thin_client": thin.exists(),
    }

    db = Path(cfg.get("compiler_db", ""))
    marker = db / ".built_by"
    out["compiler_db"] = {
        "exists": db.exists() and any(db.iterdir()) if db.exists() else False,
        "built_by": marker.read_text(encoding="utf-8").strip() if marker.exists() else "",
    }

    # --- транспорт ---
    try:
        from src.onec import http_transport as ht
        st = ht.status(cfg)
    except Exception as e:
        st = {"running": False, "reason": repr(e)}
    out["http"] = {k: st.get(k) for k in
                   ("running", "mode", "url", "runner_alive", "last_seen_ago",
                    "last_wait", "last_client", "tasks_served") if k in st}

    out["runner_files"] = _runner_file_state(cfg)

    # --- транспорт, которым раннер реально подключён ---
    if st.get("runner_alive"):
        transport = "http"
        wait = st.get("last_wait")
        out["runner_mode"] = ("быстрый опрос (сеанс подвисает)" if wait
                              else "отзывчивый (сеанс свободен)")
    elif (out["runner_files"].get("runner_txt_age_sec") or 1e9) < 120:
        transport = "папка обмена"
    else:
        transport = "нет связи"
    out["transport"] = transport

    # --- вердикт одной строкой ---
    if not out["platform"]["build_exists"]:
        out["verdict"] = "НЕ ГОТОВО: не найдена платформа для сборки"
    elif transport == "нет связи":
        out["verdict"] = ("НЕ ГОТОВО: раннер не на связи — откройте обработку в 1С "
                          "(или запустите Раннер_unf_main.bat)")
    else:
        out["verdict"] = f"готово, раннер на связи через {transport}"

    if probe and transport != "нет связи":
        from src.onec.glue import Real1CRunner
        t = time.time()
        status, _errors, log = Real1CRunner(cfg)(
            "Процедура ВыполнитьЗадачу(ЛогВыполнения) Экспорт\n"
            '\tСообщить("preflight: " + Метаданные.Имя);\n'
            '\tСообщить("ГОТОВО");\n'
            "КонецПроцедуры\n")
        out["probe"] = {"status": status, "seconds": round(time.time() - t, 2),
                        "log": (log or "").strip()[:200]}
        if status != "ok":
            out["verdict"] = f"СВЯЗЬ ЕСТЬ, НО ПРОГОН НЕ ПРОШЁЛ: {status}"

    return out
