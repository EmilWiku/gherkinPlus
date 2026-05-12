<div align="center">

# Pocket Option · торговый бот

**Асинхронный бот** с модульным пайплайном: сессия Pocket Option → анализ свечей и индикаторов → решения по входу → при необходимости уведомления в **Telegram**.

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Async](https://img.shields.io/badge/stack-asyncio-5865F2?style=flat-square)](https://docs.python.org/3/library/asyncio.html)
[![Env](https://img.shields.io/badge/config-.env-222?style=flat-square)](.env.example)

[В двух словах](#about) · [Gherkin‑контур](#llm-gherkin) · [Быстрый старт](#quickstart) · [Структура](#layout) · [Переменные](#env) · [Примеры](#examples)

</div>

<a id="llm-gherkin"></a>

> [!TIP]
> **Прогноз движения рынка — через Gherkin‑контракт, а не «простыню» промпта.**  
> Модели задаётся сценарий в духе **Given / When / Then**: что принимаем за данные и рамки, при каком условии допускается вывод, какие свойства ответа обязаны выполняться. Так сужается зона догадок, проще ловить ошибки и сопоставлять ответ с фактами **без переобучения весов**, за счёт явной проверяемости.

---

<a id="about"></a>

## В двух словах

Подключение к **Pocket Option** по SSID, пайплайн из **стадий** (связь → сигналы → ордера → Telegram → логи), SQLite для метрик. Клиент платформы — в **`PocketOptionAPI/`**. Другие режимы — **`versions/`**, архив — **`legacy/`**, рабочий код — **`bot_app/`** + **`main.py`**.

> **Безопасность:** токены, пароли и SSID — только в **`.env`** (шаблон — [`.env.example`](.env.example)). В git их не коммитьте.

---

<a id="quickstart"></a>

## Быстрый старт

```bash
git clone <repo-url>
cd <repo-dir>
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # или: cp .env.example .env
# заполните POCKET_OPTION_SSID и Telegram-поля — см. таблицу ниже

python main.py
```

---

<a id="layout"></a>

## Структура репозитория

| Каталог | Назначение |
|---------|------------|
| [`bot_app/`](bot_app/) | Ядро: конфиг, БД, бот, анализ, `stages/`, `app_main.py` |
| [`PocketOptionAPI/`](PocketOptionAPI/) | Асинхронный клиент Pocket Option |
| [`versions/`](versions/) | Другие точки входа (v1–v4, разные режимы) |
| [`scripts/`](scripts/) | Деплой, SSH, SSID через Selenium, диагностика |
| [`requirements/`](requirements/) | `server.txt`, `visualization.txt` |
| [`examples/`](examples/) | Примеры (графики и т.п.) |
| [`ansible/`](ansible/) | Развёртывание на Linux через Ansible |
| [`visualization_lib/`](visualization_lib/) | Рендер картинок для Telegram |
| [`data/`](data/) | Локальные данные (SSID-файлы, выгрузки) — не для коммита |
| [`artifacts/`](artifacts/) | Сгенерированное (чарты, sqlite по умолчанию) |
| [`legacy/`](legacy/) | Архивные tryout-скрипты |

<details>
<summary><strong>Дерево (схематично)</strong></summary>

```
.
├── main.py                 # лаунчер: PYTHONPATH → bot_app + PocketOptionAPI
├── bot_app/
│   ├── app_main.py         # основной async-сценарий
│   ├── bot.py
│   ├── stages/
│   └── …
├── PocketOptionAPI/
├── versions/
├── scripts/
├── requirements/
├── examples/
└── …
```

</details>

Корневой **`main.py`** только настраивает пути и вызывает логику из **`bot_app/app_main.py`**.

---

<a id="env"></a>

## Переменные окружения

Скопируйте [`.env.example`](.env.example) → `.env` и заполните.

| Переменная | Когда нужна | Описание |
|------------|-------------|----------|
| `POCKET_OPTION_SSID` | Почти всегда | Сессия / auth-строка Pocket Option |
| `POCKET_OPTION_SSID_FILE` | Альтернатива SSID | Путь к файлу; первая строка = сессия (если `POCKET_OPTION_SSID` пуст) |
| `TELEGRAM_BOT_TOKEN` | `python main.py` | Токен бота от @BotFather |
| `TELEGRAM_CHANNEL_ID` | `python main.py` | Канал / группа (`-100…` или `@channel`) |
| `TELEGRAM_TOPIC_ID` | Опционально | Тема в супергруппе (`main_v3`, `main_v4`) |
| `POCKET_OPTION_PROXY_URL` | Опционально | SOCKS5 / HTTP прокси |
| `TRADE_DB_PATH` | Опционально | Путь к SQLite метрик (по умолчанию под `artifacts/`) |
| `DEPLOY_SSH_HOST`, `DEPLOY_SSH_USER`, `DEPLOY_SSH_PASSWORD` | Скрипты деплоя | SSH в `scripts/*` |
| `POCKET_OPTION_EMAIL`, `POCKET_OPTION_PASSWORD` | Selenium | Только для `scripts/get_ssid_automated.py` |

---

<a id="examples"></a>

## Примеры

**Основной бот** (из корня репозитория):

```bash
python main.py
```

**Графики по свечам** (нужен SSID в `.env`):

```bash
python examples/generate_chart_techniques.py --asset GBPJPY_otc
```

**Доп. зависимости:**

```bash
pip install -r requirements/server.txt          # сервер / прод-стек
pip install -r requirements/visualization.txt   # графики и визуализация
```

---

