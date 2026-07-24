#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Микро-починщик BSL: детерминированный delint + Qwen (LM Studio).
Это будущий инструмент fix_micro для 1С MCP-сервера. Пока — отдельный
тестируемый модуль. Самопроверка:  python3 fixer.py
"""
import json, re, time, urllib.request

# --- LM Studio ---
LM_BASE = "http://localhost:1235/v1"
LM_KEY = "sk-lm-FQkn7Xhd:yYxzccoJ7B04iFDN8hu5"  # локальный ключ
TEMPERATURE = 0.15
MAX_TOKENS = 1200

# --- DELINT: известные галлюцинации локалки -> валидный BSL ---
# Только то, что НЕ валидно ни по-русски, ни по-английски (English-варианты
# в BSL легальны: Return/If/True — их НЕ трогаем). Расширяем по мере наблюдения
# за Qwen. Замена по границе слова. Осторожно со строковыми литералами:
# правила добавляем только для токенов, которые в строках почти не встречаются.
DELINT_RULES = [
    (r"\bВернуть\b", "Возврат"),       # наблюдали: Вернуть -> Возврат
    (r"\bКонецДля\b", "КонецЦикла"),   # 21x в логах: КонецДля -> КонецЦикла
    # (r"==", "="),                    # кандидаты — включим, когда увидим
    # (r"!=", "<>"),
]


def delint(code: str):
    fixes = []
    for pat, repl in DELINT_RULES:
        code, n = re.subn(pat, repl, code)
        if n:
            fixes.append({"rule": pat, "n": n})
    return code, fixes


SYSTEM = (
    "Ты — починщик кода на встроенном языке 1С (BSL). "
    "На вход: одна процедура/функция и одна ошибка. "
    "Верни ТОЛЬКО исправленный код в блоке ```bsl ... ```. "
    "Без объяснений. /no_think"
)


def _strip_fences(text: str) -> str:
    # срезаем всё до открывающего ``` (в т.ч. возможный leaked <think>) и после
    t = re.sub(r"^.*?```(?:bsl|1c)?\s*", "", text, flags=re.S | re.I)
    t = re.sub(r"\s*```.*$", "", t, flags=re.S)
    return t.strip()


def get_model():
    req = urllib.request.Request(LM_BASE + "/models",
        headers={"Authorization": "Bearer " + LM_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["data"][0]["id"]


def qwen_available(timeout: float = 2.0) -> bool:
    """
    Быстрая проверка, поднят ли LM Studio — ДО того как heal_module/fix_snippet
    попробуют что-то чинить. LM Studio нужен только этим двум инструментам;
    если он выключен, петля должна деградировать грациозно (вернуть Клоду
    прогон без починки), а не падать непонятной ошибкой соединения.
    """
    try:
        req = urllib.request.Request(LM_BASE + "/models",
            headers={"Authorization": "Bearer " + LM_KEY})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def qwen_fix(code: str, error: str, model: str):
    user = "Ошибка:\n" + error + "\n\nКод:\n```bsl\n" + code + "\n```"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "stream": False,
    }).encode()
    req = urllib.request.Request(LM_BASE + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + LM_KEY})
    with urllib.request.urlopen(req, timeout=60) as r:   # подвис Qwen -> падаем за 60с, не виснем
        resp = json.loads(r.read())
    return _strip_fences(resp["choices"][0]["message"]["content"]), resp.get("usage", {})


def fix_once(code: str, error: str, model=None):
    """delint -> Qwen. Возвращает (исправленный_код, отчёт)."""
    code, dl = delint(code)
    if model is None:
        model = get_model()
    t = time.time()
    fixed, usage = qwen_fix(code, error, model)
    return fixed, {"delint": dl, "qwen": {"sec": round(time.time() - t, 1), "usage": usage}}


# ---- самопроверка ----
if __name__ == "__main__":
    broken = (
        "Функция ПолучитьСумму(Товары)\n"
        "    Сумма = 0;\n"
        "    Для Каждного Стр Из Товары Цикл\n"
        "        Сумма = Сумма + Стр.Цена * Стр.Количество;\n"
        "    КонецЦикла;\n"
        "КонецФункции"
    )
    err = "{Модуль(3)}: ожидается 'Каждого'; функция не возвращает значение."
    print("=== ДО ===\n" + broken)
    fixed, rep = fix_once(broken, err)
    print("\n=== delint ===", rep["delint"])
    print("=== qwen  ===", rep["qwen"])
    print("\n=== ПОСЛЕ ===\n" + fixed)
    if re.search(r"\bВернуть\b", fixed):
        print("\n[!] Снова 'Вернуть' — delint добьёт на следующем круге.")
    elif re.search(r"\bВозврат\b", fixed):
        print("\n[OK] Корректный 'Возврат'.")
