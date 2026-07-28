---
# Documentation for local production setup and configuration
# Save this as docs/SETUP.md in the repository

# TAC - Setup & Production Readiness Guide

## Overview
This guide walks through preparing TAC for local production-like use: configuring Gmail OAuth, database initialization, OCR setup, Pub/Sub for Gmail push, and running the dashboard.

## Prerequisites
- Python 3.12+
- System packages: tesseract-ocr (for OCR)
- Google Cloud project and Pub/Sub (if using Gmail push)

## 1) Install Python dependencies

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

(Alternatively see pyproject.toml)

## 2) Tesseract

Ubuntu/Debian:
  sudo apt-get update && sudo apt-get install -y tesseract-ocr

macOS (Homebrew):
  brew install tesseract

## 3) Gmail OAuth

- Create OAuth 2.0 Client ID (Desktop app) in Google Cloud Console.
- Download the `credentials.json` and place it at `./config/credentials.json` or set environment variable `GMAIL_CREDENTIALS_PATH`.
- When first running auth flows, the app will open a browser to complete authorization.

## 4) Pub/Sub for Gmail push (optional)

- Create a Pub/Sub topic in your GCP project.
- Create a subscription for that topic.
- Grant the Gmail push identity `serviceAccount:gmail-api-push@system.gserviceaccount.com` the Publisher role on your topic.
- Set `GMAIL_PUBSUB_TOPIC` in your environment or config.

## 5) Database initialization

Run the setup script to apply migrations:

python scripts/setup.py --db sqlite:///./data/tac.db --data-dir ./data --write-env

This will create the database and optionally write a `.env` file with admin credentials.

## 6) Running the dashboard

Start the dashboard (Flask):

python scripts/run_dashboard.py

Open http://localhost:8080 and login with the admin credentials (from .env or TAC_ADMIN_USER/TAC_ADMIN_PASS).

## 7) Demo mode (no Gmail required)

To import sample demo apps:

mkdir samples && create directories named by message id with files inside
python scripts/import_demo.py --samples ./samples --db sqlite:///./data/tac.db --data-dir ./data

This will import demo applications, run OCR & classification, create packages, and populate the dashboard.

## 8) Logs & Diagnostics

Logs are written to the console and optionally to the file configured in `TAC_JSON_LOG`. Use the dashboard to view recent processing errors. Reprocess or retry failed applications using the dashboard.

## 9) Security

This dashboard is for local/private use. Configure `TAC_ADMIN_USER`, `TAC_ADMIN_PASS`, and `TAC_SECRET_KEY` either in `.env` or environment variables. Do not expose the dashboard without proper authentication.
