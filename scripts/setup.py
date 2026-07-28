#!/usr/bin/env python3
"""
Setup script for TAC local deployment.

- Applies DB migrations
- Ensures data directories exist
- Optionally writes a .env file with admin credentials (local use only)
"""
import argparse
import os
from rental_app.migrations.runner import apply_migrations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='sqlite:///./data/tac.db')
    parser.add_argument('--data-dir', default='./data')
    parser.add_argument('--admin-user', default='admin')
    parser.add_argument('--admin-pass', default='password')
    parser.add_argument('--write-env', action='store_true')
    args = parser.parse_args()
    os.makedirs(args.data_dir, exist_ok=True)
    print('Applying migrations...')
    apply_migrations(args.db)
    if args.write_env:
        env_path = '.env'
        with open(env_path, 'w') as fh:
            fh.write(f"TAC_DB={args.db}\n")
            fh.write(f"TAC_DATA_DIR={args.data_dir}\n")
            fh.write(f"TAC_ADMIN_USER={args.admin_user}\n")
            fh.write(f"TAC_ADMIN_PASS={args.admin_pass}\n")
        print(f'Wrote {env_path} with admin credentials (keep secure)')
    print('Setup complete')

if __name__ == '__main__':
    main()
