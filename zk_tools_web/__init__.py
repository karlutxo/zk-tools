"""Inicialización de la aplicación Flask de zk-tools."""
from __future__ import annotations

from flask import Flask, g

from . import db

def create_app() -> Flask:
    """Crea y configura la aplicación Flask."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "zk-tools-dev"

    db.init_app(app)

    from .routes.auth import bp as auth_bp
    from .routes.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_user():
        return {"current_user": g.get("user")}

    return app


app = create_app()

__all__ = ["app", "create_app"]
