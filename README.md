# Change Watcher

A self-hosted web app that monitors web pages and APIs for changes and sends notifications when values change.

## Features

- Monitor HTML pages (CSS selectors, regex) and API endpoints (JSONPath, regex)
- Configurable check intervals per item
- Telegram notifications on value changes
- Import requests from cURL commands
- Test requests and notifications before activating
- Access-code authentication with brute-force protection
- HTMX-powered UI with Pico CSS

## Quick Start

```bash
pip install -r requirements.txt
python manage.py init-db
python manage.py add-code <your-access-code>
python app.py
```

Open `http://localhost:5000` and log in with your access code.

## Configuration

Copy `.env.example` to `.env` and set:

```
SECRET_KEY=<random-string>
TELEGRAM_BOT_TOKEN=<your-bot-token>
DATABASE_PATH=data/change_watcher.db
```

## Docker

```bash
cp .env.example .env
# edit .env with your values
docker compose up --build
```

Data is persisted in `./data/`.

## CLI

```
python manage.py init-db          # Initialize the database
python manage.py add-code <code>  # Add an access code
python manage.py cleanup          # Delete old logs and expired sessions
```

## Tech Stack

Python, Flask, SQLite (WAL), APScheduler, HTMX, Pico CSS, httpx, BeautifulSoup, jsonpath-ng
