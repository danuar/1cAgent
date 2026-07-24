import time
from PIL import Image
import pyautogui
import pygetwindow as gw
import pytesseract

# Укажите ваш путь к Tesseract OCR
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def ocr_1c_window():
    # 1. Ищем окно, в названии которого есть "1С:"
    # Обычно заголовки выглядят как "1С:Предприятие - [Название базы]"
    windows = [w for w in gw.getAllTitles() if "Ожидание запуска" in w]

    if not windows:
        print(
            "Окно 1С не найдено. Убедитесь, что программа запущена и в заголовке есть '1С:'."
        )
        return

    # Берем первое найденное окно
    win_title = windows[0]
    win = gw.getWindowsWithTitle(win_title)[0]

    print(f"Найдено окно: {win_title}")

    # 2. Активируем окно и выводим на передний план
    if win.isMinimized:
        win.restore()  # Разворачиваем, если свернуто
    win.activate()  # Делаем активным
    time.sleep(0.5)  # Небольшая пауза, чтобы окно успело прорисоваться

    # 3. Получаем координаты окна
    left, top, width, height = win.left, win.top, win.width, win.height

    # 4. Делаем скриншот только этой области
    screenshot = pyautogui.screenshot(region=(left, top, width, height))

    # (Опционально) Сохраняем скриншот, чтобы проверить, что попало в кадр
    screenshot.save("1c_screenshot.png")
    print("Скриншот успешно сделан и сохранен как 1c_screenshot.png")

    # 5. Распознаем текст (русский + английский)
    print("Распознавание текста... Подождите...")
    text = pytesseract.image_to_string(screenshot, lang="rus+eng")

    print("\n--- РЕЗУЛЬТАТ РАСПОЗНАВАНИЯ ---")
    print(text)
    print("--------------------------------")


if __name__ == "__main__":
    ocr_1c_window()