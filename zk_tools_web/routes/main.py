"""Vistas principales de la aplicación web."""
from __future__ import annotations

import logging
from typing import List, Set

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import services

bp = Blueprint("main", __name__)

logger = logging.getLogger(__name__)


@bp.route("/", methods=["GET", "POST"])
def index():
    """Página principal para administrar empleados."""
    terminal_value = request.values.get("terminal")
    parsed_ip, parsed_port = services.parse_terminal_value(terminal_value)
    fallback_ip = (request.values.get("ip", "") or "").strip() or None
    ip = parsed_ip or fallback_ip
    port = parsed_port if parsed_ip else services.coerce_port(request.values.get("port"))

    employees = []
    selected: Set[str] = set()
    terminal_status = None
    terminal_status_errors: List[str] = []
    known_terminals = services.load_known_terminals()
    known_terminal_ips = [item["ip"] for item in known_terminals]

    def redirect_with_terminal():
        terminal_param = services.format_terminal_value(ip, port)
        if terminal_param:
            return redirect(url_for("main.index", terminal=terminal_param))
        fallback_terminal = (terminal_value or "").strip()
        if fallback_terminal:
            return redirect(url_for("main.index", terminal=fallback_terminal))
        return redirect(url_for("main.index"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "import" and ip:
            try:
                imported_employees = services.parse_employee_file(request.files.get("employee_file"))
            except ValueError as exc:
                flash(str(exc))
            else:
                services.set_cached_employees(ip, imported_employees)
                services.set_selected_uids(ip, set())
                flash(
                    f"Se importaron {len(imported_employees)} empleado(s) en memoria para el terminal {ip}."
                )
            return redirect_with_terminal()
        if action == "import":
            flash("Debes indicar un terminal para importar empleados.")
            return redirect_with_terminal()
        if action == "fetch" and ip:
            try:
                employees = services.fetch_employees(ip, port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al consultar empleados del terminal %s", ip)
                flash(f"No se pudo obtener la información del terminal {ip}: {exc}")
            else:
                services.set_cached_employees(ip, employees)
                selected = services.get_selected_uids(ip)
            return redirect_with_terminal()
        if action == "select" and ip:
            selected_uids = set(request.form.getlist("selected"))
            services.set_selected_uids(ip, selected_uids)
            return redirect_with_terminal()
        if action == "status" and ip:
            try:
                terminal_status, terminal_status_errors = services.get_terminal_status(ip, port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al obtener el estado del terminal %s", ip)
                flash(f"No se pudo obtener el estado del terminal: {exc}")
                return redirect_with_terminal()
        if action == "status":
            if not ip:
                flash("Debes indicar un terminal para consultar su estado.")
                return redirect_with_terminal()
        if action == "push" and ip:
            selected_uids = set(request.form.getlist("selected"))
            if not selected_uids:
                flash("Selecciona al menos un empleado para enviar.")
                return redirect_with_terminal()

            cached_employees = services.get_cached_employees(ip)
            if not cached_employees:
                flash("No hay empleados en memoria para enviar. Carga o importa primero los empleados.")
                return redirect_with_terminal()

            selected_employees = [
                emp for emp in cached_employees if emp.get("uid") in selected_uids
            ]
            if not selected_employees:
                flash(
                    "Los empleados seleccionados no están disponibles en caché. Consulta nuevamente el terminal."
                )
                return redirect_with_terminal()

            services.set_selected_uids(ip, selected_uids)
            try:
                uploaded, errors = services.upload_employees(ip, selected_employees, port=port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al enviar empleados al terminal %s", ip)
                flash(f"No se pudieron enviar los empleados seleccionados: {exc}")
            else:
                if uploaded:
                    flash(f"Se enviaron {len(uploaded)} empleado(s) al terminal.")
                if errors:
                    for uid, message in errors:
                        flash(f"No se pudo enviar el empleado {uid}: {message}")
            return redirect_with_terminal()
        if action == "push":
            flash("Debes indicar un terminal para enviar empleados.")
            return redirect_with_terminal()
        if action == "delete" and ip:
            selected_uids = set(request.form.getlist("selected"))
            if not selected_uids:
                flash("Selecciona al menos un empleado para eliminar.")
                return redirect_with_terminal()

            cached_employees = services.get_cached_employees(ip)
            to_delete = [emp for emp in cached_employees if emp.get("uid") in selected_uids]

            if not to_delete:
                flash(
                    "Los empleados seleccionados no están disponibles en caché. Consulta nuevamente el terminal."
                )
                return redirect_with_terminal()

            try:
                deleted, errors = services.delete_employees(ip, to_delete, port=port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al eliminar empleados del terminal %s", ip)
                flash(f"No se pudieron eliminar los empleados seleccionados: {exc}")
            else:
                if deleted:
                    flash(f"Se eliminaron {len(deleted)} empleado(s) del terminal.")
                    remaining = [
                        emp for emp in cached_employees if emp.get("uid") not in deleted
                    ]
                    services.set_cached_employees(ip, remaining)
                    services.remove_selected_uids(ip, deleted)
                if errors:
                    for uid, message in errors:
                        flash(f"No se pudo eliminar el empleado {uid}: {message}")
            return redirect_with_terminal()
        if action in {"export_csv", "export_json", "export_excel"} and ip:
            selected_uids = set(request.form.getlist("selected"))
            if not selected_uids:
                flash("Selecciona al menos un empleado para exportar.")
                return redirect_with_terminal()

            cached_employees = services.get_cached_employees(ip)
            if not cached_employees:
                flash("No hay empleados en caché para exportar. Consulta primero el terminal.")
                return redirect_with_terminal()

            selected_employees = [
                emp for emp in cached_employees if emp.get("uid") in selected_uids
            ]
            if not selected_employees:
                flash(
                    "Los empleados seleccionados no están disponibles en caché. Consulta nuevamente el terminal."
                )
                return redirect_with_terminal()

            services.set_selected_uids(ip, selected_uids)
            export_format = action.split("_", 1)[1]
            try:
                return services.build_export_response(ip, selected_employees, export_format)
            except ValueError as exc:
                flash(str(exc))
                return redirect_with_terminal()
        if action == "clear":
            if ip:
                cached = services.clear_terminal_cache(ip)
                removed_count = len(cached)
                if removed_count:
                    flash(
                        f"Se limpiaron {removed_count} empleado(s) en memoria para el terminal {ip}."
                    )
                else:
                    flash("No había empleados almacenados en memoria para este terminal.")
                return redirect_with_terminal()
            services.clear_all_cache()
            flash("Se limpiaron los empleados almacenados en memoria.")
            return redirect(url_for("main.index"))

    if ip:
        employees = services.get_cached_employees(ip)
        selected = services.get_selected_uids(ip)

    employee_map = {emp["uid"]: emp for emp in employees}
    employee_uids = set(employee_map.keys())
    selected = {uid for uid in selected if uid in employee_uids}
    if ip:
        services.set_selected_uids(ip, selected)
    total_employees = len(employees)
    selected_count = len(selected)
    terminal_display = services.format_terminal_value(ip, port)
    if not terminal_display and terminal_value:
        terminal_display = terminal_value.strip()

    return render_template(
        "index.html",
        ip=ip,
        port=port,
        terminal=terminal_display,
        employees=employees,
        selected=selected,
        employee_map=employee_map,
        total_employees=total_employees,
        selected_count=selected_count,
        terminal_status=terminal_status,
        terminal_status_errors=terminal_status_errors,
        known_terminals=known_terminals,
        known_terminal_ips=known_terminal_ips,
    )
