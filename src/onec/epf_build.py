#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#65: сборка/разборка внешних обработок С ФОРМАМИ через конфигуратор в пакетном
режиме. До этого агент умел собирать только БЕЗФОРМЕННУЮ AgentCode.epf (см.
glue.Real1CRunner._build), а любую правку формы-раннера приходилось делать
руками в конфигураторе.

КОРЕНЬ ПРОБЛЕМЫ (найден живьём, стоил четырёх неудачных попыток и модальных
окон на экране пользователя): у выгрузки внешней обработки ДВА формата.
  * Иерархический (по умолчанию у DumpExternalDataProcessorOrReportToFiles):
        Имя.xml + Имя/Forms/Форма.xml + Имя/Forms/Форма/Ext/Form/Module.bsl
  * Плоский (-Format Plain):
        Имя.xml + Имя.Form.Форма.xml + Имя.Form.Форма.Form.xml
                + Имя.Form.Форма.Form.Module.txt
LoadExternalDataProcessorOrReportFromFiles принимает ТОЛЬКО ПУТЬ К ФАЙЛУ (на
каталог отвечает "является путем к директории, в то время как ожидается путь к
файлу") и трактует его как ПЛОСКУЮ выгрузку — то есть иерархический дамп ей
скормить нельзя в принципе, а ключ -Format на загрузке не помогает. Отсюда
"Файл объекта не существует - ...Имя.Form.Форма.xml" при попытке собрать из
иерархического исходника.

Поэтому весь цикл здесь идёт ЧЕРЕЗ ПЛОСКИЙ ФОРМАТ: dump -Format Plain -> правка
файлов -> load. Проверено вживую: round-trip .epf -> plain -> .epf даёт rc=0 за
~3с.

ВТОРАЯ ГРАБЛЯ, дороже первой (поймана живьём на СравнениеИИзменениеЦен.epf из
УТ 11.5): раньше конфигуратор ЗДЕСЬ ВСЕГДА запускался с /F compiler_db — пустой
служебной базой. Для обработки, принадлежащей реальной конфигурации, это тихо
уничтожает ССЫЛОЧНЫЕ ТИПЫ РЕКВИЗИТОВ ФОРМЫ: конфигуратор не может разрешить
СправочникСсылка.Номенклатура в базе, где такого справочника нет, и пишет в XML
xs:string. Сборка закрепляет подмену. Внешне .epf открывается, но поля выбора
перестают быть полями выбора, а код падает на ПолеСсылки.Код с "Значение не
является значением объектного типа". Round-trip БЕЗ ЕДИНОЙ ПРАВКИ уже ломает
обработку, и по дампам это не видно — они одинаково испорчены с обеих сторон.

Поэтому ib_connection теперь идёт параметром через весь модуль: разбирать и
собирать .epf нужно В ТОЙ БАЗЕ, КОТОРОЙ ОНА ПРИНАДЛЕЖИТ. compiler_db годится
только для обработок без ссылочных реквизитов (как раннер агента). Страховка —
epf_typecheck.scan_plain_dump: ищет следы схлопнутых типов и не даёт записать
испорченный .epf молча.
"""
import shutil
from pathlib import Path

from src.core.ib_connection import cli_connection_str
from src.onec.designer_run import run_watched
from src.onec.epf_typecheck import scan_plain_dump


def _ib_args(cfg: dict, ib_connection: str) -> tuple:
    """
    -> (фрагмент командной строки, строка для поиска процессов). Пустой
    ib_connection = служебная база-компилятор (прежнее поведение).
    """
    if ib_connection:
        return cli_connection_str(ib_connection), ib_connection
    return f'/F "{cfg["compiler_db"]}"', f'File="{cfg["compiler_db"]}"'


def _designer(cfg: dict, args: str, log_path: Path, timeout: int,
              ib_connection: str = "") -> dict:
    """
    Один запуск конфигуратора в пакетном режиме. Возвращает
    {"ok", "returncode", "log", "timeout"}. Модальное окно конфигуратора
    процесс не завершает — поэтому timeout ОБЯЗАТЕЛЕН и по нему процесс
    убивается, иначе висим до бесконечности (ловилось живьём).
    """
    exe = cfg.get("path_1c_build") or cfg["path_1c"]
    ib_frag, ib_match = _ib_args(cfg, ib_connection)
    cmd = f'"{exe}" DESIGNER {ib_frag} {args} /Out "{log_path}"'
    # #66: НЕ subprocess.run(timeout=) — на Windows он таймаутит только cmd.exe,
    # а сам 1cv8.exe остаётся висеть осиротевшим (см. HANDOFF_ARCHIVE #45).
    # run_watched поллит процесс, параллельно ловит модальное окно по скриншоту
    # и убивает ДЕРЕВО процессов.
    watched = run_watched(cmd, timeout, cfg, ib_match)
    rc = watched.get("returncode")
    timed_out = bool(watched.get("timed_out"))
    dialog_hint = watched.get("hint") or ""
    log = ""
    if log_path.exists():
        try:
            log = log_path.read_text(encoding="utf-8-sig")
        except Exception:
            log = ""
    res = {"ok": rc == 0 and not timed_out and not watched.get("dialog"),
           "returncode": rc, "timeout": timed_out, "log": log.strip()}
    if watched.get("dialog"):
        res["dialog"] = True
        res["reason"] = "конфигуратор встал на модальном окне: " + dialog_hint
    elif timed_out:
        res["reason"] = f"конфигуратор не уложился в {timeout}с, процесс убит"
    return res


def dump_epf(cfg: dict, epf_path: str, out_dir: str, timeout: int = 120,
             ib_connection: str = "") -> dict:
    """
    .epf -> ПЛОСКАЯ выгрузка в out_dir (каталог пересоздаётся). Возвращает
    {"ok", "root_xml", "files": [...], "log"}. root_xml — тот самый файл,
    который потом принимает build_epf.
    """
    out = Path(out_dir)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out.parent / (out.name + ".dump.log")
    res = _designer(cfg, f'/DumpExternalDataProcessorOrReportToFiles "{out}" "{epf_path}" -Format Plain',
                    log_path, timeout, ib_connection=ib_connection)
    files = sorted(p.name for p in out.iterdir()) if out.exists() else []
    root = Path(epf_path).stem + ".xml"
    res.update({"root_xml": str(out / root) if (out / root).exists() else "",
                "files": files, "out_dir": str(out)})
    if res["ok"] and not res["root_xml"]:
        res["ok"] = False
        res["reason"] = f"выгрузка прошла, но корневого {root} в {out} нет"
    if res["ok"]:
        res["types"] = scan_plain_dump(str(out))
    return res


def build_epf(cfg: dict, root_xml: str, target_epf: str, timeout: int = 120,
              ib_connection: str = "") -> dict:
    """
    ПЛОСКАЯ выгрузка (путь к корневому Имя.xml) -> .epf. Каталог передавать
    НЕЛЬЗЯ, только файл — см. модульный докстринг.
    """
    root = Path(root_xml)
    if root.is_dir():
        return {"ok": False, "reason": "нужен путь к корневому XML-ФАЙЛУ выгрузки, а не к каталогу "
                                       "(конфигуратор каталог не принимает)"}
    if not root.exists():
        return {"ok": False, "reason": f"нет файла выгрузки: {root}"}
    target = Path(target_epf)
    target.parent.mkdir(parents=True, exist_ok=True)
    log_path = target.with_suffix(".build.log")
    res = _designer(cfg, f'/LoadExternalDataProcessorOrReportFromFiles "{root}" "{target}"',
                    log_path, timeout, ib_connection=ib_connection)
    res["target"] = str(target)
    res["size"] = target.stat().st_size if target.exists() else 0
    if res["ok"] and not res["size"]:
        res["ok"] = False
        res["reason"] = "конфигуратор вернул 0, но .epf не появился"
    return res


def _module_file(out_dir: Path, epf_stem: str, form_name: str) -> Path:
    """В плоском формате модуль формы лежит в Имя.Form.<Форма>.Form.Module.txt."""
    return out_dir / f"{epf_stem}.Form.{form_name}.Form.Module.txt"


def read_form_module(cfg: dict, epf_path: str, form_name: str = "Форма",
                     work_subdir: str = "epf_edit", ib_connection: str = "") -> dict:
    """Текст модуля формы прямо из .epf (через временную плоскую выгрузку)."""
    epf = Path(epf_path)
    out = Path(cfg["runtime_dir"]) / work_subdir
    dumped = dump_epf(cfg, str(epf), str(out), ib_connection=ib_connection)
    if not dumped["ok"]:
        return {"ok": False, "step": "dump", **dumped}
    mod = _module_file(out, epf.stem, form_name)
    if not mod.exists():
        return {"ok": False, "reason": f"в выгрузке нет {mod.name}", "files": dumped["files"]}
    return {"ok": True, "module": mod.read_text(encoding="utf-8-sig"), "path": str(mod),
            "types": dumped.get("types", {})}


def patch_form_module(cfg: dict, epf_path: str, replacements: list, form_name: str = "Форма",
                      ib_connection: str = "", allow_type_loss: bool = False) -> dict:
    """
    #86 (пункт A2 плана): точечная правка модуля формы ОДНИМ вызовом вместо
    цепочки прочитать -> изменить -> линт -> записать -> проверить (пять ходов,
    а ход стоит ~26 тыс. единиц независимо от содержания).

    replacements — список {"old": "...", "new": "..."}. Каждый old должен
    встречаться в модуле РОВНО ОДИН раз: иначе правка неоднозначна, и мы
    отказываемся целиком, ничего не записав. Пустой "new" = удаление фрагмента.

    Возвращает {"ok", "applied": N, "lines_before/after", "target"} либо отказ с
    указанием, какая именно замена не сошлась. Линт-гейт из write_form_module
    работает и здесь — модуль с ParseError в .epf не попадёт.
    """
    if not replacements:
        return {"ok": False, "reason": "нечего применять: replacements пуст"}

    current = read_form_module(cfg, epf_path, form_name=form_name, ib_connection=ib_connection)
    if not current.get("ok"):
        return {"ok": False, "step": "read", **current}
    text = current["module"]
    before_lines = len(text.splitlines())

    for i, rep in enumerate(replacements, 1):
        old = (rep or {}).get("old", "")
        new = (rep or {}).get("new", "")
        if not old:
            return {"ok": False, "step": "match", "reason": f"замена №{i}: пустой old"}
        found = text.count(old)
        if found != 1:
            return {"ok": False, "step": "match",
                    "reason": (f"замена №{i}: фрагмент встречается {found} раз(а), "
                               f"нужен ровно один — уточните old"),
                    "fragment": old[:160]}
        text = text.replace(old, new, 1)

    res = write_form_module(cfg, epf_path, text, form_name=form_name,
                            ib_connection=ib_connection, allow_type_loss=allow_type_loss)
    if not res.get("ok"):
        return res
    res.update({"applied": len(replacements), "lines_before": before_lines,
                "lines_after": len(text.splitlines())})
    return res


def write_form_module(cfg: dict, epf_path: str, module_text: str, form_name: str = "Форма",
                      work_subdir: str = "epf_edit", backup: bool = True,
                      skip_lint: bool = False, ib_connection: str = "",
                      allow_type_loss: bool = False) -> dict:
    """
    Заменить модуль формы ВНУТРИ .epf: dump -> подменить Module.txt -> load.
    Сам .epf и есть источник правды (иерархический исходник в репозитории для
    сборки не годится, см. модульный докстринг), поэтому правим его на месте.
    backup=True кладёт рядом <имя>.epf.bak до перезаписи.
    """
    epf = Path(epf_path)
    if not epf.exists():
        return {"ok": False, "reason": f"нет файла обработки: {epf}"}

    # #68: ГЕЙТ. Записать в .epf модуль, который физически не компилируется —
    # значит отдать пользователю сломанный раннер, и узнает он об этом только
    # при открытии обработки в 1С. Ровно так и случилось: незакрытый строковый
    # литерал уехал в .epf, потому что проверка линтером читала НЕСУЩЕСТВУЮЩИЙ
    # ключ "issues" вместо "diagnostics" и всегда возвращала "проблем нет".
    # Здесь смотрим именно ParseError — стиль не важен.
    if not skip_lint:
        try:
            from src.onec.bsl_ls import lint as _lint
            diags = (_lint(module_text, cfg["bsl_ls_jar"],
                           java_exe=cfg.get("java_exe", "java")).get("diagnostics") or [])
            parse_errors = [d for d in diags if d.get("code") == "ParseError"]
            if parse_errors:
                return {"ok": False, "step": "lint", "compiles": False,
                        "reason": "модуль не компилируется — в .epf не пишу",
                        "parse_errors": parse_errors[:8]}
        except Exception:
            pass   # линтер недоступен — не повод блокировать запись

    out = Path(cfg["runtime_dir"]) / work_subdir
    dumped = dump_epf(cfg, str(epf), str(out), ib_connection=ib_connection)
    if not dumped["ok"]:
        return {"ok": False, "step": "dump", **dumped}

    # ГЛАВНЫЙ ГЕЙТ (см. модульный докстринг и epf_typecheck): если конфигуратор
    # разбирал .epf в базе, где её типов нет, ссылочные реквизиты формы УЖЕ
    # схлопнулись в строку. Собрать обратно — значит отдать пользователю
    # сломанную обработку, причём молча.
    types = dumped.get("types") or {}
    if types.get("degraded") and not allow_type_loss:
        return {"ok": False, "step": "types", "reason": types.get("reason", ""),
                "suspects": types.get("suspects", []),
                "suspects_total": types.get("suspects_total", 0),
                "hint": "передайте ib_connection базы этой обработки; "
                        "allow_type_loss=True только если потеря типов заведомо безразлична"}

    mod = _module_file(out, epf.stem, form_name)
    if not mod.exists():
        return {"ok": False, "step": "dump", "reason": f"в выгрузке нет {mod.name}",
                "files": dumped["files"]}
    mod.write_text(module_text, encoding="utf-8-sig")

    # Собираем во ВРЕМЕННЫЙ файл и подменяем только при успехе — чтобы неудачная
    # сборка не оставила пользователя без рабочего раннера.
    tmp = out.parent / (epf.stem + ".rebuilt.epf")
    if tmp.exists():
        tmp.unlink()
    built = build_epf(cfg, dumped["root_xml"], str(tmp), ib_connection=ib_connection)
    if not built["ok"]:
        return {"ok": False, "step": "build", **built}

    if backup:
        shutil.copy2(epf, epf.with_suffix(epf.suffix + ".bak"))
    shutil.copy2(tmp, epf)
    return {"ok": True, "target": str(epf), "size": epf.stat().st_size,
            "backup": str(epf.with_suffix(epf.suffix + ".bak")) if backup else "",
            "lines": len(module_text.splitlines())}
