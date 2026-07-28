#!/usr/bin/env python3
"""
Import demo/sample applications into the DB for testing/demo mode.

Place sample directories under samples/ each containing files for attachments.
"""
import argparse
import os
import json
from pathlib import Path
from rental_app.db import DB
from rental_app.models import EmailRecord, Application, Document
from rental_app.state_machine import ApplicationStateMachine, State
from rental_app.ocr import extract_text_from_pdf, is_scanned_pdf, ocr_pdf
from rental_app.classifier import classify_document
from rental_app.packager import create_package


def import_demo(samples_dir: str, db_url: str, data_dir: str):
    db = DB(db_url=db_url)
    sd = Path(samples_dir)
    for d in sd.iterdir():
        if not d.is_dir():
            continue
        message_id = d.name
        with db.SessionLocal() as sess:
            # create email record
            er = EmailRecord(message_id=message_id, sender='demo', sender_email='demo@example.com', subject='Demo import')
            sess.add(er)
            sess.flush()
            app = Application(message_id=message_id, processing_id=message_id, state=State.NEW.value)
            sess.add(app)
            sess.flush()
            # copy files into data_dir attachments
            attach_dir = Path(data_dir) / 'attachments' / message_id
            attach_dir.mkdir(parents=True, exist_ok=True)
            docs = []
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                dest = attach_dir / f.name
                if not dest.exists():
                    dest.write_bytes(f.read_bytes())
                doc = Document(application_id=app.id, filename=f.name, path=str(dest), checksum='demo-'+f.name, size_bytes=dest.stat().st_size)
                sess.add(doc)
                docs.append(doc)
            sess.commit()
            print('Imported demo application', message_id)
            # run OCR/classification/packaging immediately
            with db.SessionLocal() as sess2:
                a = sess2.query(Application).filter(Application.message_id==message_id).first()
                docs2 = sess2.query(Document).filter(Document.application_id==a.id).all()
                for doc in docs2:
                    try:
                        texts = extract_text_from_pdf(doc.path)
                        scanned = is_scanned_pdf(texts)
                        if scanned:
                            ocr_texts = ocr_pdf(doc.path)
                            doc.ocr_text = '\n'.join(ocr_texts.values())
                        else:
                            doc.ocr_text = '\n'.join(texts.values())
                        doc.document_type = classify_document(doc.filename, doc.ocr_text).document_type
                        sess2.add(doc)
                    except Exception as e:
                        print('OCR error', e)
                sess2.commit()
                ordered_paths = [doc.path for doc in sess2.query(Document).filter(Document.application_id==a.id).all()]
                pkg = create_package(a.id, ordered_paths, str(Path(data_dir)/'packages'))
                print('Created package', pkg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', default='./samples')
    parser.add_argument('--db', default='sqlite:///./data/tac.db')
    parser.add_argument('--data-dir', default='./data')
    args = parser.parse_args()
    import_demo(args.samples, args.db, args.data_dir)
