import hashlib
import uuid

from flask import (
    Blueprint, flash, g, make_response, redirect, render_template,
    request, url_for
)

from config import Config
from db import get_db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    code = request.form.get('code', '').strip()
    ip = request.remote_addr or 'unknown'
    db = get_db()

    # Brute-force check
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM login_logs "
        "WHERE ip_address = ? AND success = 0 "
        "AND created_at > datetime('now', ?)",
        (ip, f'-{Config.BRUTE_FORCE_WINDOW_MINUTES} minutes')
    ).fetchone()

    if row['cnt'] >= Config.BRUTE_FORCE_MAX_ATTEMPTS:
        flash('Too many failed attempts. Please try again later.', 'error')
        return render_template('login.html'), 429

    code_hash = hashlib.sha256(code.encode()).hexdigest()
    ac = db.execute(
        'SELECT * FROM access_codes WHERE code_hash = ? AND is_active = 1',
        (code_hash,)
    ).fetchone()

    if not ac:
        db.execute(
            'INSERT INTO login_logs (ip_address, success) VALUES (?, 0)',
            (ip,)
        )
        db.commit()
        flash('Invalid access code.', 'error')
        return render_template('login.html'), 401

    # Success
    db.execute(
        'INSERT INTO login_logs (ip_address, success, access_code_id) VALUES (?, 1, ?)',
        (ip, ac['id'])
    )
    token = uuid.uuid4().hex
    db.execute(
        'INSERT INTO sessions (token, access_code_id, ip_address) VALUES (?, ?, ?)',
        (token, ac['id'], ip)
    )
    db.commit()

    resp = make_response(redirect(url_for('items.item_list')))
    resp.set_cookie(
        Config.SESSION_COOKIE_NAME,
        token,
        max_age=Config.SESSION_MAX_AGE_DAYS * 86400,
        httponly=True,
        samesite='Lax'
    )
    return resp


@auth_bp.route('/logout')
def logout():
    token = request.cookies.get(Config.SESSION_COOKIE_NAME)
    if token:
        db = get_db()
        db.execute('DELETE FROM sessions WHERE token = ?', (token,))
        db.commit()
    resp = make_response(redirect(url_for('auth.login')))
    resp.delete_cookie(Config.SESSION_COOKIE_NAME)
    return resp
