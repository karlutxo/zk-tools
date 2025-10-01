"""Servicios y utilidades para interactuar con terminales ZKTeco."""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from io import BytesIO, StringIO
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from flask import make_response, send_file
from openpyxl import Workbook, load_workbook

from zk_tools import DEFAULT_PORT, connect_with_retries

logger = logging.getLogger(__name__)

TERMINAL_EMPLOYEES: Dict[str, List[dict]] = {}
SELECTED_EMPLOYEES: Dict[str, Set[str]] = {}

EXPORT_COLUMNS: Sequence[Tuple[str, str]] = (
    ("uid", "UID"),
    ("name", "Nombre"),
    ("user_id", "User ID"),
    ("card", "Tarjeta"),
    ("privilege", "Privilegio"),
    ("group_id", "Grupo"),
    ("biometrics", "Biometría"),
)


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
                    "size": len(getattr(template, "template", b""))
                    if hasattr(template, "template")
                    else None,
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
    host: str, employees: Iterable[dict], port: int = DEFAULT_PORT
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


def coerce_port(port_value: Optional[str]) -> int:
    try:
        port = int(port_value) if port_value is not None else DEFAULT_PORT
    except (TypeError, ValueError):
        return DEFAULT_PORT
    if 1 <= port <= 65535:
        return port
    return DEFAULT_PORT


def parse_terminal_value(value: Optional[str]) -> Tuple[Optional[str], int]:
    """Convierte el texto introducido por el usuario en IP y puerto."""

    if not value:
        return None, DEFAULT_PORT

    cleaned = value.strip()
    if not cleaned:
        return None, DEFAULT_PORT

    host = cleaned
    port = DEFAULT_PORT

    if cleaned.startswith("[") and "]" in cleaned:
        closing = cleaned.find("]")
        host = cleaned[1:closing].strip()
        remainder = cleaned[closing + 1 :].strip()
        if remainder.startswith(":"):
            port = coerce_port(remainder[1:].strip())
    else:
        parts = cleaned.rsplit(":", 1)
        if len(parts) == 2 and parts[0]:
            potential_host, potential_port = parts
            if potential_port:
                host = potential_host.strip() or cleaned
                port = coerce_port(potential_port.strip())
        elif cleaned.count(":") > 1:
            host = cleaned  # Dirección IPv6 sin puerto

    host = host.strip()
    if not host:
        host = None

    return host, port


def format_terminal_value(host: Optional[str], port: int) -> str:
    if not host:
        return ""
    if port == DEFAULT_PORT:
        return host
    return f"{host}:{port}"


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


def get_cached_employees(host: str) -> List[dict]:
    """Devuelve los empleados almacenados en memoria para un terminal."""
    return TERMINAL_EMPLOYEES.get(host, [])


def set_cached_employees(host: str, employees: List[dict]) -> None:
    """Guarda los empleados en memoria para un terminal."""
    TERMINAL_EMPLOYEES[host] = employees


def clear_terminal_cache(host: str) -> List[dict]:
    """Elimina y devuelve los empleados en memoria de un terminal."""
    removed = TERMINAL_EMPLOYEES.pop(host, [])
    SELECTED_EMPLOYEES.pop(host, None)
    return removed


def clear_all_cache() -> None:
    """Vacía las estructuras en memoria utilizadas por la aplicación."""
    TERMINAL_EMPLOYEES.clear()
    SELECTED_EMPLOYEES.clear()


def get_selected_uids(host: str) -> Set[str]:
    """Obtiene los UID seleccionados para un terminal."""
    return set(SELECTED_EMPLOYEES.get(host, set()))


def set_selected_uids(host: str, selected: Iterable[str]) -> None:
    """Almacena los UID seleccionados para un terminal."""
    SELECTED_EMPLOYEES[host] = set(selected)


def remove_selected_uids(host: str, uids: Iterable[str]) -> None:
    """Elimina UID concretos del conjunto de seleccionados de un terminal."""
    existing = SELECTED_EMPLOYEES.get(host)
    if existing is None:
        return
    existing.difference_update({str(uid) for uid in uids})
    SELECTED_EMPLOYEES[host] = existing
