"""Punto de entrada para ejecutar la aplicación web."""
from __future__ import annotations

from zk_tools_web import app, create_app

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
