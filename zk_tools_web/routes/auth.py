"""Blueprint para autenticación y gestión de usuarios."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import db

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.before_app_request
def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = db.get_user_by_id(user_id)


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.get("user") is None:
            next_url = request.path
            return redirect(url_for("auth.login", next=next_url))
        return view(**kwargs)

    return wrapped_view


def admin_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped_view(**kwargs):
        user = g.get("user")
        if user is None:
            return redirect(url_for("auth.login", next=request.path))
        if not user.get("is_admin"):
            flash("No tienes permisos para realizar esta acción.")
            return redirect(url_for("main.index"))
        return view(**kwargs)

    return wrapped_view


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user") is not None:
        return redirect(url_for("main.index"))

    error: Optional[str] = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            error = "Introduce usuario y contraseña."
        else:
            user = db.authenticate_user(username, password)
            if user is None:
                error = "Credenciales inválidas."
            else:
                session.clear()
                session["user_id"] = user["id"]
                flash("Sesión iniciada correctamente.")
                next_url = request.args.get("next")
                if next_url and next_url.startswith("/"):
                    return redirect(next_url)
                return redirect(url_for("main.index"))

        if error:
            flash(error)

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Sesión cerrada.")
    return redirect(url_for("auth.login"))


@bp.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def manage_users():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                password_confirm = request.form.get("password_confirm") or ""
                is_admin = bool(request.form.get("is_admin"))
                if not username or not password:
                    raise ValueError("El usuario y la contraseña son obligatorios.")
                if password != password_confirm:
                    raise ValueError("Las contraseñas no coinciden.")
                db.create_user(username, password, is_admin)
                flash("Usuario creado correctamente.")
            elif action == "update":
                user_id = int(request.form.get("user_id") or 0)
                is_admin = bool(request.form.get("is_admin"))
                password = request.form.get("password") or None
                password_confirm = request.form.get("password_confirm") or None
                if password and password != password_confirm:
                    raise ValueError("Las contraseñas no coinciden.")
                db.update_user(user_id, password=password if password else None, is_admin=is_admin)
                flash("Usuario actualizado.")
            elif action == "delete":
                user_id = int(request.form.get("user_id") or 0)
                if g.user and g.user["id"] == user_id:
                    raise ValueError("No puedes eliminar tu propio usuario.")
                db.delete_user(user_id)
                flash("Usuario eliminado.")
            else:
                flash("Acción no reconocida.")
        except ValueError as exc:
            flash(str(exc))
        except Exception as exc:  # pragma: no cover
            flash(f"Se produjo un error inesperado: {exc}")

        return redirect(url_for("auth.manage_users"))

    users = db.list_users()
    return render_template("users.html", users=users)


__all__ = ["bp", "login_required", "admin_required"]
