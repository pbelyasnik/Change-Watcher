from datetime import datetime

import httpx

from config import Config


def send_telegram(chat_id: str, message: str) -> bool:
    token = Config.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError('TELEGRAM_BOT_TOKEN is not configured')

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True
    }

    with httpx.Client(timeout=15) as client:
        resp = client.post(url, json=payload)
        data = resp.json()
        if not data.get('ok'):
            raise ValueError(f'Telegram API error: {data.get("description", "Unknown error")}')
    return True


def send_notification(notification_type: str, notification_config: dict, message: str) -> bool:
    if notification_type == 'telegram':
        chat_id = notification_config.get('chat_id', '')
        if not chat_id:
            raise ValueError('Telegram Chat ID is required')
        return send_telegram(chat_id, message)
    else:
        raise ValueError(f'Unsupported notification type: {notification_type}')


def format_message(template: str, old_value: str, new_value: str, url: str, name: str) -> str:
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    return template.format(
        old_value=old_value or '(none)',
        new_value=new_value or '(none)',
        url=url,
        name=name,
        timestamp=now
    )
