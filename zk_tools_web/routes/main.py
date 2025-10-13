"""Vistas principales de la aplicación web."""
from __future__ import annotations

import logging
from typing import Dict, List, Set

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .. import services
from .auth import login_required

bp = Blueprint("main", __name__)

logger = logging.getLogger(__name__)


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Página principal para administrar empleados."""
    terminal_value_raw = request.values.get("terminal")
    terminal_value = (terminal_value_raw or "").strip()
    special_terminal_value = services.normalize_special_terminal_value(terminal_value)
    is_special_selection = special_terminal_value is not None
    is_database_selection = special_terminal_value == services.DATABASE_TERMINAL_KEY
    is_zktime_selection = special_terminal_value == services.ZKTIME_TERMINAL_KEY

    if is_special_selection:
        parsed_ip, parsed_port = (None, services.DEFAULT_PORT)
    else:
        parsed_ip, parsed_port = services.parse_terminal_value(terminal_value)

    fallback_ip = (request.values.get("ip", "") or "").strip() or None
    ip = None if is_special_selection else parsed_ip or fallback_ip
    if is_special_selection:
        port = services.DEFAULT_PORT
    else:
        port = parsed_port if parsed_ip else services.coerce_port(request.values.get("port"))

    cache_key = special_terminal_value if is_special_selection else ip

    employees: List[dict] = []
    selected: Set[str] = set()
    override_employees: List[dict] | None = None
    terminal_status = None
    terminal_status_errors: List[str] = []
    known_terminals = services.load_known_terminals()
    known_terminal_ips = [item["ip"] for item in known_terminals]
    expand_details_values = [
        (value or "").lower() for value in request.values.getlist("expand_details") if value is not None
    ]
    if not expand_details_values:
        expand_details = True
    else:
        truthy_values = {"1", "true", "on"}
        falsy_values = {"0", "false", "off"}
        if any(value in truthy_values for value in expand_details_values):
            expand_details = True
        elif any(value in falsy_values for value in expand_details_values):
            expand_details = False
        else:
            expand_details = True

    def redirect_with_terminal():
        redirect_params = {}
        if is_special_selection and special_terminal_value:
            redirect_params["terminal"] = special_terminal_value
        else:
            terminal_param = services.format_terminal_value(ip, port)
            if terminal_param:
                redirect_params["terminal"] = terminal_param
            fallback_terminal = terminal_value
            if fallback_terminal:
                redirect_params.setdefault("terminal", fallback_terminal)
        redirect_params["expand_details"] = "1" if expand_details else "0"
        return redirect(url_for("main.index", **redirect_params))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "import" and cache_key and not is_special_selection:
            try:
                imported_employees = services.parse_employee_file(request.files.get("employee_file"))
            except ValueError as exc:
                flash(str(exc))
            else:
                services.set_cached_employees(cache_key, imported_employees)
                services.set_selected_uids(cache_key, set())
                flash(
                    f"Se importaron {len(imported_employees)} empleado(s) en memoria para el terminal {ip}."
                )
            return redirect_with_terminal()
        if action == "import":
            flash("Debes indicar un terminal para importar empleados.")
            return redirect_with_terminal()
        if action == "fetch" and is_special_selection:
            source_label = services.get_special_terminal_label(special_terminal_value) or "la fuente seleccionada"
            try:
                if is_database_selection:
                    employees = services.refresh_database_cache()
                elif is_zktime_selection:
                    employees = services.refresh_zktime_cache()
                else:
                    raise RuntimeError("El origen seleccionado no está soportado.")
            except Exception as exc:
                logger.exception(
                    "Error al refrescar la caché de empleados para %s: %s",
                    special_terminal_value,
                    exc,
                )
                flash(f"No se pudo actualizar la relación de {source_label}: {exc}")
            else:
                flash(f"Se cargaron {len(employees)} empleado(s) desde {source_label}.")
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
        if action == "fetch":
            flash("Debes indicar un terminal para cargar empleados.")
            return redirect_with_terminal()
        if action == "select" and cache_key:
            selected_uids = set(request.form.getlist("selected"))
            services.set_selected_uids(cache_key, selected_uids)
            return redirect_with_terminal()
        if action == "status" and is_special_selection:
            flash("Esta opción no dispone de estado de terminal.")
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
        if action == "sync_time" and ip:
            try:
                services.sync_terminal_time(ip, port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al sincronizar la hora del terminal %s", ip)
                flash(f"No se pudo sincronizar la fecha y hora: {exc}")
            else:
                flash("Fecha y hora sincronizadas con éxito.")
            return redirect_with_terminal()
        if action == "sync_time":
            flash("Debes indicar un terminal para actualizar la hora.")
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
        if action in {"export_csv", "export_json", "export_excel"} and cache_key:
            selected_uids = set(request.form.getlist("selected"))
            if not selected_uids:
                flash("Selecciona al menos un empleado para exportar.")
                return redirect_with_terminal()

            cached_employees = services.get_cached_employees(cache_key)
            if not cached_employees:
                flash("No hay empleados en caché para exportar. Consulta primero la fuente de empleados.")
                return redirect_with_terminal()

            selected_employees = [
                emp for emp in cached_employees if emp.get("uid") in selected_uids
            ]
            if not selected_employees:
                flash(
                    "Los empleados seleccionados no están disponibles en caché. Consulta nuevamente el terminal."
                )
                return redirect_with_terminal()

            services.set_selected_uids(cache_key, selected_uids)
            export_format = action.split("_", 1)[1]
            source_label = services.get_special_terminal_label(cache_key)
            export_host = (
                source_label.replace(" ", "_")
                if source_label
                else (ip or services.DATABASE_TERMINAL_LABEL.replace(" ", "_"))
            )
            try:
                return services.build_export_response(export_host, selected_employees, export_format)
            except ValueError as exc:
                flash(str(exc))
                return redirect_with_terminal()
        if action == "clear":
            if cache_key:
                cached = services.clear_terminal_cache(cache_key)
                removed_count = len(cached)
                if removed_count:
                    if is_special_selection:
                        flash(
                            f"Se limpiaron {removed_count} empleado(s) en memoria."
                        )
                    else:
                        flash(
                            f"Se limpiaron {removed_count} empleado(s) del terminal {ip} en memoria."
                        )
                else:
                    if is_special_selection:
                        flash("No había empleados almacenados en memoria.")
                    else:
                        flash("No había empleados almacenados en memoria para este terminal.")
                return redirect_with_terminal()
            services.clear_all_cache()
            flash("Se limpiaron los empleados almacenados en memoria.")
            return redirect(url_for("main.index"))
        if action == "duplicates":
            if not cache_key:
                flash("Debes indicar una fuente de empleados para buscar duplicados.")
                return redirect_with_terminal()
            cached_employees = services.get_cached_employees(cache_key)
            if not cached_employees:
                flash("No hay empleados en memoria. Consulta primero la fuente seleccionada.")
                return redirect_with_terminal()
            duplicate_employees = services.find_duplicate_employees(cached_employees)
            if duplicate_employees:
                flash(
                    f"Se encontraron {len(duplicate_employees)} empleado(s) con el mismo nombre y distinto User ID."
                )
            else:
                flash("No se encontraron empleados duplicados por nombre con distinto User ID.")
            override_employees = duplicate_employees
        if action == "update_cards_zktime":
            if not cache_key:
                flash("Debes indicar una fuente de empleados para actualizar las tarjetas.")
                return redirect_with_terminal()
            cached_employees = services.get_cached_employees(cache_key)
            if not cached_employees:
                flash("No hay empleados en memoria. Consulta primero la fuente seleccionada.")
                return redirect_with_terminal()
            try:
                updated_count, attempted, update_entries = services.update_zktime_cards(cached_employees)
            except Exception as exc:
                logger.exception("Error al actualizar tarjetas en ZK Time: %s", exc)
                flash(f"No se pudieron actualizar las tarjetas en ZK Time: {exc}")
            else:
                log_entries = []
                for code, card in update_entries:
                    status = "success" if updated_count else "info"
                    if status == "success":
                        text = f"Al empleado {code} se ha actualizado la tarjeta {card}."
                    else:
                        text = f"Se solicitó actualizar la tarjeta {card} del empleado {code}."
                    log_entries.append({"status": status, "text": text})
                if updated_count:
                    summary = f"Se actualizaron {updated_count} tarjeta(s) en ZK Time."
                    flash(summary)
                elif attempted:
                    summary = "Se encontraron tarjetas para actualizar, pero no se modificó ningún registro en ZK Time."
                    flash(summary)
                else:
                    summary = "No hay tarjetas disponibles para actualizar."
                    flash(summary)
                if not log_entries:
                    log_entries.append(
                        {
                            "status": "info",
                            "text": "No se encontraron tarjetas para actualizar.",
                        }
                    )
                session["update_log"] = {
                    "title": "Actualización de tarjetas en ZKTime",
                    "summary": summary,
                    "entries": log_entries,
                }
            return redirect_with_terminal()
        if action == "update_cards_rrhh":
            if not cache_key:
                flash("Debes indicar una fuente de empleados para actualizar las tarjetas.")
                return redirect_with_terminal()
            cached_employees = services.get_cached_employees(cache_key)
            if not cached_employees:
                flash("No hay empleados en memoria. Consulta primero la fuente seleccionada.")
                return redirect_with_terminal()
            try:
                updated_count, attempted, success_entries, errors = services.update_rrhh_cards(cached_employees)
            except Exception as exc:  # pragma: no cover - dependiente del servicio externo
                logger.exception("Error al actualizar tarjetas en RRHH: %s", exc)
                flash(f"No se pudieron actualizar las tarjetas en RRHH: {exc}")
            else:
                log_entries = [
                    {
                        "status": "success",
                        "text": f"Al empleado {code} se ha registrado la tarjeta {card}.",
                    }
                    for code, card in success_entries
                ]
                if updated_count:
                    summary = f"Se registraron {updated_count} tarjeta(s) en RRHH."
                    flash(summary)
                elif attempted == 0:
                    summary = "No hay tarjetas disponibles para registrar en RRHH."
                    flash(summary)
                else:
                    summary = "No se pudo registrar ninguna tarjeta en RRHH."
                    flash(summary)
                for code, message in errors:
                    flash(f"No se pudo registrar la tarjeta del empleado {code}: {message}")
                    log_entries.append(
                        {
                            "status": "error",
                            "text": f"No se registró la tarjeta del empleado {code}: {message}",
                        }
                    )
                if not log_entries:
                    log_entries.append(
                        {
                            "status": "info",
                            "text": "No se registró ninguna tarjeta.",
                        }
                    )
                session["update_log"] = {
                    "title": "Registro de tarjetas en RRHH",
                    "summary": summary,
                    "entries": log_entries,
                }
            return redirect_with_terminal()

    if override_employees is not None:
        employees = override_employees
        if cache_key:
            selected = services.get_selected_uids(cache_key)
    elif cache_key:
        employees = services.get_cached_employees(cache_key)
        selected = services.get_selected_uids(cache_key)

    employee_map = {emp["uid"]: emp for emp in employees}
    employee_uids = set(employee_map.keys())
    selected = {uid for uid in selected if uid in employee_uids}
    if cache_key:
        services.set_selected_uids(cache_key, selected)
    total_employees = len(employees)
    selected_count = len(selected)
    terminal_display = services.format_terminal_value(ip, port) if ip else ""
    if is_special_selection:
        terminal_display = services.get_special_terminal_label(special_terminal_value) or terminal_display
    elif not terminal_display and terminal_value:
        terminal_display = terminal_value.strip()
    cached_employee_count = len(services.get_cached_employees(cache_key)) if cache_key else 0
    external_employee_details: Dict[str, dict] = {}
    resolved_external_employee_details: Dict[str, dict] = {}
    employee_last_seen: Dict[str, str] = {}

    if employees:
        try:
            user_lookup_map = services.get_external_employee_map()
        except Exception as exc:  # pragma: no cover - dependiente del servicio externo
            logger.exception("No se pudo obtener la información externa de empleados: %s", exc)
        else:
            for employee in employees:
                user_id_value = employee.get("user_id")
                details = services.lookup_external_employee(user_id_value, user_lookup_map)
                last_seen_value = None
                if details:
                    center_value = details.get("cod_ct")
                    if center_value:
                        employee["center"] = center_value
                    contract_from_value = details.get("contract_from")
                    if contract_from_value:
                        employee["contract_from"] = contract_from_value
                    medical_leave_value = details.get("medical_leave_from")
                    if medical_leave_value:
                        employee["medical_leave_from"] = medical_leave_value
                    vacation_status_value = details.get("vacation_status")
                    if vacation_status_value is not None:
                        employee["vacation_status"] = vacation_status_value
                    dni_value = details.get("dni")
                    if dni_value and not employee.get("dni"):
                        employee["dni"] = dni_value
                    last_seen_value = details.get("last_seen")
                if not last_seen_value:
                    last_seen_value = employee.get("last_seen")
                if last_seen_value:
                    formatted_last_seen = services.format_relative_time(last_seen_value)
                    employee_last_seen[str(employee.get("uid"))] = formatted_last_seen

    if expand_details:
        try:
            external_employee_details = services.get_external_employee_map_by_dni()
        except Exception as exc:  # pragma: no cover - dependiente del servicio externo
            logger.exception("No se pudo ampliar la información de empleados: %s", exc)
            flash("No se pudo obtener la información ampliada de empleados.")
            expand_details = False
        else:
            for employee in employees:
                candidate_identifier = employee.get("dni") or employee.get("name")
                details = services.lookup_external_employee(candidate_identifier, external_employee_details)
                if details:
                    resolved_external_employee_details[str(employee.get("uid"))] = details
                    center_value = details.get("cod_ct")
                    if center_value and not employee.get("center"):
                        employee["center"] = center_value
                    contract_from_value = details.get("contract_from")
                    if contract_from_value and not employee.get("contract_from"):
                        employee["contract_from"] = contract_from_value
                    medical_leave_value = details.get("medical_leave_from")
                    if medical_leave_value and not employee.get("medical_leave_from"):
                        employee["medical_leave_from"] = medical_leave_value
                    vacation_status_value = details.get("vacation_status")
                    if vacation_status_value is not None and not employee.get("vacation_status"):
                        employee["vacation_status"] = vacation_status_value

    for employee in employees:
        if not employee.get("center"):
            employee["center"] = employee.get("group_id")
        employee["contract_from_display"] = services.format_contract_date(employee.get("contract_from"))
        employee["medical_leave_from_display"] = services.format_contract_date(
            employee.get("medical_leave_from")
        )
        employee["vacation_status_display"] = str(employee.get("vacation_status") or "").strip()

    terminal_param_value = terminal_value or services.format_terminal_value(ip, port) or ""
    show_custom_terminal_input = (
        bool(terminal_param_value)
        and terminal_param_value not in known_terminal_ips
        and services.normalize_special_terminal_value(terminal_param_value) is None
    )

    update_log = session.pop("update_log", None)

    return render_template(
        "index.html",
        ip=ip,
        port=port,
        terminal=terminal_param_value,
        terminal_display_name=terminal_display,
        employees=employees,
        selected=selected,
        employee_map=employee_map,
        total_employees=total_employees,
        selected_count=selected_count,
        terminal_status=terminal_status,
        terminal_status_errors=terminal_status_errors,
        known_terminals=known_terminals,
        known_terminal_ips=known_terminal_ips,
        showing_duplicates=override_employees is not None,
        cached_employee_count=cached_employee_count,
        expand_details=expand_details,
        external_employee_details=external_employee_details,
        resolved_external_employee_details=resolved_external_employee_details,
        employee_last_seen=employee_last_seen,
        database_mode=is_special_selection,
        zktime_mode=is_zktime_selection,
        database_terminal_value=services.DATABASE_TERMINAL_KEY,
        database_terminal_label=services.DATABASE_TERMINAL_LABEL,
        zktime_terminal_value=services.ZKTIME_TERMINAL_KEY,
        zktime_terminal_label=services.ZKTIME_TERMINAL_LABEL,
        special_terminal_value=special_terminal_value,
        special_terminal_options=services.get_special_terminal_options(),
        show_custom_terminal_input=show_custom_terminal_input,
        update_log=update_log,
    )
