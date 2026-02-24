import json
import time

from flask import current_app

from db import get_db
from services.crypto import decrypt_value
from services.executor import execute_pipeline
from services.notifier import format_message, send_notification


def check_item(item: dict) -> dict:
    start = time.time()
    item_id = item['id']
    previous_value = item['current_value']
    had_error = bool(item['last_error'])

    db = get_db()

    # Load secrets
    secret_rows = db.execute(
        'SELECT key, encrypted_value FROM pipeline_secrets WHERE watch_item_id = ?',
        (item_id,)
    ).fetchall()
    secrets = {}
    for row in secret_rows:
        try:
            secrets[row['key']] = decrypt_value(row['encrypted_value'])
        except Exception:
            secrets[row['key']] = ''

    # Load pipeline state
    state_row = db.execute(
        'SELECT variables FROM pipeline_state WHERE watch_item_id = ?',
        (item_id,)
    ).fetchone()
    state_vars = json.loads(state_row['variables']) if state_row else {}

    # Execute pipeline
    result = execute_pipeline(
        item['pipeline_yaml'],
        secrets,
        state_vars,
        previous_value=previous_value,
    )

    parsed_value = result.final_value
    value_changed = result.value_changed
    error_msg = result.error
    notification_sent = False

    # Persist updated variables
    new_vars = json.dumps(result.variables)
    if state_row:
        db.execute(
            "UPDATE pipeline_state SET variables = ?, updated_at = datetime('now') WHERE watch_item_id = ?",
            (new_vars, item_id)
        )
    else:
        db.execute(
            "INSERT INTO pipeline_state (watch_item_id, variables) VALUES (?, ?)",
            (item_id, new_vars)
        )

    # Determine notifications
    should_notify_change = value_changed
    should_notify_error = error_msg and not had_error
    should_notify_recovery = not error_msg and had_error

    if should_notify_change or should_notify_error or should_notify_recovery:
        try:
            notification_type = item['notification_type']
            notification_config = json.loads(item['notification_config']) if item['notification_config'] else {}

            if should_notify_error:
                message = f'⚠️ {item["name"]}\n\nError: {error_msg}\n\nPipeline: {item["name"]}'
            elif should_notify_recovery:
                message = f'✅ {item["name"]}\n\nRecovered — working normally again.'
            else:
                template = item['message_template'] or (
                    '🔔 {name}\n\nValue changed!\nOld: {old_value}\nNew: {new_value}\n\nTime: {timestamp}'
                )
                # Extract URL from check step for message
                url = ''
                try:
                    import yaml
                    config = yaml.safe_load(item['pipeline_yaml'])
                    url = config.get('check', {}).get('url', '')
                except Exception:
                    pass
                message = format_message(template, previous_value, parsed_value, url, item['name'])

            send_notification(notification_type, notification_config, message)
            notification_sent = True
        except Exception as notify_err:
            if error_msg:
                error_msg += f'; Notification failed: {notify_err}'
            else:
                error_msg = f'Notification failed: {notify_err}'

    duration_ms = int((time.time() - start) * 1000)

    # Determine http_status from the last check step
    http_status = None
    for sr in reversed(result.step_results):
        if sr.step_type == 'check':
            http_status = sr.http_status
            break

    # Update watch_items
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

    # Log each step
    for sr in result.step_results:
        db.execute(
            '''INSERT INTO request_logs
               (watch_item_id, step_name, http_status, parsed_value, previous_value,
                value_changed, notification_sent, error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (item_id, sr.step_name, sr.http_status, parsed_value if sr.step_type == 'check' else None,
             previous_value if sr.step_type == 'check' else None,
             1 if value_changed and sr.step_type == 'check' else 0,
             1 if notification_sent and sr.step_type == 'check' else 0,
             sr.error, sr.duration_ms)
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
        'duration_ms': duration_ms,
    }
