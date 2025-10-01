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
from openpyxl import Workbook, load_workbook

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


def _normalize_employee_record(raw: dict) -> dict:
    """Normaliza los datos de un empleado importado."""

    def _safe_get(key: str):
        for candidate in (key, key.lower(), key.upper()):
            if candidate in raw:
                return raw.get(candidate)
        return raw.get(key)

    biometrics_value = _safe_get("biometrics")
    biometrics: List[dict]
    if isinstance(biometrics_value, list):
        biometrics = [item for item in biometrics_value if isinstance(item, dict)]
    elif isinstance(biometrics_value, str):
        biometrics_value = biometrics_value.strip()
        if biometrics_value:
            try:
                parsed = json.loads(biometrics_value)
            except json.JSONDecodeError:
                biometrics = []
            else:
                biometrics = (
                    [item for item in parsed if isinstance(item, dict)]
                    if isinstance(parsed, list)
                    else []
                )
        else:
            biometrics = []
    else:
        biometrics = []

    return {
        "uid": str(_safe_get("uid") or ""),
        "name": _safe_get("name") or "",
        "user_id": _safe_get("user_id") or "",
        "card": _safe_get("card") or "",
        "privilege": _safe_get("privilege") or "",
        "group_id": _safe_get("group_id") or "",
        "biometrics": biometrics,
    }


def parse_employee_file(file_storage) -> List[dict]:
    """Convierte un archivo cargado en una lista de empleados."""

    if file_storage is None:
        raise ValueError("Selecciona un archivo para importar.")

    filename = (file_storage.filename or "").strip()
    if not filename:
        raise ValueError("Selecciona un archivo para importar.")

    payload = file_storage.read()
    if not payload:
        raise ValueError("El archivo de empleados está vacío.")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "json":
        try:
            data = json.loads(payload.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"El archivo JSON es inválido: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("El archivo JSON debe contener una lista de empleados.")
        return [_normalize_employee_record(item) for item in data if isinstance(item, dict)]

    if ext == "csv":
        text = payload.decode("utf-8-sig")
        reader = csv.DictReader(StringIO(text))
        return [_normalize_employee_record({k.lower(): v for k, v in row.items()}) for row in reader]

    if ext in {"xlsx", "xlsm"}:
        workbook = load_workbook(BytesIO(payload), data_only=True)
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(cell).strip().lower() if cell is not None else "" for cell in rows[0]]
        employees: List[dict] = []
        for row in rows[1:]:
            if row is None:
                continue
            row_dict = {
                headers[index]: value
                for index, value in enumerate(row)
                if index < len(headers) and headers[index]
            }
            employees.append(_normalize_employee_record(row_dict))
        return employees

    raise ValueError("Formato de archivo no soportado. Usa JSON, CSV o Excel.")


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

    <form method=\"post\" action=\"{{ url_for('index') }}\" enctype=\"multipart/form-data\" class=\"table-controls\">
        <input type=\"hidden\" name=\"action\" value=\"import\">
        <label for=\"import-ip\">Terminal:</label>
        <input type=\"text\" name=\"ip\" id=\"import-ip\" value=\"{{ ip or '' }}\" required>
        <label for=\"employee-file\">Importar empleados:</label>
        <input type=\"file\" name=\"employee_file\" id=\"employee-file\" accept=\".json,.csv,.xlsx,.xlsm\" required>
        <button type=\"submit\">Importar</button>
    </form>

    <form method=\"post\" action=\"{{ url_for('index') }}\">
        <input type=\"hidden\" name=\"action\" value=\"fetch\">
        <label for=\"ip\">Dirección IP del terminal:</label>
        <input type=\"text\" name=\"ip\" id=\"ip\" value=\"{{ ip or '' }}\" required>
        <label for=\"port\">Puerto:</label>
        <input type=\"number\" name=\"port\" id=\"port\" value=\"{{ port }}\" min=1 max=65535>
        <button type=\"submit\">Leer empleados</button>
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
            <button type=\"submit\" name=\"action\" value=\"clear\" onclick=\"return confirm('Esto eliminará a todos los empleados almacenados en memoria para este terminal. ¿Continuar?');\">Limpiar</button>
        </div>
        <div class=\"actions\">
            <span>Exportar selección:</span>
            <button type=\"submit\" name=\"action\" value=\"export_csv\">CSV</button>
            <button type=\"submit\" name=\"action\" value=\"export_json\">JSON</button>
            <button type=\"submit\" name=\"action\" value=\"export_excel\">Excel</button>
        </div>
        <div class=\"actions\">
            <span id=\"selection-info\" data-total=\"{{ total_employees }}\" data-selected=\"{{ selected_count }}\">Seleccionados: {{ selected_count }} de {{ total_employees }}</span>
        </div>
    </form>
    {% elif ip %}
        <p>No se encontraron empleados para el terminal {{ ip }}.</p>
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
            let lastClicked = null;
            const selectionInfo = document.getElementById('selection-info');
            const totalEmployees = selectionInfo ? parseInt(selectionInfo.dataset.total || '0', 10) : checkboxes.length;

            const updateSelectAllState = () => {
                if (!selectAll) {
                    return;
                }
                if (!checkboxes.length) {
                    selectAll.checked = false;
                    return;
                }
                selectAll.checked = checkboxes.every(item => item.checked);
            };

            const updateSelectionInfo = () => {
                if (!selectionInfo) {
                    return;
                }
                const selectedCount = checkboxes.filter(cb => cb.checked).length;
                selectionInfo.dataset.selected = String(selectedCount);
                selectionInfo.textContent = `Seleccionados: ${selectedCount} de ${totalEmployees}`;
            };

            const updateRowClasses = () => {
                rows.forEach((row, index) => {
                    const checkbox = checkboxes[index];
                    if (!checkbox) {
                        return;
                    }
                    row.classList.toggle('selected', checkbox.checked);
                });
                updateSelectionInfo();
            };

            if (selectAll) {
                selectAll.addEventListener('change', function () {
                    checkboxes.forEach(cb => {
                        cb.checked = selectAll.checked;
                    });
                    updateRowClasses();
                    updateSelectAllState();
                });
            }

            checkboxes.forEach(cb => {
                cb.addEventListener('change', function () {
                    updateRowClasses();
                    updateSelectAllState();
                });

                cb.addEventListener('click', function (event) {
                    if (event.shiftKey && lastClicked && lastClicked !== cb) {
                        const currentIndex = checkboxes.indexOf(cb);
                        const lastIndex = checkboxes.indexOf(lastClicked);
                        if (currentIndex !== -1 && lastIndex !== -1) {
                            const start = Math.min(currentIndex, lastIndex);
                            const end = Math.max(currentIndex, lastIndex);
                            const shouldCheck = cb.checked;
                            for (let i = start; i <= end; i++) {
                                checkboxes[i].checked = shouldCheck;
                            }
                            updateRowClasses();
                            updateSelectAllState();
                        }
                    }
                    lastClicked = cb;
                });
            });

            updateRowClasses();
            updateSelectAllState();
            updateSelectionInfo();

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
        if action == "import" and ip:
            try:
                imported_employees = parse_employee_file(request.files.get("employee_file"))
            except ValueError as exc:
                flash(str(exc))
            else:
                _TERMINAL_EMPLOYEES[ip] = imported_employees
                _SELECTED_EMPLOYEES[ip] = set()
                flash(
                    f"Se importaron {len(imported_employees)} empleado(s) en memoria para el terminal {ip}."
                )
            return redirect(url_for("index", ip=ip, port=port))
        elif action == "import":
            flash("Debes indicar un terminal para importar empleados.")
            return redirect(url_for("index"))
        elif action == "fetch" and ip:
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
        elif action == "clear":
            if ip:
                cached = _TERMINAL_EMPLOYEES.pop(ip, [])
                removed_count = len(cached)
                _SELECTED_EMPLOYEES.pop(ip, None)
                if removed_count:
                    flash(
                        f"Se limpiaron {removed_count} empleado(s) en memoria para el terminal {ip}."
                    )
                else:
                    flash("No había empleados almacenados en memoria para este terminal.")
                return redirect(url_for("index", ip=ip, port=port))
            _TERMINAL_EMPLOYEES.clear()
            _SELECTED_EMPLOYEES.clear()
            flash("Se limpiaron los empleados almacenados en memoria.")
            return redirect(url_for("index"))

    if ip and ip in _TERMINAL_EMPLOYEES:
        employees = _TERMINAL_EMPLOYEES[ip]
        selected = _SELECTED_EMPLOYEES.get(ip, set())
    
    employee_map = {emp["uid"]: emp for emp in employees}
    employee_uids = set(employee_map.keys())
    selected = {uid for uid in selected if uid in employee_uids}
    if ip:
        _SELECTED_EMPLOYEES[ip] = selected
    total_employees = len(employees)
    selected_count = len(selected)
    return render_template_string(
        INDEX_TEMPLATE,
        ip=ip,
        port=port,
        employees=employees,
        selected=selected,
        employee_map=employee_map,
        total_employees=total_employees,
        selected_count=selected_count,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
