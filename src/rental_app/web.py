from __future__ import annotations
from typing import Dict, Any, Optional
from flask import Flask, jsonify, request, send_file, abort
import os
from rental_app.db import DB
from rental_app.credential_store import KeyringCredentialStore
from rental_app.gmail_enhancements import GmailClientEnhancements
from rental_app.state_machine import ApplicationStateMachine, State
from rental_app.models import Application, Document, Package, Draft, ReviewerNote
from rental_app.logging_config import setup_logging, get_logger

app = Flask(__name__)
setup_logging()

# initialize DB and Gmail helper - in production, wire credential store and service properly
DB_URL = os.getenv('TAC_DB', 'sqlite:///./data/tac.db')
_db = DB(DB_URL)
_cred_store = KeyringCredentialStore()
_gmail = GmailClientEnhancements(_cred_store, db=_db)

logger = get_logger('tac.web')


@app.route('/api/applications', methods=['GET'])
def list_applications():
    with _db.SessionLocal() as sess:
        apps = sess.query(Application).order_by(Application.created_at.desc()).all()
        out = []
        for a in apps:
            out.append({
                'id': a.id,
                'message_id': a.message_id,
                'state': a.state,
                'created_at': a.created_at.isoformat(),
                'last_error': a.last_error,
            })
        return jsonify(out)


@app.route('/api/applications/<int:app_id>', methods=['GET'])
def get_application(app_id: int):
    with _db.SessionLocal() as sess:
        a = sess.query(Application).filter(Application.id == app_id).first()
        if not a:
            abort(404)
        docs = [
            {'id': d.id, 'filename': d.filename, 'path': d.path, 'document_type': d.document_type}
            for d in a.documents
        ]
        pkgs = [
            {'id': p.id, 'path': p.package_path, 'checksum': p.checksum}
            for p in a.packages
        ]
        drafts = [
            {'id': d.id, 'draft_id': d.draft_id, 'to': d.to, 'subject': d.subject}
            for d in sess.query(Draft).filter(Draft.application_id == a.id).all()
        ]
        notes = [
            {'id': n.id, 'reviewer': n.reviewer, 'note': n.note, 'created_at': n.created_at.isoformat()}
            for n in a.notes
        ]
        missing = []
        # simple missing detection via verification helper
        from rental_app.verification import verify_required_documents
        res = verify_required_documents(a, sess)
        missing = res.missing
        return jsonify({
            'id': a.id,
            'message_id': a.message_id,
            'state': a.state,
            'documents': docs,
            'packages': pkgs,
            'drafts': drafts,
            'notes': notes,
            'missing_documents': missing,
            'last_error': a.last_error,
        })


@app.route('/api/applications/<int:app_id>/notes', methods=['POST'])
def add_note(app_id: int):
    data = request.json or {}
    reviewer = data.get('reviewer')
    note = data.get('note')
    if not note:
        return jsonify({'error': 'note required'}), 400
    with _db.SessionLocal() as sess:
        a = sess.query(Application).filter(Application.id == app_id).first()
        if not a:
            abort(404)
        rn = ReviewerNote(application_id=app_id, reviewer=reviewer, note=note)
        sess.add(rn)
        sess.commit()
        return jsonify({'id': rn.id, 'created_at': rn.created_at.isoformat()})


@app.route('/api/applications/<int:app_id>/approve', methods=['POST'])
def approve_application(app_id: int):
    with _db.SessionLocal() as sess:
        a = sess.query(Application).filter(Application.id == app_id).first()
        if not a:
            abort(404)
        if a.state != State.AWAITING_MY_APPROVAL.value:
            return jsonify({'error': 'Application not awaiting approval'}), 400
        # transition to APPROVED
        machine = ApplicationStateMachine(sess)
        machine.transition(a, State.APPROVED, reason='Approved by reviewer')
        sess.commit()
        # send draft if exists
        draft = sess.query(Draft).filter(Draft.application_id == a.id).first()
        if draft and draft.draft_id:
            try:
                # send via Gmail
                sent = _gmail._service.users().drafts().send(userId='me', body={'id': draft.draft_id}).execute()
                logger.info('Draft sent for application %s', a.id)
            except Exception as exc:
                # roll back approval and set error
                a.last_error = f'DRAFT_SEND_FAILED: {str(exc)[:200]}'
                a.state = State.ERROR.value
                sess.add(a)
                sess.commit()
                return jsonify({'error': 'Failed to send draft'}), 500
        return jsonify({'status': 'approved'})


@app.route('/api/applications/<int:app_id>/reject', methods=['POST'])
def reject_application(app_id: int):
    data = request.json or {}
    reason = data.get('reason')
    with _db.SessionLocal() as sess:
        a = sess.query(Application).filter(Application.id == app_id).first()
        if not a:
            abort(404)
        if a.state != State.AWAITING_MY_APPROVAL.value:
            return jsonify({'error': 'Application not awaiting approval'}), 400
        machine = ApplicationStateMachine(sess)
        machine.transition(a, State.ERROR, reason=f'Rejected: {reason}')
        sess.commit()
        return jsonify({'status': 'rejected'})


@app.route('/api/packages/<int:pkg_id>/file', methods=['GET'])
def get_package_file(pkg_id: int):
    with _db.SessionLocal() as sess:
        p = sess.query(Package).filter(Package.id == pkg_id).first()
        if not p:
            abort(404)
        if not os.path.exists(p.package_path):
            abort(404)
        return send_file(p.package_path, as_attachment=True)


if __name__ == '__main__':
    app.run(port=8080)
