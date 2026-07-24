#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скриншот ВИДИМОГО окна 1cv8.exe (DESIGNER/ENTERPRISE) — закрывает "слепую
зону" невидимых модальных диалогов (ошибка формата документа, диалог логина,
конфликт имён общего модуля и т.п. — см. HANDOFF.md #25 п.2, #32 п.2,
ретроотчёт по билету №15), которые НЕ попадают ни в /Out-лог DESIGNER, ни в
Журнал регистрации (check_event_log). ТОЛЬКО ЧТЕНИЕ — никакого автоотправления
клавиш/кликов в найденное окно (закрытие зависшей сессии — уже существующий
kill_sessions, см. sessions.py).

OCR (#39): Windows.Media.Ocr через winsdk НЕ подключён (winsdk не собирается
под Python 3.14 в этом окружении — нет готового wheel, сборка из исходников
требует Visual Studio). Вместо него подключён Tesseract (pytesseract) — он
уже установлен на машине (v5.0.1, `rus`+`eng` в tessdata), путь ищется через
CFG["tesseract_exe"] (см. config.py/bootstrap.find_tesseract). ocr_text() —
ДОПОЛНИТЕЛЬНЫЙ дешёвый путь ПОВЕРХ capture_window(): картинка ВСЕГДА
прилагается к результату screenshot_1c_window (см. session_tools.py) — если
OCR вернул пусто/мусор (нераспознанные диалоги, нестандартная вёрстка), Claude
читает картинку сам, как и раньше.
"""
import ctypes
from io import BytesIO
from pathlib import Path

import win32gui
import win32process
import win32ui
from PIL import Image as PILImage

_PW_RENDERFULLCONTENT = 2  # печатает и DirectComposition/аппаратно ускоренное содержимое


def _enum_1c_windows(pids: set) -> list:
    """pids — ОБЯЗАТЕЛЬНО непустой набор PID реальных процессов 1cv8.exe (см.
    sessions.list_1c_processes/find_matching_processes) — НЕ угадываем по
    заголовку/классу окна: заголовок вида "1cAgent — HANDOFF.md" у обычного
    редактора кода даёт ложное совпадение по подстроке "1c" (поймано вживую
    смоук-тестом при разработке этого модуля)."""
    found = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid not in pids:
            return
        found.append({"hwnd": hwnd, "pid": pid, "title": title})

    win32gui.EnumWindows(_cb, None)
    return found


def find_1c_window(pids: set):
    """
    Ищет ПЕРВОЕ видимое top-level окно среди процессов pids (набор PID
    РЕАЛЬНЫХ процессов 1cv8.exe — получайте через
    sessions.find_matching_processes(ib_connection) или
    sessions.list_1c_processes(), НЕ угадывайте PID иначе). None, если ничего
    не видно (окно ещё не отрисовалось, процесс headless без GUI, или уже
    закрылся) или pids пуст.
    """
    if not pids:
        return None
    wins = _enum_1c_windows(pids)
    return wins[0] if wins else None


def capture_window(hwnd: int):
    """PrintWindow -> PNG bytes. None при любой неудаче захвата (не бросает)."""
    hwnd_dc = mfc_dc = save_dc = bitmap = None
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return None

        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), _PW_RENDERFULLCONTENT)
        if not ok:
            return None

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        img = PILImage.frombuffer(
            "RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1
        )
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None
    finally:
        if bitmap is not None:
            win32gui.DeleteObject(bitmap.GetHandle())
        if save_dc is not None:
            save_dc.DeleteDC()
        if mfc_dc is not None:
            mfc_dc.DeleteDC()
        if hwnd_dc is not None:
            win32gui.ReleaseDC(hwnd, hwnd_dc)


_OCR_UPSCALE_MAX_DIM = 700


def _preprocess_for_ocr(img: PILImage.Image):
    """
    #51 (задача 8): найдено ЭКСПЕРИМЕНТАЛЬНО на сохранённом плохом скриншоте
    (1c_screenshot.png — реальный диалог блокировки ИБ при конфигурировании,
    436x199). Сравнивались: нативный размер vs upscale x2/x3 (LANCZOS),
    цвет vs grayscale, с бинаризацией порогом и без, psm 3/4/6/11/12 (см.
    ocr_experiment_results.txt из живого прогона — в репозитории не хранится,
    это черновой лог сессии, не артефакт продукта).

    Итог: нативное разрешение + psm по умолчанию (авто=3) читает ОСНОВНОЙ текст
    сносно, но ТЕРЯЕТ заголовок окна и путает мелкий текст кнопок/счётчика
    ("50 сек." -> "50 cox),"). Лучший результат для МАЛЕНЬКИХ окон (модальные
    диалоги 1С обычно <500x250) — grayscale + upscale x3 + psm=6 (единый блок
    текста): восстанавливает заголовок И кнопки без потерь в теле. Бинаризация
    порогом добавляла шум (ложные строки) — НЕ взята.

    Для БОЛЬШИХ окон (целиком Конфигуратор/Предприятие) апскейл x3 дорог по
    памяти и не проверен экспериментально (нет сохранённого плохого примера) —
    возвращает картинку и config БЕЗ ИЗМЕНЕНИЙ (psm=авто, как раньше), меняется
    поведение ТОЛЬКО для маленьких окон (min(width,height) < _OCR_UPSCALE_MAX_DIM).
    """
    w, h = img.size
    if min(w, h) < _OCR_UPSCALE_MAX_DIM:
        return img.convert("L").resize((w * 3, h * 3), PILImage.LANCZOS), "--psm 6"
    return img, ""


def ocr_text(cfg: dict, png_bytes: bytes, lang: str = "rus+eng"):
    """
    Распознаёт текст на PNG через Tesseract (#39, тюнинг параметров — #51).
    Возвращает str (обрезанную/очищенную) или None, если OCR недоступен/
    распознавание не удалось/текста не нашлось — вызывающий код
    (screenshot_1c_window) в любом из этих случаев просто НЕ добавляет
    "ocr_text" в результат, картинка остаётся основным способом прочитать
    диалог (уже так устроено, ничего не меняется в контракте). Никогда не
    бросает исключение наружу.
    """
    tess_path = cfg.get("tesseract_exe", "")
    if not tess_path or not Path(tess_path).exists():
        return None
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tess_path
        img = PILImage.open(BytesIO(png_bytes))
        img, config = _preprocess_for_ocr(img)
        text = pytesseract.image_to_string(img, lang=lang, config=config)
    except Exception:
        return None
    text = text.strip()
    return text or None
