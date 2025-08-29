# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import sys

from zk import const
from zk_tools import connect_with_retries, _has_valid_card
from update_empl import update_employee_card

DEFAULT_PORT = 4370


def sync_cards(src_conn, dst_conn):
    """Sync card numbers from src_conn users to dst_conn matching by user_id.

    Only the ``card`` field is updated in the destination terminal; all the
    remaining user information is preserved as stored on ``dst_conn``.
    """

    src_users = src_conn.get_users()

    updated = 0
    for src_u in src_users:
        if not _has_valid_card(src_u):
            continue

        user_id = getattr(src_u, 'user_id', '')
        if not user_id:
            continue

        if (update_employee_card(dst_conn, user_id=user_id, card=getattr(src_u, 'card', ''))):
            updated += 1

    return updated


def main():
    parser = argparse.ArgumentParser(
        description='Sync card numbers between two ZKTeco terminals'
    )
    parser.add_argument('src_host', help='IP del terminal origen')
    parser.add_argument('dst_host', help='IP del terminal destino')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help='Puerto (mismo para ambos, default {0})'.format(DEFAULT_PORT))
    args = parser.parse_args()

    src_zk = dst_zk = src_conn = dst_conn = None
    try:
        src_zk, src_conn = connect_with_retries(args.src_host, args.port)
        dst_zk, dst_conn = connect_with_retries(args.dst_host, args.port)
        print('Conectado a ambos terminales.')

        count = sync_cards(src_conn, dst_conn)
        print('Actualizados {0} usuarios con tarjeta.'.format(count))
    except Exception as e:
        print('Error: {0}'.format(e))
        sys.exit(1)
    finally:
        for conn in (src_conn, dst_conn):
            try:
                if conn:
                    conn.disconnect()
            except Exception:
                pass


if __name__ == '__main__':
    main()
