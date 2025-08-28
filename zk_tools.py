# -*- coding: utf-8 -*-
from __future__ import print_function  # permite print() en Python 2.7
import argparse
import socket
import sys
import time

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
        # Python 2: basestring existe
        basestring  # noqa
        if isinstance(obj, unicode):  # noqa
            return obj.encode('utf-8')
        return str(obj)
    except NameError:
        # Python 3
        return str(obj)

def list_functions(conn):
    print('--- Funciones soportadas ---')
#    print(dir(conn))
    for name in dir(conn):
        if not name.startswith("_"):
            func = getattr(conn, name)
            if callable(func):
                doc = getattr(func, "__doc__", "")
                print("=================================================================")
                print("{0}:\n  {1}\n".format(name, doc.strip() if doc else "No docstring"))


def list_users(conn):
    print('--- Users ---')
    users = conn.get_users()
    for u in users:
        print(u.__dict__)


def voice_test(conn):
    print('Voice Test…')
    conn.test_voice()


def device_enable(conn, enable=True):
    if enable:
        print('Enabling device…')
        conn.enable_device()
    else:
        print('Disabling device…')
        conn.disable_device()


def main():
    parser = argparse.ArgumentParser(
        description='ZKTeco helper (Python 2.7): listar usuarios, test de voz y (des)habilitar dispositivo.'
    )
    parser.add_argument('host', help='IP del terminal ZKTeco (p.ej. 192.9.210.91)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help='Puerto (default {0})'.format(DEFAULT_PORT))
    parser.add_argument('--list-users', action='store_true', help='Listar usuarios')
    parser.add_argument('--voice-test', action='store_true', help='Reproducir voice test')
    parser.add_argument('--disable', action='store_true', help='Deshabilitar temporalmente el dispositivo')
    parser.add_argument('--enable', action='store_true', help='Habilitar el dispositivo')
    parser.add_argument('--list-functions', action='store_true', help='Lista las funciones soportadas por el dispositivo')
    args = parser.parse_args()

    zk = None
    conn = None
    try:
        zk, conn = connect_with_retries(args.host, args.port)
        print('Conectado.')

        if args.disable:
            device_enable(conn, enable=False)

        if args.list_users:
            list_users(conn)

        if args.voice_test:
            voice_test(conn)

        if args.enable:
            device_enable(conn, enable=True)

        if args.list_functions:
            list_functions(conn)

    except Exception as e:
        print('Error: {0}'.format(e))
        sys.exit(1)
    finally:
        try:
            if conn:
                # Rehabilita salvo que se haya pedido dejarlo deshabilitado explícitamente
                if (not args.disable) or args.enable:
                    conn.enable_device()
                conn.disconnect()
        except Exception:
            pass


if __name__ == '__main__':
    main()

