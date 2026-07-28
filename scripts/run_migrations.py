#!/usr/bin/env python3
import argparse
from rental_app.migrations.runner import apply_migrations

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=False, default='sqlite:///./data/tac.db')
    args = parser.parse_args()
    apply_migrations(args.db)
