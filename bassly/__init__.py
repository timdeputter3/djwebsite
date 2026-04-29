import os

from flask import Flask

import bassly.models  # noqa: F401
from bassly.auth import configure_login
from bassly.config import BASE_DIR, get_database_uri
from bassly.extensions import db
from bassly.routes import register_routes
from bassly.services.database import bootstrap_database


def create_app():
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "bassly-dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024

    db.init_app(app)
    configure_login(app)
    register_routes(app)

    with app.app_context():
        bootstrap_database()

    return app
