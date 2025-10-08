"""Servicios y utilidades para interactuar con terminales ZKTeco."""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from flask import make_response, send_file
from openpyxl import Workbook, load_workbook

from zk import const
from zk_tools import DEFAULT_PORT, connect_with_retries

logger = logging.getLogger(__name__)

TERMINAL_EMPLOYEES: Dict[str, List[dict]] = {}
SELECTED_EMPLOYEES: Dict[str, Set[str]] = {}
TERMINAL_LIST_PATH = Path(__file__).resolve().parent.parent / "terminales.txt"

EXTERNAL_EMPLOYEE_URL = "http://lpa6.bonny.eu:8888/rh/zk.employees"
EXTERNAL_EMPLOYEE_CACHE_TTL = timedelta(hours=2)
EXTERNAL_EMPLOYEE_CACHE: Dict[str, object] = {"data": None, "timestamp": None}

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


def get_terminal_status(host: str, port: int = DEFAULT_PORT) -> Tuple[dict, List[str]]:
    """Recopila información general del terminal para mostrar al usuario."""

    zk = conn = None
    info: Dict[str, Optional[str]] = {
        "Dirección IP": host,
        "Puerto": str(port),
    }
    errors: List[str] = []

    def safe_call(attr: str, label: str) -> Optional[str]:
        if not hasattr(conn, attr):
            errors.append(f"El terminal no soporta la consulta '{label}'.")
            return None
        try:
            value = getattr(conn, attr)()
        except Exception as exc:  # pragma: no cover - dependiente del dispositivo
            errors.append(f"Error al obtener {label}: {exc}")
            return None
        if value is None:
            return None
        return str(value)

    try:
        zk, conn = connect_with_retries(host, port)
        if conn is None:
            raise ValueError("No se pudo establecer conexión con el terminal.")

        info["Número de serie"] = safe_call("get_serialnumber", "el número de serie")
        info["Nombre del dispositivo"] = safe_call("get_device_name", "el nombre del dispositivo")
        info["Modelo"] = safe_call("get_model", "el modelo")
        info["Plataforma"] = safe_call("get_platform", "la plataforma")
        info["Versión de firmware"] = safe_call("get_firmware_version", "la versión de firmware")
        info["Dirección MAC"] = safe_call("get_mac", "la dirección MAC")
        info["Fecha y hora"] = safe_call("get_time", "la fecha y hora")

        users: List = []
        try:
            users = conn.get_users() or []
        except Exception as exc:  # pragma: no cover - dependiente del dispositivo
            errors.append(f"No se pudo obtener la lista de usuarios: {exc}")
        else:
            info["Usuarios en memoria"] = str(len(users))

        attendance_count: Optional[int] = None
        if hasattr(conn, "get_attendance_count"):
            try:
                attendance_count = conn.get_attendance_count()
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                errors.append(f"No se pudo obtener el número de marcajes: {exc}")
        elif hasattr(conn, "get_attendance"):
            try:
                attendances = conn.get_attendance() or []
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                errors.append(f"No se pudo obtener los marcajes: {exc}")
            else:
                attendance_count = len(attendances)

        if attendance_count is not None:
            info["Marcajes en memoria"] = str(attendance_count)

        if hasattr(conn, "get_work_code"):
            try:
                workcodes = conn.get_work_code() or []
            except Exception as exc:  # pragma: no cover - dependiente del dispositivo
                errors.append(f"No se pudo obtener los códigos de trabajo: {exc}")
            else:
                info["Códigos de trabajo"] = str(len(workcodes))

    finally:
        try:
            if conn:
                conn.disconnect()
        except Exception:  # pragma: no cover - errores de red
            logger.exception("Error al desconectar del terminal %s", host)

    cleaned_info = {k: v for k, v in info.items() if v}
    return cleaned_info, errors


def load_known_terminals() -> List[Dict[str, str]]:
    """Devuelve la lista de terminales conocidos desde el fichero `terminales.txt`."""

    try:
        content = TERMINAL_LIST_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("No se encontró el fichero de terminales en %s", TERMINAL_LIST_PATH)
        return []
    except OSError as exc:
        logger.warning("No se pudo leer el fichero de terminales: %s", exc)
        return []

    terminals: List[Dict[str, str]] = []
    seen_ips = set()
    for line in content.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        label = ""
        ip = entry
        if "," in entry:
            name_part, ip_part = entry.split(",", 1)
            label = name_part.strip()
            ip = ip_part.strip() or ip
        elif " " in entry:
            parts = entry.split()
            ip_candidate = parts[-1]
            ip = ip_candidate.strip()
            label = entry[: -len(ip_candidate)].strip()
        if not ip or ip in seen_ips:
            continue
        seen_ips.add(ip)
        terminals.append({
            "ip": ip,
            "label": label,
        })
    return terminals


def upload_employees(
    host: str, employees: Iterable[dict], port: int = DEFAULT_PORT
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Envía empleados al terminal creando o actualizando sus datos básicos."""

    allowed_privileges = {
        int(getattr(const, name))
        for name in ("USER_DEFAULT", "USER_ADMIN", "USER_ENROLLER", "USER_SUPERADMIN")
        if hasattr(const, name)
    }

    def _coerce_privilege(value) -> int:
        if value is None:
            return const.USER_DEFAULT
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return const.USER_DEFAULT
        lowered = text.lower()
        mapping = {
            "admin": const.USER_ADMIN,
            "superadmin": const.USER_ADMIN,
            "user": const.USER_DEFAULT,
            "default": const.USER_DEFAULT,
        }
        if lowered in mapping:
            return mapping[lowered]
        try:
            numeric = int(text)
        except ValueError:
            return const.USER_DEFAULT
        if allowed_privileges and numeric not in allowed_privileges:
            return const.USER_DEFAULT
        return numeric

    zk = conn = None
    uploaded: List[str] = []
    errors: List[Tuple[str, str]] = []
    try:
        zk, conn = connect_with_retries(host, port)
        if conn is None:
            raise ValueError("No se pudo establecer conexión con el terminal.")
        try:
            conn.disable_device()
        except Exception as exc:  # pragma: no cover - dependiente del terminal
            logger.warning("No fue posible deshabilitar temporalmente el terminal %s: %s", host, exc)

        try:
            existing_users = conn.get_users()
        except Exception as exc:  # pragma: no cover - dependiente del terminal
            logger.warning("No fue posible recuperar usuarios existentes de %s: %s", host, exc)
            existing_users = []

        used_uids: Set[int] = set()
        for user in existing_users:
            try:
                uid_int = int(getattr(user, "uid", None))
            except (TypeError, ValueError):
                continue
            else:
                used_uids.add(uid_int)

        allocated_uids: Set[int] = set()
        next_candidate = 1

        def _allocate_uid() -> int:
            nonlocal next_candidate
            attempts = 0
            while True:
                if next_candidate not in used_uids and next_candidate not in allocated_uids:
                    allocated_uids.add(next_candidate)
                    assigned = next_candidate
                    next_candidate += 1
                    return assigned
                next_candidate += 1
                attempts += 1
                if attempts > 200000:  # límite razonable para evitar bucles infinitos
                    raise ValueError("No se encontraron UID libres en el terminal.")

        for employee in employees:
            uid_label = str(employee.get("uid", "") or "").strip()
            name = str(employee.get("name", "") or "").strip()
            user_id = str(employee.get("user_id", "") or "").strip()
            group_id = str(employee.get("group_id", "") or "").strip()
            privilege = _coerce_privilege(employee.get("privilege"))
            card_value = employee.get("card")
            card = str(card_value).strip() if card_value is not None else ""
            if card.lower() in {"", "0", "none", "null"}:
                card = None

            if not uid_label and not user_id:
                errors.append(("(sin identificador)", "UID o User ID inválido"))
                continue

            try:
                new_uid = _allocate_uid()
            except ValueError as exc:
                errors.append((uid_label or user_id or "(sin identificador)", str(exc)))
                break

            payload = {
                "uid": new_uid,
                "name": name,
                "privilege": privilege,
                "group_id": group_id or "",
                "user_id": user_id or "",
                "password": "",
            }
            if card is not None:
                payload["card"] = card

            try:
                conn.set_user(**payload)
            except Exception as exc:  # pragma: no cover - dependiente del terminal
                errors.append((uid_label or user_id or "(sin UID)", str(exc)))
            else:
                uploaded.append(uid_label or str(new_uid))
    finally:
        try:
            if conn:
                try:
                    conn.enable_device()
                except Exception:  # pragma: no cover - dependiente del terminal
                    logger.exception("Error al habilitar nuevamente el terminal %s", host)
                conn.disconnect()
        except Exception:  # pragma: no cover - errores de red
            logger.exception("Error al desconectar del terminal %s", host)

    return uploaded, errors


def sync_terminal_time(host: str, port: int = DEFAULT_PORT) -> None:
    """Sincroniza la fecha y hora del terminal con la del sistema."""

    zk = conn = None
    try:
        zk, conn = connect_with_retries(host, port)
        if conn is None:
            raise ValueError("No se pudo establecer conexión con el terminal.")
        conn.enable_device()
        conn.set_time(datetime.now())
    finally:
        try:
            if conn:
                conn.disconnect()
        except Exception:  # pragma: no cover - errores de red
            logger.exception("Error al desconectar del terminal %s", host)


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

    key_aliases = {
        "uid": {"uid", "id", "identificador"},
        "name": {"name", "nombre"},
        "user_id": {"user_id", "user id", "userid", "id usuario", "idusuario"},
        "card": {"card", "tarjeta", "num tarjeta"},
        "privilege": {"privilege", "privilegio"},
        "group_id": {"group_id", "group id", "grupo", "id grupo", "grupo id"},
        "biometrics": {"biometrics", "biometria", "biometría", "biometricas", "plantillas"},
    }

    normalized_keys = {}
    for original_key, value in raw.items():
        if isinstance(original_key, str):
            normalized_keys[original_key.strip().lower()] = value

    def _safe_get(key: str):
        candidates = key_aliases.get(key, set()) | {key, key.lower(), key.upper()}
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate_key = candidate.strip().lower()
            if candidate_key in normalized_keys:
                return normalized_keys[candidate_key]
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


def find_duplicate_employees(employees: Iterable[dict]) -> List[dict]:
    """Devuelve empleados que comparten nombre pero tienen distinto user_id."""
    name_to_user_ids: Dict[str, Set[str]] = defaultdict(set)

    normalized_employees: List[Tuple[str, dict]] = []
    for employee in employees:
        raw_name = (employee.get("name") or "").strip()
        normalized_name = raw_name.casefold()
        user_id_value = str(employee.get("user_id") or "").strip()

        normalized_employees.append((normalized_name, employee))
        name_to_user_ids[normalized_name].add(user_id_value)

    duplicate_names = {
        normalized_name
        for normalized_name, user_ids in name_to_user_ids.items()
        if len(user_ids) > 1 and normalized_name
    }

    if not duplicate_names:
        return []

    return [
        employee
        for normalized_name, employee in normalized_employees
        if normalized_name in duplicate_names
    ]


def _download_external_employees() -> List[dict]:
    """Descarga la lista de empleados externos desde el endpoint remoto."""
    try:
        with urlopen(EXTERNAL_EMPLOYEE_URL, timeout=15) as response:  # nosec: B310 - endpoint controlado
            status = getattr(response, "status", response.getcode())
            if status and status >= 400:
                raise ValueError(f"Respuesta inesperada ({status}) al consultar empleados externos.")
            payload = response.read()
    except URLError as exc:
        raise RuntimeError(f"No se pudo conectar con la fuente de empleados externa: {exc}") from exc

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("La respuesta de empleados externa no es un JSON válido.") from exc

    if not isinstance(data, list):
        raise ValueError("La respuesta de empleados externa no es una lista.")

    return data


def load_external_employees(force_refresh: bool = False) -> List[dict]:
    """Obtiene la lista de empleados externos, usando caché durante 2 horas."""
    cached_data = EXTERNAL_EMPLOYEE_CACHE.get("data")
    cached_timestamp = EXTERNAL_EMPLOYEE_CACHE.get("timestamp")
    now = datetime.now(timezone.utc)

    if (
        not force_refresh
        and cached_data
        and isinstance(cached_timestamp, datetime)
        and now - cached_timestamp < EXTERNAL_EMPLOYEE_CACHE_TTL
    ):
        return cached_data

    try:
        data = _download_external_employees()
    except Exception as exc:
        logger.exception("Error al refrescar los empleados externos: %s", exc)
        if cached_data:
            return cached_data
        raise

    EXTERNAL_EMPLOYEE_CACHE["data"] = data
    EXTERNAL_EMPLOYEE_CACHE["timestamp"] = now
    return data


def _store_external_mapping_entry(
    mapping: Dict[str, dict],
    user_code: str,
    payload: dict,
) -> None:
    """Agrega un registro al mapeo usando variaciones comunes del código."""
    if not user_code:
        return

    mapping[user_code] = payload

    trimmed = user_code.lstrip("0")
    if trimmed and trimmed != user_code:
        mapping.setdefault(trimmed, payload)

    upper_original = user_code.upper()
    if upper_original not in mapping:
        mapping[upper_original] = payload

    if trimmed:
        upper_trimmed = trimmed.upper()
        if upper_trimmed not in mapping:
            mapping[upper_trimmed] = payload


def get_external_employee_map(force_refresh: bool = False) -> Dict[str, dict]:
    """Devuelve un diccionario user_id -> datos ampliados del empleado."""
    external_employees = load_external_employees(force_refresh=force_refresh)
    mapping: Dict[str, dict] = {}
    for record in external_employees:
        user_code = str(record.get("CODIGO_ZK_ATRIBUTO") or "").strip()
        if not user_code:
            continue
        payload = {
            "dni": str(record.get("DNI") or "").strip(),
            "nombre": str(record.get("NOMBRE") or "").strip(),
            "cod_ct": str(record.get("COD_CT") or "").strip(),
            "last_seen": record.get("LAST_SEEN"),
        }
        _store_external_mapping_entry(mapping, user_code, payload)
    return mapping


def get_external_employee_map_by_dni(force_refresh: bool = False) -> Dict[str, dict]:
    """Construye un diccionario con clave DNI para datos ampliados."""
    external_employees = load_external_employees(force_refresh=force_refresh)
    mapping: Dict[str, dict] = {}
    for record in external_employees:
        dni = str(record.get("DNI") or "").strip()
        if not dni:
            continue
        payload = {
            "dni": dni,
            "nombre": str(record.get("NOMBRE") or "").strip(),
            "cod_ct": str(record.get("COD_CT") or "").strip(),
            "last_seen": record.get("LAST_SEEN"),
        }
        normalized = dni.upper()
        mapping.setdefault(dni, payload)
        mapping.setdefault(normalized, payload)
    return mapping


def lookup_external_employee(identifier: str, mapping: Dict[str, dict]) -> Optional[dict]:
    """Busca un empleado externo usando variaciones comunes del identificador."""
    if not identifier:
        return None

    candidate = str(identifier).strip()
    if not candidate:
        return None

    variations = [
        candidate,
        candidate.upper(),
    ]

    trimmed = candidate.lstrip("0")
    if trimmed:
        variations.extend([trimmed, trimmed.upper()])

    for key in variations:
        if key and key in mapping:
            return mapping[key]
    return None


def format_relative_time(value: Optional[str], default: str = "N/A") -> str:
    """Convierte una fecha ISO en un texto relativo (p.ej. '4 hours ago')."""
    if not value:
        return default

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed_date = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return default
        parsed = datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            tzinfo=timezone.utc,
        )

    if not isinstance(parsed, datetime):
        parsed = datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - parsed
    seconds = delta.total_seconds()

    if abs(seconds) < 60:
        return "just now"

    future = seconds < 0
    seconds = abs(seconds)

    units = (
        (365 * 24 * 3600, "year"),
        (30 * 24 * 3600, "month"),
        (7 * 24 * 3600, "week"),
        (24 * 3600, "day"),
        (3600, "hour"),
        (60, "minute"),
    )

    for unit_seconds, unit_name in units:
        if seconds >= unit_seconds:
            value_count = int(seconds // unit_seconds)
            plural = "s" if value_count != 1 else ""
            text = f"{value_count} {unit_name}{plural}"
            return f"in {text}" if future else f"{text} ago"

    return default
