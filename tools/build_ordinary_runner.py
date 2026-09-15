#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка раннера для ОБЫЧНОГО ПРИЛОЖЕНИЯ с обычной формой.

Обычную форму нельзя описать текстом, поэтому её разметка берётся из ЭТАЛОННОЙ
плоской выгрузки (каталог --plain), сделанной один раз из .epf, собранного
человеком в конфигураторе. Скрипт подставляет туда свежий модуль объекта и
модуль формы и собирает .epf.

ВАЖНО про версию платформы: собирать надо ТОЙ ЖЕ платформой (или старше),
что и целевая база. Эталонная выгрузка тоже привязана к версии: XML формата
2.21 (8.5.1) конфигуратор 8.3.26 не читает — "Неизвестная версия формата".
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.onec.ordinary_form import write_module  # noqa: E402

# Модуль ОБЫЧНОЙ ФОРМЫ держим минимальным: вся логика живёт в модуле объекта,
# который правится как обычный текст. Форма только крутит таймер и переключает.
# ГРАБЛЯ ОБЫЧНЫХ ФОРМ: событие формы срабатывает ТОЛЬКО если оно назначено в
# палитре свойств — сама по себе процедура с именем ПриОткрытии обработчиком не
# становится (в отличие от управляемых форм, где связь пишется в Form.xml).
# Привязку конфигуратор делает при создании заготовки, поэтому единственный
# гарантированно привязанный обработчик здесь — нажатие кнопки "Выполнить".
# На неё и вешаем всё: первый клик включает таймер и опрос, второй выключает.
FORM_MODULE = """
Процедура Старт()
	Если УстановитьАдрес(ПутьОбмена) Тогда
		РаннерСтарт();
		ПодключитьОбработчикОжидания("Тик", 1);
	КонецЕсли;
КонецПроцедуры

Процедура КнопкаВыполнитьНажатие(Кнопка)
	Если РаннерРаботает() Тогда
		ОтключитьОбработчикОжидания("Тик");
		РаннерСтоп();
	Иначе
		Старт();
	КонецЕсли;
КонецПроцедуры

Процедура Тик()
	РаннерТик();
КонецПроцедуры

Процедура ПриОткрытии()
	Если ПустаяСтрока(ПутьОбмена) Тогда
		ПутьОбмена = АдресПоУмолчанию();
	КонецЕсли;
	Если Не ПустаяСтрока(ПутьОбмена) Тогда
		Старт();
	КонецЕсли;
КонецПроцедуры
"""


def build(plain: Path, work: Path, obj_bsl: Path, epf_out: Path, exe: Path, ib: str) -> int:
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(plain, work)
    for junk in work.glob("*.log"):
        junk.unlink()

    # ГРАБЛЯ: .bsl уже начинается с BOM. Если дописать utf-8-sig, получится ДВА
    # BOM подряд, и 1С отвечает "Обнаружено логическое завершение исходного
    # текста модуля (1,1)" — модуль не компилируется целиком.
    text = obj_bsl.read_text(encoding="utf-8-sig")
    payload = "\ufeff" + text.replace("\r\n", "\n").replace("\n", "\r\n")
    module_txt = next(work.glob("*.ObjectModule.txt"))
    module_txt.write_bytes(payload.encode("utf-8"))

    form_file = next(work.glob("*.Form.*.Form"))
    write_module(str(form_file), FORM_MODULE, allow_grow=True)

    root_xml = next(p for p in work.glob("*.xml") if ".Form." not in p.name)
    epf_out.unlink(missing_ok=True)
    log = work / "build.log"
    cmd = [str(exe), "DESIGNER", f"/F{ib}", "/LoadExternalDataProcessorOrReportFromFiles",
           str(root_xml), str(epf_out), "/Out", str(log)]
    rc = subprocess.run(cmd).returncode
    if log.exists():
        print(log.read_text(encoding="utf-8-sig", errors="ignore").strip()[:600])
    print(f"rc={rc} epf={'есть' if epf_out.exists() else 'НЕТ'}")
    return 0 if epf_out.exists() else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plain", default=str(ROOT / "ВнешняяОбработкаОбычная" / "plain"),
                    help="эталонная плоская выгрузка (с формой)")
    ap.add_argument("--work", default=str(ROOT / "runtime" / "ordinary_build"),
                    help="временный каталог сборки")
    ap.add_argument("--obj", default=str(ROOT / "ВнешняяОбработкаОбычная" / "РаннерОбычный" / "Ext" / "ObjectModule.bsl"))
    ap.add_argument("--out", default=str(ROOT / "ВнешняяОбработкаОбычная" / "РаннерОбычный.epf"))
    ap.add_argument("--exe", default=r"D:\1сБазы\платформы\8.5.1.1343\bin\1cv8.exe")
    ap.add_argument("--ib", default=r"D:\1сБазы\работа\сертификация\stend85")
    a = ap.parse_args()
    return build(Path(a.plain), Path(a.work), Path(a.obj), Path(a.out), Path(a.exe), a.ib)


if __name__ == "__main__":
    raise SystemExit(main())
