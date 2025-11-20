# Bazos AutoReg (Windows) — v2

**Что делает (ровно по требованию):**
1. Открывает **любой раздел** (рандомную категорию) на **bazos.cz**, затем выбирает **случайное объявление**.
2. Принимает cookies.
3. Через API-сервис **берёт номер**, **вставляет в форму**, жмёт «отправить код».
4. **Ждёт код**, вводит его, жмёт «подтвердить».
   - Если **успех** → сохраняет куки в `BazosCookies/CZ/cookies-...txt`.
   - Если **ошибка** → ждёт **60 секунд**, **перезагружает** страницу и **повторяет попытку** (до 3 раз).
5. Через **60 сек** повторяет **то же для bazos.sk** **с тем же номером** (запрашивает новый код у провайдера).
   - При успехе сохраняет `BazosCookies/SK/cookies-...txt`.
6. После CZ+SK завершения переходит к **следующему циклу** с **новым номером**.
7. **Прокси**: один прокси на **весь цикл** (CZ+SK), затем берётся следующий из `proxies.txt` (карусель).

## Установка
```bat
pip install -r requirements.txt
python -m playwright install
```

## Запуск (видимый браузер и 3 цикла)
```bat
python main.py --headful --runs 3
```

## Конфигурация
- `config.json`
  - `sms_provider`: `manual` | `provider_a` | `provider_b`
  - `provider_a / provider_b`: `api_key`, `base_url` — вставьте из ваших доков
  - `timeout_sec`: таймаут ожидания SMS
  - `delay_between_countries_sec`: пауза между CZ и SK (по умолчанию 60)
  - `max_attempts_per_country`: попыток подтверждения кода (по умолчанию 3)
- `proxies.txt`: по строке на прокси, формат `http://user:pass@host:port` или `socks5://...`.
  Прокси применяется на **весь цикл** (CZ+SK), затем переключается на следующий.

## Встраивание 2 SMS-API
Файл `sms_providers.py` содержит классы-заглушки `ProviderA` и `ProviderB`. Пришлите:
- URL покупки номера (с параметром страны CZ/SK), формат ответа `{activation_id, phone}`
- URL получения кода по `activation_id` (долгий опрос/статус)
- URL для **повторной отправки кода** (если требуется для SK)
- URL финализации (успех/отмена)

Я впишу логику сразу после того, как дадите спецификации.

## Где лежат cookies
- `./BazosCookies/CZ/cookies-*.txt`
- `./BazosCookies/SK/cookies-*.txt`

Формат строк: `name=...; value=...; domain=...; path=/; secure=false; httpOnly=false; sameSite=Lax; expirationDate=...`

## Примечания
- Структура страниц Bazos может меняться. Селекторы сделаны максимально гибко (по текстам и типам инпутов). Если на вашем аккаунте поля/тексты отличаются — подстрою.
- При ручном провайдере (`manual`) программа спросит номер и коды в консоли.


### Профили (fingerprint-lite)
- Файл `profiles.json`: один профиль на цикл (CZ+SK). Настраиваются `locale`, `timezoneId`, `userAgent`, `viewport`, `colorScheme`.
- Это не «антидетект» — только легальные параметры окружения для тестов совместимости.
- Пример запуска с профилями: `python main.py --headful --runs 2 --profiles profiles.json`


### Подключение SMS API (Generic)
- Установите `sms_provider` в `generic` и заполните секцию `generic` в `config.json`.
- Опишите пути и методы `buy/status/resend/finalize`, заголовки (токен) и извлечение полей (`extract.id_path`, `extract.phone_path`, `extract.code_path`, `extract.status_path`).
- Провайдер запросит номер (`request_number`), подождёт код (`wait_for_sms`), умеет `request_new_code` (для SK) и `finalize`.


### Настройки в GUI
- Во вкладке **SMS провайдер**: выбери `onlinesim` или `manual`, вставь API key, service, base URL.
- Во вкладке **Прокси**: редактируй список прокси прямо в окне, один на строку.


### Выбор страны и сервиса для SMS
- Во вкладке **SMS провайдер** теперь можно выбрать `Service` (по каталогу OnlineSim) и `Страна` (CZ, SK, PL, DE).
- Эти параметры используются в запросе номера (`getNum.php`).


### Ротация 1 цикл = 1 прокси + 1 профиль
- Софт гарантирует, что каждый цикл (CZ→SK) использует ровно один прокси и один профиль.
- В `config.json.rotation` можно настроить `proxy_cooldown_cycles` и `profile_cooldown_cycles`.
- Хедеры `Accept-Language` и геолокация выставляются из профиля; куки и storage-state сохраняются по странам.


### Автоподстановка языка/гео/часового пояса по прокси
- Опция `auto_match_proxy_locale` (и чекбокс в GUI) определяет IP через прокси и тянет геоданные (страна, таймзона, координаты).
- Софт автоматически ставит `locale`, `Accept-Language`, `timezoneId`, `geolocation` для контекста Playwright.
- Это НЕ антидетект и НЕ спуфинг Canvas/WebGL; только корректная настройка окружения под IP.


### Persistent context (на каждый цикл)
- В `config.json` включён `use_persistent_context: true`.
- Профиль Chromium сохраняется в `./UserData/cycle-N`, 1 цикл = 1 профиль браузера.
- Включён флаг `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` для предотвращения WebRTC обхода прокси.


### WebRTC через прокси
- По умолчанию включено `--force-webrtc-ip-handling-policy=proxy_only`, чтобы WebRTC не использовал прямой UDP и работал только через прокси.
- Включена опция `WebRtcHideLocalIpsWithMdns`, чтобы локальные IP не раскрывались в JS.
- Для корректности используйте HTTPS/SOCKS5 прокси. HTTP прокси без UDP может приводить к отсутствию WebRTC-кандидатов (что обычно трактуется как «WebRTC скрыт»).


### Всё от прокси (Auto from proxy)
- Вкладка **SMS провайдер** → `Режим выбора страны`: **auto_from_proxy**.
- Софт определяет IP через прокси и выбирает страну активации (CZ/SK/PL/DE) по геолокации IP.
- Профиль браузера (locale/Accept-Language/timezone/geolocation) уже подставляется по IP прокси автоматически.
