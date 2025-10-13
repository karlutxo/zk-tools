"""Utilidades de configuración para la aplicación zk-tools."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def _clean_value(value: str) -> str:
    """Normaliza un valor eliminando comillas envolventes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file(env_path: Path) -> Dict[str, str]:
    """Carga un archivo .env simple en un diccionario."""
    if not env_path.exists():
        return {}

    data: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        data[key.strip()] = _clean_value(value.strip())

    return data


_ENV_CACHE = _load_env_file(Path(__file__).resolve().parents[1] / ".env")


def get_setting(key: str, default: str | None = None) -> str | None:
    """Obtiene un valor de configuración, priorizando variables de entorno."""
    return os.getenv(key, _ENV_CACHE.get(key, default))

