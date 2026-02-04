import json
import time

import httpx
from flask import current_app

from db import get_db
from services.notifier import format_message, send_notification
from services.parsers import parse_css, parse_jsonpath, parse_regex


def check_item(item: dict) -> dict:
    start = time.time()
    item_id = item['id']
    url = item['url']
    method = item['method'] or 'GET'
    headers = json.loads(item['headers']) if item['headers'] else {}
    body = item['body'] or ''
    selector_type = item['selector_type']
    selector = item['selector']
    previous_value = item['current_value']
    had_error = bool(item['last_error'])

    http_status = None
    parsed_value = None
    value_changed = False
    notification_sent = False
    error_msg = None

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.request(method, url, headers=headers, content=body if body else None)
        http_status = resp.status_code
        content = resp.text

        if selector_type == 'css':
            parsed_value = parse_css(content, selector)
        elif selector_type == 'jsonpath':
            parsed_value = parse_jsonpath(content, selector)
        elif selector_type == 'regex':
            parsed_value = parse_regex(content, selector)
        else:
            raise ValueError(f'Unknown selector type: {selector_type}')

        # Compare values
        if previous_value is not None and parsed_value != previous_value:
            value_changed = True

    except Exception as e:
        error_msg = str(e)
        parsed_value = None

    # Determine what notifications to send
    should_notify_change = value_changed
    should_notify_error = error_msg and not had_error  # only on first occurrence
    should_notify_recovery = not error_msg and had_error  # error just cleared

    if should_notify_change or should_notify_error or should_notify_recovery:
        try:
            notification_type = item['notification_type']
            notification_config = json.loads(item['notification_config']) if item['notification_config'] else {}

            if should_notify_error:
                message = f'⚠️ {item["name"]}\n\nError: {error_msg}\n\nURL: {url}'
            elif should_notify_recovery:
                message = f'✅ {item["name"]}\n\nRecovered — working normally again.\n\nURL: {url}'
            else:
                template = item['message_template'] or (
                    '🔔 {name}\n\nValue changed!\nOld: {old_value}\nNew: {new_value}\n\nURL: {url}\nTime: {timestamp}'
                )
                message = format_message(template, previous_value, parsed_value, url, item['name'])

            send_notification(notification_type, notification_config, message)
            notification_sent = True
        except Exception as notify_err:
            if error_msg:
                error_msg += f'; Notification failed: {notify_err}'
            else:
                error_msg = f'Notification failed: {notify_err}'

    duration_ms = int((time.time() - start) * 1000)

    # Update DB
    db = get_db()
    if parsed_value is not None:
        db.execute(
            "UPDATE watch_items SET current_value = ?, last_error = NULL, "
            "last_checked_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (parsed_value, item_id)
        )
    else:
        db.execute(
            "UPDATE watch_items SET last_error = ?, "
            "last_checked_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (error_msg, item_id)
        )

    db.execute(
        '''INSERT INTO request_logs
           (watch_item_id, http_status, parsed_value, previous_value,
            value_changed, notification_sent, error, duration_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (item_id, http_status, parsed_value, previous_value,
         1 if value_changed else 0, 1 if notification_sent else 0,
         error_msg, duration_ms)
    )
    db.commit()

    return {
        'item_id': item_id,
        'http_status': http_status,
        'parsed_value': parsed_value,
        'previous_value': previous_value,
        'value_changed': value_changed,
        'notification_sent': notification_sent,
        'error': error_msg,
        'duration_ms': duration_ms
    }
