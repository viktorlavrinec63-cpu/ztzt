BazosAutoReg — FINAL build

Что внутри (ядро):
- main.py — цикл: один номер/прокси/слепок до успеха на CZ и SK; паузы, повторы, 'blocked'.
- bazos_bot.py — автоклики (куки, рандом категория/объявление, показать телефон), печать номера/кода "как человек",
  распознавание успех/ошибка/бан, сохранение cookies ТОЛЬКО при успехе в BazosCookies/Чехия|Словакия.
- sms_providers.py — OnlineSim API (getNum/getState/revise/ok), finalize(success,banned).
- main_gui.py — GUI с раздельным выбором домена (CZ/SK) и страны номера (PL/CZ/SK/DE).
- proxy_utils.py — парсер прокси (http/socks5, с/без логина).
- run.bat — быстрый запуск GUI.

Полезное:
- diag_onlinesim.py — диагностика ключа/сервиса OnlineSim.
- extras/ — альтернативные версии файлов, если хочешь вернуться к ранним вариантам.

Быстрый старт:
1) Отредактируй config.json (ключи/страны) или через вкладку "SMS провайдер" в GUI.
2) В proxies.txt укажи HTTP-прокси с авторизацией (или SOCKS5 без логина/пароля).
3) Запуск: двойной клик по run.bat, далее "Старт".

Куда пишутся cookies:
- bazos.cz → BazosCookies/Чехия/...
- bazos.sk → BazosCookies/Словакия/...

Настройки в config.json:
{
  "delay_between_countries_sec": 60,
  "max_number_cycles": 5,
  "retry_delay_sec": 60,
  "onlinesim": {
    "sms_number_country_mode": "manual",
    "sms_number_country": "PL",
    "activation_country_mode": "manual",
    "activation_country": "CZ",
    "timeout_sec": 120,
    "api_key": "ВАШ_КЛЮЧ",
    "base_url": "https://onlinesim.io",
    "service": "bazos"
  }
}