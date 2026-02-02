from datetime import datetime, timedelta

from flask import g, redirect, request, url_for

from config import Config
from db import get_db


def register_middleware(app):
    @app.before_request
    def before_request():
        # Skip auth check for login, static files, and favicon
        if request.endpoint and (
            request.endpoint.startswith('auth.')
            or request.endpoint == 'static'
        ):
            return

        token = request.cookies.get(Config.SESSION_COOKIE_NAME)
        if not token:
            return redirect(url_for('auth.login'))

        db = get_db()
        session = db.execute(
            'SELECT * FROM sessions WHERE token = ?', (token,)
        ).fetchone()

        if not session:
            resp = redirect(url_for('auth.login'))
            resp.delete_cookie(Config.SESSION_COOKIE_NAME)
            return resp

        # Check if session expired
        last_activity = datetime.fromisoformat(session['last_activity_at'])
        if datetime.utcnow() - last_activity > timedelta(days=Config.SESSION_MAX_AGE_DAYS):
            db.execute('DELETE FROM sessions WHERE id = ?', (session['id'],))
            db.commit()
            resp = redirect(url_for('auth.login'))
            resp.delete_cookie(Config.SESSION_COOKIE_NAME)
            return resp

        # Update last activity
        db.execute(
            'UPDATE sessions SET last_activity_at = datetime(\'now\') WHERE id = ?',
            (session['id'],)
        )
        db.commit()

        g.user_id = session['access_code_id']
        g.session_id = session['id']
