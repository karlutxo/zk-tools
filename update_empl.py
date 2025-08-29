# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import sys

from zk import const
from zk_tools import connect_with_retries

DEFAULT_PORT = 4370
TARGET_USER_ID = '1800410'
NEW_CARD = '4088337'


def update_employee_card(conn, user_id=TARGET_USER_ID, card=NEW_CARD):
    """Busca al usuario por user_id y actualiza su tarjeta."""
    users = conn.get_users()
    for u in users:
        if str(getattr(u, 'user_id', '')) == str(user_id):
            conn.set_user(
                uid=u.uid,
                name=getattr(u, 'name', ''),
                privilege=getattr(u, 'privilege', const.USER_DEFAULT),
                password=getattr(u, 'password', ''),
                group_id=getattr(u, 'group_id', ''),
                user_id=getattr(u, 'user_id', ''),
                card=card,
            )
            return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description='Actualiza tarjeta para user_id {0}'.format(TARGET_USER_ID)
    )
    parser.add_argument('dst_host', help='IP del terminal destino')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help='Puerto (default {0})'.format(DEFAULT_PORT))
    args = parser.parse_args()

    zk = conn = None
    try:
        zk, conn = connect_with_retries(args.dst_host, args.port)
        print('Conectado al terminal.')
        if update_employee_card(conn):
            print('Tarjeta actualizada.')
        else:
            print('Usuario no encontrado.')
    except Exception as e:
        print('Error: {0}'.format(e))
        sys.exit(1)
    finally:
        try:
            if conn:
                conn.disconnect()
        except Exception:
            pass


if __name__ == '__main__':
    main()
