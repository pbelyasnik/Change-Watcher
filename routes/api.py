import json
import time

import httpx
from flask import Blueprint, jsonify, request

from config import Config
from services.parsers import parse_css, parse_jsonpath, parse_regex
from services.notifier import send_notification

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/test-request', methods=['POST'])
def test_request():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    method = data.get('method', 'GET').upper()
    headers = data.get('headers', {})
    body = data.get('body', '')
    selector_type = data.get('selector_type', 'css')
    selector = data.get('selector', '').strip()

    if not url:
        return jsonify({'success': False, 'error': 'URL is required'}), 400
    if not selector:
        return jsonify({'success': False, 'error': 'Selector is required'}), 400

    try:
        start = time.time()
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.request(method, url, headers=headers, content=body if body else None)
        duration_ms = int((time.time() - start) * 1000)

        content = resp.text

        if selector_type == 'css':
            value = parse_css(content, selector)
        elif selector_type == 'jsonpath':
            value = parse_jsonpath(content, selector)
        elif selector_type == 'regex':
            value = parse_regex(content, selector)
        else:
            return jsonify({'success': False, 'error': f'Unknown selector type: {selector_type}'}), 400

        return jsonify({
            'success': True,
            'value': value,
            'http_status': resp.status_code,
            'duration_ms': duration_ms
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api_bp.route('/test-notification', methods=['POST'])
def test_notification():
    data = request.get_json(silent=True) or {}
    notification_type = data.get('notification_type', 'telegram')
    notification_config = data.get('notification_config', {})

    message = 'This is a test notification from Change Watcher.'

    try:
        result = send_notification(notification_type, notification_config, message)
        return jsonify({'success': True, 'message': 'Notification sent successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
