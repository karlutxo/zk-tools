# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import sys

from zk import const
from zk_tools import connect_with_retries, _has_valid_card

DEFAULT_PORT = 4370


def sync_cards(src_conn, dst_conn):
    """Sync card numbers from src_conn users to dst_conn."""
    users = src_conn.get_users()
    updated = 0
    for u in users:
        if not _has_valid_card(u):
            continue
        dst_conn.set_user(
            uid=u.uid,
            name=getattr(u, 'name', ''),
            privilege=getattr(u, 'privilege', const.USER_DEFAULT),
            password=getattr(u, 'password', ''),
            group_id=getattr(u, 'group_id', ''),
            user_id=getattr(u, 'user_id', ''),
            card=getattr(u, 'card', '')
        )
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
