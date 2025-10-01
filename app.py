"""Aplicación Flask para consultar y seleccionar empleados de terminales ZKTeco."""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from io import BytesIO, StringIO
from typing import Dict, List, Sequence, Set, Tuple

from flask import (
    Flask,
    flash,
    make_response,
    redirect,
    render_template_string,
    request,
    send_file,
    url_for,
)
from openpyxl import Workbook

from zk_tools import DEFAULT_PORT, connect_with_retries

app = Flask(__name__)
app.secret_key = "zk-tools-dev"

# Almacenamiento en memoria de los empleados descubiertos por terminal
_TERMINAL_EMPLOYEES: Dict[str, List[dict]] = {}
# Almacenamiento en memoria de los UID seleccionados por terminal
_SELECTED_EMPLOYEES: Dict[str, Set[str]] = {}

EXPORT_COLUMNS: Sequence[Tuple[str, str]] = (
    ("uid", "UID"),
    ("name", "Nombre"),
    ("user_id", "User ID"),
    ("card", "Tarjeta"),
    ("privilege", "Privilegio"),
    ("group_id", "Grupo"),
    ("biometrics", "Biometría"),
)

logger = logging.getLogger(__name__)


def fetch_employees(host: str, port: int = DEFAULT_PORT) -> List[dict]:
    """Obtiene los empleados del terminal incluyendo datos biométricos."""
    zk = conn = None
    try:
        zk, conn = connect_with_retries(host, port)
        users = conn.get_users()
        try:
            templates = conn.get_templates()
        except Exception as exc:  # pragma: no cover - depende del terminal
            logger.warning("No fue posible obtener plantillas biométricas: %s", exc)
            templates = []

        template_index: Dict[int, List[dict]] = {}
        for template in templates or []:
            uid = getattr(template, "uid", None)
            if uid is None:
                continue
            template_index.setdefault(uid, []).append(
                {
                    "fid": getattr(template, "fid", ""),
                    "type": getattr(template, "type", ""),
                    "valid": getattr(template, "valid", ""),
                    "size": len(getattr(template, "template", b"")) if hasattr(template, "template") else None,
                }
            )

        employees: List[dict] = []
        for user in users:
            uid = getattr(user, "uid", "")
            employees.append(
                {
                    "uid": str(uid),
                    "name": getattr(user, "name", ""),
                    "user_id": getattr(user, "user_id", ""),
                    "card": getattr(user, "card", ""),
                    "privilege": getattr(user, "privilege", ""),
                    "group_id": getattr(user, "group_id", ""),
                    "biometrics": template_index.get(uid, []),
                }
            )
        return employees
    finally:
        try:
            if conn:
                conn.disconnect()
        except Exception:  # pragma: no cover - errores de red
            logger.exception("Error al desconectar del terminal %s", host)


def delete_employees(
    host: str,
    employees: List[dict],
    port: int = DEFAULT_PORT,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Elimina empleados del terminal y devuelve listas de eliminados y errores."""
    zk = conn = None
    deleted: List[str] = []
    errors: List[Tuple[str, str]] = []
    try:
        zk, conn = connect_with_retries(host, port)
        for employee in employees:
            uid_str = employee.get("uid", "")
            kwargs = {}
            try:
                uid_value = int(uid_str)
            except (TypeError, ValueError):
                uid_value = None

            if uid_value is not None:
                kwargs["uid"] = uid_value

            user_id = (employee.get("user_id") or "").strip()
            if user_id:
                kwargs["user_id"] = user_id

            if not kwargs:
                errors.append((str(uid_str), "El registro no tiene identificadores válidos"))
                continue

            try:
                conn.delete_user(**kwargs)
            except Exception as exc:  # pragma: no cover - depende del terminal
                errors.append((str(uid_str), str(exc)))
            else:
                deleted.append(str(uid_str))
    finally:
        try:
            if conn:
                conn.disconnect()
        except Exception:  # pragma: no cover - errores de red
            logger.exception("Error al desconectar del terminal %s", host)

    return deleted, errors


def _stringify_export_value(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def build_export_response(host: str, employees: List[dict], export_format: str):
    """Genera un archivo de exportación para los empleados seleccionados."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_host = host.replace(":", "-")
    base_filename = f"empleados_{safe_host}_{timestamp}"

    if export_format == "json":
        payload = json.dumps(employees, ensure_ascii=False, indent=2)
        response = make_response(payload)
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.headers["Content-Disposition"] = (
            f"attachment; filename={base_filename}.json"
        )
        return response

    if export_format == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([header for _, header in EXPORT_COLUMNS])
        for employee in employees:
            row = [_stringify_export_value(employee.get(key)) for key, _ in EXPORT_COLUMNS]
            writer.writerow(row)
        csv_data = output.getvalue()
        response = make_response(csv_data)
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = (
            f"attachment; filename={base_filename}.csv"
        )
        return response

    if export_format == "excel":
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Empleados"
        worksheet.append([header for _, header in EXPORT_COLUMNS])
        for employee in employees:
            row = [_stringify_export_value(employee.get(key)) for key, _ in EXPORT_COLUMNS]
            worksheet.append(row)
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{base_filename}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    raise ValueError("Formato de exportación no soportado.")


INDEX_TEMPLATE = """
<!doctype html>
<html lang=\"es\">
<head>
    <meta charset=\"utf-8\">
    <title>Empleados del terminal</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 2rem; }
        form { margin-bottom: 2rem; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; }
        th { background-color: #f2f2f2; }
        .actions { margin-top: 1rem; }
        .selected { background-color: #e6f7ff; }
        .biometric-list { margin: 0; padding-left: 1rem; }
        .messages { color: #c0392b; }
        .table-controls { display: flex; align-items: center; gap: 1rem; margin-bottom: 0.75rem; }
        .hidden { display: none; }
    </style>
</head>
<body>
    <h1>Consulta de empleados</h1>
    {% with messages = get_flashed_messages() %}
        {% if messages %}
            <ul class=\"messages\">
                {% for message in messages %}
                <li>{{ message }}</li>
                {% endfor %}
            </ul>
        {% endif %}
    {% endwith %}

    <form method=\"post\" action=\"{{ url_for('index') }}\">
        <input type=\"hidden\" name=\"action\" value=\"fetch\">
        <label for=\"ip\">Dirección IP del terminal:</label>
        <input type=\"text\" name=\"ip\" id=\"ip\" value=\"{{ ip or '' }}\" required>
        <label for=\"port\">Puerto:</label>
        <input type=\"number\" name=\"port\" id=\"port\" value=\"{{ port }}\" min=1 max=65535>
        <button type=\"submit\">Consultar empleados</button>
    </form>

    {% if employees %}
    <form method=\"post\" action=\"{{ url_for('index') }}\">
        <input type=\"hidden\" name=\"ip\" value=\"{{ ip }}\">
        <input type=\"hidden\" name=\"port\" value=\"{{ port }}\">
        <div class=\"table-controls\">
            <label>
                <input type=\"checkbox\" id=\"select-all\">
                Seleccionar todo
            </label>
            <label for=\"filter\">Filtrar:</label>
            <input type=\"search\" id=\"filter\" placeholder=\"Escribe para filtrar por UID, nombre, tarjeta...\">
        </div>
        <table id=\"employees-table\">
            <thead>
                <tr>
                    <th>Seleccionar</th>
                    <th>UID</th>
                    <th>Nombre</th>
                    <th>User ID</th>
                    <th>Tarjeta</th>
                    <th>Privilegio</th>
                    <th>Grupo</th>
                    <th>Biometría</th>
                </tr>
            </thead>
            <tbody>
                {% for employee in employees %}
                <tr class=\"{% if employee.uid in selected %}selected{% endif %}\" data-search=\"{{ (
                    (employee.uid or '') ~ ' ' ~
                    (employee.name or '') ~ ' ' ~
                    (employee.user_id or '') ~ ' ' ~
                    (employee.card or '')
                )|lower }}\">
                    <td>
                        <input type=\"checkbox\" name=\"selected\" value=\"{{ employee.uid }}\" {% if employee.uid in selected %}checked{% endif %}>
                    </td>
                    <td>{{ employee.uid }}</td>
                    <td>{{ employee.name }}</td>
                    <td>{{ employee.user_id }}</td>
                    <td>{{ employee.card }}</td>
                    <td>{{ employee.privilege }}</td>
                    <td>{{ employee.group_id }}</td>
                    <td>
                        {% if employee.biometrics %}
                        <ul class=\"biometric-list\">
                            {% for bio in employee.biometrics %}
                            <li>FID {{ bio.fid }}, Tipo {{ bio.type }}, Tamaño {{ bio.size or 'N/D' }}, Válido {{ bio.valid }}</li>
                            {% endfor %}
                        </ul>
                        {% else %}
                        Sin datos
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <div class=\"actions\">
            <button type=\"submit\" name=\"action\" value=\"select\">Guardar selección</button>
            <button type=\"submit\" name=\"action\" value=\"delete\" onclick=\"return confirm('¿Eliminar empleados seleccionados del terminal?');\">Eliminar seleccionados</button>
        </div>
        <div class=\"actions\">
            <span>Exportar selección:</span>
            <button type=\"submit\" name=\"action\" value=\"export_csv\">CSV</button>
            <button type=\"submit\" name=\"action\" value=\"export_json\">JSON</button>
            <button type=\"submit\" name=\"action\" value=\"export_excel\">Excel</button>
        </div>
    </form>
    {% elif ip %}
        <p>No se encontraron empleados para el terminal {{ ip }}.</p>
    {% endif %}

    {% if selected and employees %}
        <h2>Empleados seleccionados</h2>
        <ul>
            {% for uid in selected %}
                {% set emp = employee_map.get(uid) %}
                <li>{{ uid }} - {{ emp.name if emp else 'Empleado desconocido' }}</li>
            {% endfor %}
        </ul>
    {% endif %}
    <script>
        document.addEventListener('DOMContentLoaded', function () {
            const selectAll = document.getElementById('select-all');
            const filterInput = document.getElementById('filter');
            const table = document.getElementById('employees-table');
            if (!table) {
                return;
            }

            const checkboxes = Array.from(table.querySelectorAll('tbody input[type="checkbox"]'));
            const rows = Array.from(table.querySelectorAll('tbody tr'));

            if (selectAll) {
                if (checkboxes.length && checkboxes.every(item => item.checked)) {
                    selectAll.checked = true;
                }

                selectAll.addEventListener('change', function () {
                    checkboxes.forEach(cb => {
                        cb.checked = selectAll.checked;
                    });
                });

                checkboxes.forEach(cb => {
                    cb.addEventListener('change', function () {
                        if (!this.checked) {
                            selectAll.checked = false;
                        } else if (checkboxes.every(item => item.checked)) {
                            selectAll.checked = true;
                        }
                    });
                });
            }

            if (filterInput) {
                filterInput.addEventListener('input', function () {
                    const query = this.value.trim().toLowerCase();
                    rows.forEach(row => {
                        const haystack = row.getAttribute('data-search') || '';
                        if (!query || haystack.includes(query)) {
                            row.classList.remove('hidden');
                        } else {
                            row.classList.add('hidden');
                        }
                    });
                });
            }
        });
    </script>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    ip = request.values.get("ip", "").strip() or None
    port_value = request.values.get("port", str(DEFAULT_PORT))
    try:
        port = int(port_value)
    except (TypeError, ValueError):
        port = DEFAULT_PORT

    employees = []
    selected = set()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "fetch" and ip:
            try:
                employees = fetch_employees(ip, port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al consultar empleados del terminal %s", ip)
                flash(f"No se pudo obtener la información del terminal {ip}: {exc}")
            else:
                _TERMINAL_EMPLOYEES[ip] = employees
                selected = _SELECTED_EMPLOYEES.setdefault(ip, set())
            return redirect(url_for("index", ip=ip, port=port))
        elif action == "select" and ip:
            selected_uids = set(request.form.getlist("selected"))
            _SELECTED_EMPLOYEES[ip] = selected_uids
            return redirect(url_for("index", ip=ip, port=port))
        elif action == "delete" and ip:
            selected_uids = set(request.form.getlist("selected"))
            if not selected_uids:
                flash("Selecciona al menos un empleado para eliminar.")
                return redirect(url_for("index", ip=ip, port=port))

            cached_employees = _TERMINAL_EMPLOYEES.get(ip, [])
            to_delete = [emp for emp in cached_employees if emp.get("uid") in selected_uids]

            if not to_delete:
                flash(
                    "Los empleados seleccionados no están disponibles en caché. Consulta nuevamente el terminal."
                )
                return redirect(url_for("index", ip=ip, port=port))

            try:
                deleted, errors = delete_employees(ip, to_delete, port=port)
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                logger.exception("Error al eliminar empleados del terminal %s", ip)
                flash(f"No se pudieron eliminar los empleados seleccionados: {exc}")
            else:
                if deleted:
                    flash(f"Se eliminaron {len(deleted)} empleado(s) del terminal.")
                    _TERMINAL_EMPLOYEES[ip] = [
                        emp for emp in cached_employees if emp.get("uid") not in deleted
                    ]
                    selected_cache = _SELECTED_EMPLOYEES.get(ip, set())
                    selected_cache.difference_update(deleted)
                    _SELECTED_EMPLOYEES[ip] = selected_cache
                if errors:
                    for uid, message in errors:
                        flash(f"No se pudo eliminar el empleado {uid}: {message}")
            return redirect(url_for("index", ip=ip, port=port))
        elif action in {"export_csv", "export_json", "export_excel"} and ip:
            selected_uids = set(request.form.getlist("selected"))
            if not selected_uids:
                flash("Selecciona al menos un empleado para exportar.")
                return redirect(url_for("index", ip=ip, port=port))

            cached_employees = _TERMINAL_EMPLOYEES.get(ip, [])
            if not cached_employees:
                flash(
                    "No hay empleados en caché para exportar. Consulta primero el terminal."
                )
                return redirect(url_for("index", ip=ip, port=port))

            selected_employees = [
                emp for emp in cached_employees if emp.get("uid") in selected_uids
            ]
            if not selected_employees:
                flash(
                    "Los empleados seleccionados no están disponibles en caché. Consulta nuevamente el terminal."
                )
                return redirect(url_for("index", ip=ip, port=port))

            _SELECTED_EMPLOYEES[ip] = selected_uids
            export_format = action.split("_", 1)[1]
            try:
                return build_export_response(ip, selected_employees, export_format)
            except ValueError as exc:
                flash(str(exc))
                return redirect(url_for("index", ip=ip, port=port))

    if ip and ip in _TERMINAL_EMPLOYEES:
        employees = _TERMINAL_EMPLOYEES[ip]
        selected = _SELECTED_EMPLOYEES.get(ip, set())

    employee_map = {emp["uid"]: emp for emp in employees}
    return render_template_string(
        INDEX_TEMPLATE,
        ip=ip,
        port=port,
        employees=employees,
        selected=selected,
        employee_map=employee_map,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
