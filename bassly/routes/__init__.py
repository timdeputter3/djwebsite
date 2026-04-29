from bassly.routes.manager import register_manager_routes
from bassly.routes.public import register_public_routes
from bassly.routes.system import register_system_routes


def register_routes(app):
    register_public_routes(app)
    register_system_routes(app)
    register_manager_routes(app)
