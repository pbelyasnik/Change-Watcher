import json
import os

from flask import Flask

from config import Config
from db import close_db, init_db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['DATABASE_PATH'] = Config.DATABASE_PATH

    app.jinja_env.filters['parse_json'] = lambda s: json.loads(s) if s else {}

    app.teardown_appcontext(close_db)

    from middleware import register_middleware
    register_middleware(app)

    from routes.auth import auth_bp
    from routes.items import items_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(api_bp)

    from routes.errors import register_error_handlers
    register_error_handlers(app)

    init_db(app)

    return app


def start_scheduler(app):
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from services.scheduler import init_scheduler
        init_scheduler(app)


if __name__ == '__main__':
    app = create_app()
    start_scheduler(app)
    app.run(host='0.0.0.0', port=5000, debug=True)
