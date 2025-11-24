# -*- coding: utf-8 -*-
"""Sincroniza fecha y hora de todos los terminales listados en `terminales.txt`.

Para cada terminal registra la hora antes y después de la actualización en
`terminal_time_updates.log`.
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

from zk_tools import DEFAULT_PORT, connect_with_retries

TERMINAL_LIST = Path(__file__).resolve().parent / "terminales.txt"
LOG_FILE = Path(__file__).resolve().parent / "terminal_time_updates.log"
DRIFT_THRESHOLD_SECONDS = 60


def setup_logging() -> None:
    handlers: List[logging.Handler] = [
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def parse_terminal_list(path: Path) -> List[Tuple[str, str]]:
    terminals: List[Tuple[str, str]] = []
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el fichero de terminales: {path}")

    with path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "," not in line:
                logging.warning("Línea %s sin separador ',': %s", line_no, line)
                continue
            name_part, ip_part = line.split(",", 1)
            ip = ip_part.strip()
            if not ip:
                logging.warning("Línea %s sin IP válida: %s", line_no, line)
                continue
            name = name_part.strip() or ip
            terminals.append((name, ip))
    return terminals


def _log_with_drift(message: str, drift_seconds: float, base_level: int = logging.INFO) -> None:
    highlight = drift_seconds > DRIFT_THRESHOLD_SECONDS
    suffix = ""
    if highlight:
        suffix = f" [DESV {int(drift_seconds)}s > {DRIFT_THRESHOLD_SECONDS}s]"
    level = logging.WARNING if highlight else base_level
    logging.log(level, f"{message}{suffix}")


def sync_terminal_time(name: str, host: str, port: int, only_read: bool = False) -> None:
    zk = None
    conn = None
    try:
        zk, conn = connect_with_retries(host, port)
        before = conn.get_time()
        now_local = datetime.now()
        drift_before = abs((now_local - before).total_seconds())

        if only_read:
            _log_with_drift(
                "Conectando con %s (%s:%s)... Hora de terminal: %s"
                % (name, host, port, before),
                drift_before,
            )
            return

        logging.info("Conectando con %s (%s:%s)...", name, host, port)
        _log_with_drift("[%s] Hora antes: %s" % (name, before), drift_before)

        conn.set_time(now_local)
        after = conn.get_time()
        drift_after = abs((after - now_local).total_seconds())
        _log_with_drift("[%s] Hora después: %s" % (name, after), drift_after)
    except Exception as exc:  # pragma: no cover - protege de problemas de red/dispositivo
        logging.error("Error al sincronizar %s (%s): %s", name, host, exc)
    finally:
        try:
            if conn:
                conn.enable_device()
                conn.disconnect()
        except Exception:
            pass


def sync_all(terminals: Iterable[Tuple[str, str]], port: int, only_read: bool) -> None:
    for name, host in terminals:
        sync_terminal_time(name, host, port, only_read=only_read)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Actualiza la fecha y hora de todos los terminales listados."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=TERMINAL_LIST,
        help=f"Ruta al fichero de terminales (por defecto {TERMINAL_LIST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Puerto de los terminales (por defecto {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--only_read",
        action="store_true",
        help="Solo consulta la fecha y hora de cada terminal sin actualizarla",
    )
    args = parser.parse_args()

    setup_logging()
    logging.info("Leyendo terminales de %s", args.file)
    terminals = parse_terminal_list(args.file)
    if not terminals:
        logging.warning("No se encontraron terminales en %s", args.file)
        return

    sync_all(terminals, args.port, args.only_read)
    if args.only_read:
        logging.info("Consulta completada. Log en %s", LOG_FILE)
    else:
        logging.info("Sincronización completada. Log en %s", LOG_FILE)


if __name__ == "__main__":
    main()
