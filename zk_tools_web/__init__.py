"""Inicialización de la aplicación Flask de zk-tools."""
from __future__ import annotations

from flask import Flask


def create_app() -> Flask:
    """Crea y configura la aplicación Flask."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "zk-tools-dev"

    from .routes.main import bp as main_bp

    app.register_blueprint(main_bp)
    return app


app = create_app()

__all__ = ["app", "create_app"]
