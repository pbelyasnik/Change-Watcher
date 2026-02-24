import json

import yaml
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
)

from db import get_db
from services.crypto import encrypt_value
from services.pipeline import validate_pipeline, DEFAULT_YAML_TEMPLATE

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

    # Parse check URL from YAML for display
    items_data = []
    for item in items:
        item_dict = dict(item)
        item_dict['check_url'] = ''
        try:
            config = yaml.safe_load(item['pipeline_yaml'])
            if config and 'check' in config:
                item_dict['check_url'] = config['check'].get('url', '')
        except Exception:
            pass
        items_data.append(item_dict)

    return render_template('items/list.html', items=items_data)


@items_bp.route('/items/new', methods=['GET', 'POST'])
def item_new():
    if request.method == 'GET':
        return render_template('items/edit.html', item=None, secrets=[],
                               default_yaml=DEFAULT_YAML_TEMPLATE)
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
        secrets = db.execute(
            'SELECT key FROM pipeline_secrets WHERE watch_item_id = ? ORDER BY key',
            (item_id,)
        ).fetchall()
        secret_keys = [row['key'] for row in secrets]
        return render_template('items/edit.html', item=item, secrets=secret_keys,
                               default_yaml=DEFAULT_YAML_TEMPLATE)
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
    item_dict = dict(item)
    item_dict['check_url'] = _get_check_url(item['pipeline_yaml'])
    return render_template('partials/item_row.html', item=item_dict)


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
    check_item(dict(item))

    item = db.execute('SELECT * FROM watch_items WHERE id = ?', (item_id,)).fetchone()
    item_dict = dict(item)
    item_dict['check_url'] = _get_check_url(item['pipeline_yaml'])
    return render_template('partials/item_row.html', item=item_dict)


@items_bp.route('/items/<int:item_id>/delete', methods=['POST'])
def item_delete(item_id):
    db = get_db()
    item = db.execute(
        'SELECT * FROM watch_items WHERE id = ? AND access_code_id = ?',
        (item_id, g.user_id)
    ).fetchone()
    if not item:
        flash('Item not found.', 'error')
        return redirect(url_for('items.item_list'))

    db.execute('DELETE FROM watch_items WHERE id = ?', (item_id,))
    db.commit()
    flash('Item deleted.', 'success')
    return redirect(url_for('items.item_list'))


def _save_item(item_id):
    db = get_db()
    action = request.form.get('action', 'save')

    name = request.form.get('name', '').strip()
    pipeline_yaml = request.form.get('pipeline_yaml', '').strip()
    notification_type = request.form.get('notification_type', 'telegram')
    chat_id = request.form.get('chat_id', '').strip()
    message_template = request.form.get('message_template', '').strip()
    interval_minutes = request.form.get('interval_minutes', '5')

    # Secrets from dynamic form
    secret_keys = request.form.getlist('secret_key')
    secret_values = request.form.getlist('secret_value')

    if not name:
        flash('Name is required.', 'error')
        if item_id:
            return redirect(url_for('items.item_edit', item_id=item_id))
        return redirect(url_for('items.item_new'))

    # Validate YAML only when activating
    if action == 'activate' and pipeline_yaml:
        _, errors = validate_pipeline(pipeline_yaml)
        if errors:
            flash('Cannot activate — pipeline config errors: ' + '; '.join(errors), 'error')
            if item_id:
                return redirect(url_for('items.item_edit', item_id=item_id))
            return redirect(url_for('items.item_new'))
    elif action == 'activate' and not pipeline_yaml:
        flash('Cannot activate — pipeline config is empty.', 'error')
        if item_id:
            return redirect(url_for('items.item_edit', item_id=item_id))
        return redirect(url_for('items.item_new'))

    notification_config = json.dumps({'chat_id': chat_id})

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
            'Time: {timestamp}'
        )

    if item_id is None:
        status = 'active' if action == 'activate' else 'draft'
        cursor = db.execute(
            '''INSERT INTO watch_items
               (access_code_id, name, pipeline_yaml, notification_type, notification_config,
                message_template, status, interval_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (g.user_id, name, pipeline_yaml, notification_type, notification_config,
             message_template, status, interval_minutes)
        )
        item_id = cursor.lastrowid
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
               name=?, pipeline_yaml=?, notification_type=?, notification_config=?,
               message_template=?, status=?, interval_minutes=?,
               updated_at=datetime('now')
               WHERE id=? AND access_code_id=?''',
            (name, pipeline_yaml, notification_type, notification_config,
             message_template, status, interval_minutes,
             item_id, g.user_id)
        )

    # Save secrets
    _save_secrets(db, item_id, secret_keys, secret_values)

    db.commit()
    flash('Item saved successfully.', 'success')
    return redirect(url_for('items.item_list'))


def _save_secrets(db, item_id, keys, values):
    """Sync secrets: add new, update changed, delete removed."""
    existing = db.execute(
        'SELECT key FROM pipeline_secrets WHERE watch_item_id = ?',
        (item_id,)
    ).fetchall()
    existing_keys = {row['key'] for row in existing}

    submitted = {}
    for k, v in zip(keys, values):
        k = k.strip()
        if k:
            submitted[k] = v

    # Delete removed secrets
    for old_key in existing_keys:
        if old_key not in submitted:
            db.execute(
                'DELETE FROM pipeline_secrets WHERE watch_item_id = ? AND key = ?',
                (item_id, old_key)
            )

    # Insert or update
    for k, v in submitted.items():
        if not v or v == '••••••••':
            # Keep existing value if placeholder
            if k not in existing_keys:
                continue  # skip empty new secrets
        else:
            encrypted = encrypt_value(v)
            if k in existing_keys:
                db.execute(
                    "UPDATE pipeline_secrets SET encrypted_value = ?, updated_at = datetime('now') "
                    "WHERE watch_item_id = ? AND key = ?",
                    (encrypted, item_id, k)
                )
            else:
                db.execute(
                    'INSERT INTO pipeline_secrets (watch_item_id, key, encrypted_value) VALUES (?, ?, ?)',
                    (item_id, k, encrypted)
                )


def _get_check_url(pipeline_yaml):
    try:
        config = yaml.safe_load(pipeline_yaml)
        if config and 'check' in config:
            return config['check'].get('url', '')
    except Exception:
        pass
    return ''
