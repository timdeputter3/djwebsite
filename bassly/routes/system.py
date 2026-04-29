from flask import current_app
from sqlalchemy import text

from bassly.extensions import db
from bassly.utils import current_database_label, database_uri_present


def register_system_routes(app):
    @app.route("/health/db")
    def health_db():
        try:
            db.session.execute(text("SELECT 1"))
            status = "ok"
        except Exception as exc:
            status = "error"
            return {
                "status": status,
                "database_engine": current_database_label(current_app),
                "database_uri_present": database_uri_present(),
                "message": str(exc),
            }, 500

        return {
            "status": status,
            "database_engine": current_database_label(current_app),
            "database_uri_present": database_uri_present(),
        }
