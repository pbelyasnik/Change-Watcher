import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 'data/change_watcher.db')
    FLASK_SESSION_COOKIE_NAME = 'cw_flask_session'
    AUTH_COOKIE_NAME = 'cw_session_token'
    SESSION_MAX_AGE_DAYS = 7
    BRUTE_FORCE_WINDOW_MINUTES = 15
    BRUTE_FORCE_MAX_ATTEMPTS = 5
    LOG_RETENTION_DAYS = 30
    CHECK_INTERVAL_SECONDS = 15
