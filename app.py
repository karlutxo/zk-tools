"""Aplicación Flask para consultar y seleccionar empleados de terminales ZKTeco."""
from __future__ import annotations

import logging
from typing import Dict, List, Set

from flask import (
    Flask,
    flash,
    redirect,
    render_template_string,
    request,
    url_for,
)

from zk_tools import DEFAULT_PORT, connect_with_retries

app = Flask(__name__)
app.secret_key = "zk-tools-dev"

# Almacenamiento en memoria de los empleados descubiertos por terminal
_TERMINAL_EMPLOYEES: Dict[str, List[dict]] = {}
# Almacenamiento en memoria de los UID seleccionados por terminal
_SELECTED_EMPLOYEES: Dict[str, Set[str]] = {}

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
        <input type=\"hidden\" name=\"action\" value=\"select\">
        <input type=\"hidden\" name=\"ip\" value=\"{{ ip }}\">
        <table>
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
                <tr class=\"{% if employee.uid in selected %}selected{% endif %}\">
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
            <button type=\"submit\">Guardar selección</button>
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
