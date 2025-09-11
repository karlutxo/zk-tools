# -*- coding: utf-8 -*-
from __future__ import print_function  # permite print() en Python 2.7
import argparse
import socket
import sys
import time
import datetime

from zk import ZK, const  # pyzk / zk

DEFAULT_PORT = 4370
RETRIES = 3
RETRY_DELAY = 2  # segundos


def connect_with_retries(host, port, timeout=10):
    last_exc = None
    attempt = 1
    while attempt <= RETRIES:
        try:
            zk = ZK(host, port=port, timeout=timeout, verbose=False)
            conn = zk.connect()
            return zk, conn
        except (socket.timeout, OSError, Exception) as e:
            last_exc = e
            if attempt < RETRIES:
                time.sleep(RETRY_DELAY)
                attempt += 1
            else:
                raise last_exc
    return None, None


def _u(obj):
    """Devuelve una representación segura para impresión en py2/py3."""
    try:
        basestring  # noqa (solo existe en py2)
        if isinstance(obj, unicode):  # noqa
            return obj.encode('utf-8')
        return str(obj)
    except NameError:
        return str(obj)


def _has_valid_card(user):
    """True si el usuario tiene tarjeta no vacía/0."""
    if not hasattr(user, "card"):
        return False
    val = getattr(user, "card", None)
    if val is None:
        return False
    s = str(val).strip()
    if s.lower() in ("", "0", "none", "null"):
        return False
    try:
        if int(s) == 0:
            return False
    except Exception:
        pass
    return True


def list_functions(conn):
    print('--- Funciones soportadas ---')
    for name in dir(conn):
        if not name.startswith("_"):
            func = getattr(conn, name)
            if callable(func):
                doc = getattr(func, "__doc__", "")
                print("=================================================================")
                print("{0}:\n  {1}\n".format(name, doc.strip() if doc else "No docstring"))


def list_users(conn, solo_tarjeta=False):
    print('--- Users ---')
    users = conn.get_users()
    total = 0
    for u in users:
        if solo_tarjeta and not _has_valid_card(u):
            continue
        print(u.__dict__)
        privilege = 'Admin' if u.privilege == const.USER_ADMIN else 'User'
        try:
            verif_mode = conn.get_user_verif_mode(u.uid)  # devuelve str o None (Group)
            if verif_mode is None:
                verif_mode = 'Group'  # modo por grupo
        except Exception as e:
            verif_mode = f'N/A ({e})'  # terminal no soporta, timeout, etc.
        print('+ UID #{0}'.format(_u(u.uid)))
        print('  Name      : {0}'.format(_u(u.name)))
        print('  Privilege : {0}'.format(privilege))
        print(f'  VerifMode : {verif_mode}')
        print('  Group ID  : {0}'.format(_u(u.group_id)))
        print('  User ID   : {0}'.format(_u(u.user_id)))
        if hasattr(u, "card"):
            print('  Card      : {0}'.format(_u(u.card)))
        print('')
        total += 1
    print('Total usuarios{0}: {1}'.format(' con tarjeta' if solo_tarjeta else '', total))


def voice_test(conn):
    print('Voice Test…')
    conn.test_voice()


def get_terminal_time(conn):
    now = conn.get_time()
    print('Fecha y hora del terminal: {0}'.format(now))


def sync_terminal_time(conn):
    now = datetime.datetime.now()
    conn.set_time(now)
    print('Fecha y hora del terminal establecida a: {0}'.format(now))


def device_enable(conn, enable=True):
    if enable:
        print('Enabling device…')
        conn.enable_device()
    else:
        print('Disabling device…')
        conn.disable_device()


def main():
    parser = argparse.ArgumentParser(
        description='ZKTeco helper (Python 2.7/3.x): listar usuarios, test de voz y (des)habilitar dispositivo.'
    )
    parser.add_argument('host', help='IP del terminal ZKTeco (p.ej. 192.9.210.91)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help='Puerto (default {0})'.format(DEFAULT_PORT))
    parser.add_argument('--list-users', action='store_true', help='Listar usuarios')
    parser.add_argument('--solo-tarjeta', action='store_true',
                        help='Mostrar solo usuarios con tarjeta asignada (requiere --list-users)')
    parser.add_argument('--voice-test', action='store_true', help='Reproducir voice test')
    parser.add_argument('--disable', action='store_true', help='Deshabilitar temporalmente el dispositivo')
    parser.add_argument('--enable', action='store_true', help='Habilitar el dispositivo')
    parser.add_argument('--list-functions', action='store_true', help='Lista las funciones soportadas por el dispositivo')
    parser.add_argument('--get-time', action='store_true',
                        help='Obtiene la fecha y hora del terminal')
    parser.add_argument('--sync-time', action='store_true',
                        help='Establece la fecha y hora del terminal a la del sistema')
    args = parser.parse_args()

    zk = None
    conn = None
    try:
        zk, conn = connect_with_retries(args.host, args.port)
        print('Conectado.')

        if args.disable:
            device_enable(conn, enable=False)

        if args.list_users:
            list_users(conn, solo_tarjeta=args.solo_tarjeta)

        if args.voice_test:
            voice_test(conn)

        if args.enable:
            device_enable(conn, enable=True)

        if args.list_functions:
            list_functions(conn)

        if args.get_time:
            get_terminal_time(conn)

        if args.sync_time:
            sync_terminal_time(conn)

    except Exception as e:
        print('Error: {0}'.format(e))
        sys.exit(1)
    finally:
        try:
            if conn:
                if (not args.disable) or args.enable:
                    conn.enable_device()
                conn.disconnect()
        except Exception:
            pass


if __name__ == '__main__':
    main()
