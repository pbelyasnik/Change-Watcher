import json

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
)

from db import get_db

items_bp = Blueprint('items', __name__)


@items_bp.route('/')
def index():
    return redirect(url_for('items.item_list'))


@items_bp.route('/items')
def item_list():
    db = get_db()
    items = db.execute(
        'SELECT * FROM watch_items WHERE access_code_id = ? ORDER BY created_at DESC',
        (g.user_id,)
    ).fetchall()
    return render_template('items/list.html', items=items)


@items_bp.route('/items/new', methods=['GET', 'POST'])
def item_new():
    if request.method == 'GET':
        return render_template('items/edit.html', item=None)
    return _save_item(None)


@items_bp.route('/items/<int:item_id>', methods=['GET', 'POST'])
def item_edit(item_id):
    db = get_db()
    item = db.execute(
        'SELECT * FROM watch_items WHERE id = ? AND access_code_id = ?',
        (item_id, g.user_id)
    ).fetchone()
    if not item:
        flash('Item not found.', 'error')
        return redirect(url_for('items.item_list'))

    if request.method == 'GET':
        return render_template('items/edit.html', item=item)
    return _save_item(item_id)


@items_bp.route('/items/<int:item_id>/toggle', methods=['POST'])
def item_toggle(item_id):
    db = get_db()
    item = db.execute(
        'SELECT * FROM watch_items WHERE id = ? AND access_code_id = ?',
        (item_id, g.user_id)
    ).fetchone()
    if not item:
        return 'Not found', 404

    if item['status'] == 'draft':
        return 'Cannot toggle a draft item', 400

    new_status = 'paused' if item['status'] == 'active' else 'active'
    db.execute(
        'UPDATE watch_items SET status = ?, updated_at = datetime(\'now\') WHERE id = ?',
        (new_status, item_id)
    )
    db.commit()

    item = db.execute('SELECT * FROM watch_items WHERE id = ?', (item_id,)).fetchone()
    return render_template('partials/item_row.html', item=item)


@items_bp.route('/items/<int:item_id>/run', methods=['POST'])
def item_run(item_id):
    db = get_db()
    item = db.execute(
        'SELECT * FROM watch_items WHERE id = ? AND access_code_id = ?',
        (item_id, g.user_id)
    ).fetchone()
    if not item:
        return 'Not found', 404

    from services.checker import check_item
    result = check_item(dict(item))

    item = db.execute('SELECT * FROM watch_items WHERE id = ?', (item_id,)).fetchone()
    return render_template('partials/item_row.html', item=item)


def _save_item(item_id):
    db = get_db()
    action = request.form.get('action', 'save')

    name = request.form.get('name', '').strip()
    check_type = request.form.get('check_type', 'html')
    url = request.form.get('url', '').strip()
    method = request.form.get('method', 'GET')
    body = request.form.get('body', '').strip()
    selector_type = request.form.get('selector_type', 'css')
    selector = request.form.get('selector', '').strip()
    notification_type = request.form.get('notification_type', 'telegram')
    chat_id = request.form.get('chat_id', '').strip()
    message_template = request.form.get('message_template', '').strip()
    interval_minutes = request.form.get('interval_minutes', '5')
    current_value = request.form.get('current_value', '')

    # Build headers from dynamic form fields
    header_keys = request.form.getlist('header_key')
    header_values = request.form.getlist('header_value')
    headers = {}
    for k, v in zip(header_keys, header_values):
        k = k.strip()
        if k:
            headers[k] = v.strip()

    notification_config = json.dumps({'chat_id': chat_id})
    headers_json = json.dumps(headers)

    if not name or not url:
        flash('Name and URL are required.', 'error')
        if item_id:
            return redirect(url_for('items.item_edit', item_id=item_id))
        return redirect(url_for('items.item_new'))

    try:
        interval_minutes = int(interval_minutes)
        if interval_minutes < 1:
            interval_minutes = 1
    except (ValueError, TypeError):
        interval_minutes = 5

    if not message_template:
        message_template = (
            '🔔 {name}\n\n'
            'Value changed!\n'
            'Old: {old_value}\n'
            'New: {new_value}\n\n'
            'URL: {url}\n'
            'Time: {timestamp}'
        )

    if item_id is None:
        status = 'active' if action == 'activate' else 'draft'
        db.execute(
            '''INSERT INTO watch_items
               (access_code_id, name, check_type, url, method, headers, body,
                selector_type, selector, notification_type, notification_config,
                message_template, current_value, status, interval_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (g.user_id, name, check_type, url, method, headers_json, body,
             selector_type, selector, notification_type, notification_config,
             message_template, current_value, status, interval_minutes)
        )
    else:
        existing = db.execute(
            'SELECT status FROM watch_items WHERE id = ?', (item_id,)
        ).fetchone()
        if action == 'activate':
            status = 'active'
        elif existing and existing['status'] != 'draft':
            status = existing['status']
        else:
            status = 'draft'

        db.execute(
            '''UPDATE watch_items SET
               name=?, check_type=?, url=?, method=?, headers=?, body=?,
               selector_type=?, selector=?, notification_type=?, notification_config=?,
               message_template=?, current_value=?, status=?, interval_minutes=?,
               updated_at=datetime('now')
               WHERE id=? AND access_code_id=?''',
            (name, check_type, url, method, headers_json, body,
             selector_type, selector, notification_type, notification_config,
             message_template, current_value, status, interval_minutes,
             item_id, g.user_id)
        )

    db.commit()
    flash('Item saved successfully.', 'success')
    return redirect(url_for('items.item_list'))
