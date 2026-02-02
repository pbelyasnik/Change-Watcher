#!/usr/bin/env python3
import hashlib
import sys

from app import create_app
from db import get_db, init_db


def print_usage():
    print("Usage:")
    print("  python manage.py init-db              Initialize the database")
    print("  python manage.py add-code <code>       Add an access code")
    print("  python manage.py cleanup               Delete old logs and expired sessions")


def cmd_init_db():
    app = create_app()
    init_db(app)
    print("Database initialized.")


def cmd_add_code(code):
    app = create_app()
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    with app.app_context():
        db = get_db()
        try:
            db.execute(
                'INSERT INTO access_codes (code_hash, label) VALUES (?, ?)',
                (code_hash, f'code-{code[:4]}...')
            )
            db.commit()
            print(f"Access code added successfully.")
        except Exception as e:
            print(f"Error adding code: {e}")
            sys.exit(1)


def cmd_cleanup():
    app = create_app()
    with app.app_context():
        db = get_db()
        cur = db.execute(
            "DELETE FROM request_logs WHERE executed_at < datetime('now', '-30 days')"
        )
        print(f"Deleted {cur.rowcount} old request logs.")
        cur = db.execute(
            "DELETE FROM login_logs WHERE created_at < datetime('now', '-30 days')"
        )
        print(f"Deleted {cur.rowcount} old login logs.")
        cur = db.execute(
            "DELETE FROM sessions WHERE last_activity_at < datetime('now', '-7 days')"
        )
        print(f"Deleted {cur.rowcount} expired sessions.")
        db.commit()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]

    if command == 'init-db':
        cmd_init_db()
    elif command == 'add-code':
        if len(sys.argv) < 3:
            print("Error: access code required")
            print("Usage: python manage.py add-code <code>")
            sys.exit(1)
        cmd_add_code(sys.argv[2])
    elif command == 'cleanup':
        cmd_cleanup()
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)
