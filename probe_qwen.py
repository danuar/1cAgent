#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Проба локальной модели (LM Studio) на роль "микро-починщик BSL".
# Запускать на ТВОЕЙ машине, где доступен localhost:1235.
#   python3 probe_qwen.py
import json, time, urllib.request, urllib.error

BASE = "http://localhost:1235/v1"
API_KEY = "sk-lm-FQkn7Xhd:yYxzccoJ7B04iFDN8hu5"  # локальный ключ LM Studio
TEMPERATURE = 0.15
MAX_TOKENS = 1200
CTX_LIMIT = 30000  # твоё рабочее окно

# /no_think выключает режим рассуждения Qwen3 (иначе он жрёт бюджет и контекст).
# Если не сработает — выключи "thinking" тумблером в LM Studio.
SYSTEM = (
    "Ты — починщик кода на встроенном языке 1С (BSL). "
    "На вход: одна процедура/функция и одна ошибка компилятора. "
    "Верни ТОЛЬКО исправленный код в блоке ```bsl ... ```. "
    "Без объяснений и без лишнего текста. /no_think"
)

CASES = [
    {
        "name": "опечатка + нет Возврата",
        "code": (
            "Функция ПолучитьСуммуДокумента(Товары)\n"
            "    Сумма = 0;\n"
            "    Для Каждного СтрокаТовар Из Товары Цикл\n"
            "        Сумма = Сумма + СтрокаТовар.Цена * СтрокаТовар.Количество;\n"
            "    КонецЦикла;\n"
            "КонецФункции"
        ),
        "error": "{Модуль(3)}: ожидается ключевое слово 'Каждого'. "
                 "Также: функция не возвращает значение.",
    },
    {
        "name": "пропущен КонецЕсли",
        "code": (
            "Функция НайтиСтроку(Таблица, Артикул)\n"
            "    Для Каждого Стр Из Таблица Цикл\n"
            "        Если Стр.Артикул = Артикул Тогда\n"
            "            Возврат Стр;\n"
            "    КонецЦикла;\n"
            "    Возврат Неопределено;\n"
            "КонецФункции"
        ),
        "error": "{Модуль(5)}: не найдено соответствие 'Если' ... 'КонецЕсли'.",
    },
]


def _req(path, data=None):
    headers = {"Authorization": "Bearer " + API_KEY}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    return urllib.request.Request(BASE + path, data=data, headers=headers)


def get_model():
    with urllib.request.urlopen(_req("/models"), timeout=30) as r:
        return json.loads(r.read())["data"][0]["id"]


def chat(model, user):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "stream": False,
    }
    with urllib.request.urlopen(_req("/chat/completions", body), timeout=180) as r:
        return json.loads(r.read())


def main():
    try:
        model = get_model()
    except Exception as e:
        print("Не достучался до", BASE, "->", e)
        return
    print("Модель:", model)
    print("=" * 60)
    for c in CASES:
        user = "Ошибка:\n" + c["error"] + "\n\nКод:\n```bsl\n" + c["code"] + "\n```"
        t = time.time()
        try:
            resp = chat(model, user)
        except urllib.error.HTTPError as e:
            print("\n###", c["name"], "-> HTTP", e.code, e.read().decode()[:300])
            continue
        dt = time.time() - t
        u = resp.get("usage", {})
        fin = resp["choices"][0].get("finish_reason", "?")  # length = обрезано
        total = u.get("total_tokens", "?")
        flag = "  <-- ВЫШЕ ОКНА!" if isinstance(total, int) and total > CTX_LIMIT else ""
        print("\n### {}  ({:.1f}s, finish={})".format(c["name"], dt, fin))
        print("токены: prompt={} completion={} total={}{}".format(
            u.get("prompt_tokens", "?"), u.get("completion_tokens", "?"),
            total, flag))
        print(resp["choices"][0]["message"]["content"].strip())
        print("-" * 60)


if __name__ == "__main__":
    main()
