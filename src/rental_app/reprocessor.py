from __future__ import annotations
from typing import Optional
from rental_app.db import DB
from rental_app.models import Application, Document, Package, ProcessingEvent
from rental_app import ocr, classifier, packager
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def reprocess_application(db: DB, application_id: int) -> Optional[Application]:
    with db.SessionLocal() as sess:
        app = sess.query(Application).filter(Application.id == application_id).first()
        if not app:
            return None
        # record event
        evt = ProcessingEvent(application_id=app.id, event_type='reprocess_started', message='Reprocess requested')
        sess.add(evt)
        sess.flush()
        docs = sess.query(Document).filter(Document.application_id == app.id).all()
        try:
            for d in docs:
                try:
                    texts = {}
                    try:
                        texts = ocr.extract_text_from_pdf(d.path)
                    except Exception:
                        texts = {}
                    is_scanned = ocr.is_scanned_pdf(texts)
                    if is_scanned:
                        ocr_texts = ocr.ocr_pdf(d.path)
                        combined = '\n'.join(ocr_texts.values())
                    else:
                        combined = '\n'.join(texts.values())
                    d.ocr_text = combined
                    d.pages = len(texts) if texts else None
                    res = classifier.classify_document(d.filename, d.ocr_text)
                    d.document_type = res.document_type
                    sess.add(d)
                    sess.flush()
                    sess.add(ProcessingEvent(application_id=app.id, event_type='doc_processed', message=f'Doc {d.id} processed'))
                except Exception as e:
                    sess.add(ProcessingEvent(application_id=app.id, event_type='doc_error', message=str(e)))
                    raise
            # package
            ordered_paths = [d.path for d in docs]
            output_dir = Path(getattr(db, 'data_dir', './data')) / 'packages'
            pkg_path = packager.create_package(app.id, ordered_paths, str(output_dir))
            import hashlib
            with open(pkg_path, 'rb') as fh:
                chk = hashlib.sha256(fh.read()).hexdigest()
            p = Package(application_id=app.id, package_path=pkg_path, checksum=chk, metadata={})
            sess.add(p)
            sess.add(ProcessingEvent(application_id=app.id, event_type='packaged', message=f'Package created {pkg_path}'))
            sess.commit()
            return app
        except Exception as exc:
            sess.add(ProcessingEvent(application_id=app.id, event_type='reprocess_failed', message=str(exc)))
            sess.commit()
            logger.exception('Reprocess failed for app %s: %s', app.id, exc)
            return app
