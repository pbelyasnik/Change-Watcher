import json

from flask import Blueprint, g, jsonify, request

from db import get_db
from services.crypto import decrypt_value
from services.executor import execute_step_debug, execute_pipeline_debug
from services.notifier import send_notification
from services.pipeline import validate_pipeline, get_steps_from_config

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/validate-yaml', methods=['POST'])
def validate_yaml():
    data = request.get_json(silent=True) or {}
    yaml_str = data.get('yaml', '')

    config, errors = validate_pipeline(yaml_str)

    if errors:
        return jsonify({'valid': False, 'errors': errors})

    # Return step names for the debugger
    steps = get_steps_from_config(config)
    step_info = []
    for step_type, step in steps:
        name = step.get('name', 'check') if step_type == 'auth' else 'check'
        step_info.append({'name': name, 'type': step_type})

    return jsonify({'valid': True, 'errors': [], 'steps': step_info})


@api_bp.route('/test-step', methods=['POST'])
def test_step():
    data = request.get_json(silent=True) or {}
    item_id = data.get('item_id')
    step_index = data.get('step_index', 0)
    variables = data.get('variables', {})
    yaml_str = data.get('yaml', '')

    # Load secrets if item exists
    secrets = {}
    if item_id:
        secrets = _load_secrets(item_id)

    config, errors = validate_pipeline(yaml_str)
    if errors:
        return jsonify({'success': False, 'error': '; '.join(errors)}), 400

    steps = get_steps_from_config(config)
    if step_index < 0 or step_index >= len(steps):
        return jsonify({'success': False, 'error': 'Invalid step index.'}), 400

    step_type, step_config = steps[step_index]
    shared_headers = config.get('shared_headers') or {}

    sr = execute_step_debug(step_config, step_type, shared_headers, variables, secrets)

    return jsonify({
        'success': sr.error is None,
        'step_name': sr.step_name,
        'step_type': sr.step_type,
        'http_status': sr.http_status,
        'duration_ms': sr.duration_ms,
        'extracted_vars': sr.extracted_vars,
        'response_body': sr.response_body,
        'response_headers': sr.response_headers,
        'error': sr.error,
        'skipped': sr.skipped,
    })


@api_bp.route('/test-pipeline', methods=['POST'])
def test_pipeline():
    data = request.get_json(silent=True) or {}
    item_id = data.get('item_id')
    yaml_str = data.get('yaml', '')

    secrets = {}
    if item_id:
        secrets = _load_secrets(item_id)

    results = execute_pipeline_debug(yaml_str, secrets)

    steps_out = []
    all_vars = {}
    for sr in results:
        steps_out.append({
            'step_name': sr.step_name,
            'step_type': sr.step_type,
            'http_status': sr.http_status,
            'duration_ms': sr.duration_ms,
            'extracted_vars': sr.extracted_vars,
            'response_body': sr.response_body,
            'error': sr.error,
            'skipped': sr.skipped,
        })
        if sr.extracted_vars:
            all_vars.update(sr.extracted_vars)

    return jsonify({
        'success': all(sr.error is None for sr in results),
        'steps': steps_out,
        'variables': all_vars,
    })


@api_bp.route('/test-notification', methods=['POST'])
def test_notification():
    data = request.get_json(silent=True) or {}
    notification_type = data.get('notification_type', 'telegram')
    notification_config = data.get('notification_config', {})

    message = 'This is a test notification from Change Watcher.'

    try:
        send_notification(notification_type, notification_config, message)
        return jsonify({'success': True, 'message': 'Notification sent successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


def _load_secrets(item_id):
    db = get_db()
    rows = db.execute(
        'SELECT key, encrypted_value FROM pipeline_secrets WHERE watch_item_id = ?',
        (item_id,)
    ).fetchall()
    secrets = {}
    for row in rows:
        try:
            secrets[row['key']] = decrypt_value(row['encrypted_value'])
        except Exception:
            secrets[row['key']] = ''
    return secrets
