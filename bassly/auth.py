from functools import wraps

from flask import abort, redirect, request, url_for
from flask_login import current_user, login_required

from bassly.config import UPLOAD_BACKEND
from bassly.extensions import db
from bassly.extensions import login_manager
from bassly.models import User
from bassly.utils import role_label


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def configure_login(app):
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Log eerst in om verder te gaan."

    @app.context_processor
    def inject_global_state():
        return {
            "manager_logged_in": is_admin_user(),
            "signed_in_user": current_user if current_user.is_authenticated else None,
            "role_label": role_label,
            "upload_backend": UPLOAD_BACKEND,
        }


def is_manager_logged_in():
    return is_admin_user()


def is_admin_user():
    return current_user.is_authenticated and current_user.role == "admin"


def manager_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login", next=request.path))
        if not is_admin_user():
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator
