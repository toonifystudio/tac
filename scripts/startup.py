#!/usr/bin/env python3
"""
Startup script for TAC — validates environment and starts the dashboard.
"""
import os
import shutil
import sys
import subprocess
from rental_app.config_env import get_config


def check_tesseract():
    return shutil.which('tesseract') is not None


def main():
    cfg = get_config()
    print('Validating environment...')
    if not os.path.isdir(cfg.data_dir):
        print('Creating data dir', cfg.data_dir)
        os.makedirs(cfg.data_dir, exist_ok=True)
    print('Checking Tesseract...')
    if not check_tesseract():
        print('Warning: tesseract not found on PATH. Install tesseract to enable OCR.')
    creds = cfg.gmail_credentials
    if creds and not os.path.exists(creds):
        print(f'Gmail credentials not found at {creds}; running in demo mode or configure credentials for Gmail.')
    print('Starting dashboard...')
    # Launch the Flask app
    subprocess.run([sys.executable, 'scripts/run_dashboard.py'])

if __name__ == '__main__':
    main()
