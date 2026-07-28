from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import select
from uuid import uuid4
import logging

from rental_app.models import Application

logger = logging.getLogger(__name__)


class State(str, Enum):
    NEW = "New"
    DOWNLOADED = "Downloaded"
    DOCUMENTS_IDENTIFIED = "Documents Identified"
    VERIFICATION_FAILED = "Verification Failed"
    MISSING_DOCUMENTS = "Missing Documents"
    READY_FOR_PACKAGING = "Ready for Packaging"
    PACKAGED = "Packaged"
    AWAITING_MY_APPROVAL = "Awaiting My Approval"
    APPROVED = "Approved"
    SENT = "Sent"
    ERROR = "Error"


_ALLOWED_TRANSITIONS = {
    State.NEW: {State.DOWNLOADED, State.ERROR},
    State.DOWNLOADED: {State.DOCUMENTS_IDENTIFIED, State.ERROR},
    State.DOCUMENTS_IDENTIFIED: {State.MISSING_DOCUMENTS, State.VERIFICATION_FAILED, State.READY_FOR_PACKAGING, State.ERROR},
    State.MISSING_DOCUMENTS: {State.DOWNLOADED, State.ERROR},
    State.VERIFICATION_FAILED: {State.DOWNLOADED, State.ERROR},
    State.READY_FOR_PACKAGING: {State.PACKAGED, State.ERROR},
    State.PACKAGED: {State.AWAITING_MY_APPROVAL, State.ERROR},
    State.AWAITING_MY_APPROVAL: {State.APPROVED, State.ERROR},
    State.APPROVED: {State.SENT, State.ERROR},
    State.SENT: set(),
    State.ERROR: set(),
}


class InvalidTransitionError(Exception):
    pass


@dataclass
class TransitionResult:
    application_id: int
    old_state: State
    new_state: State
    message: str = ""
    success: bool = True


class ApplicationStateMachine:
    """State machine to manage Application processing state transitions.

    Methods are transactional-aware but do not manage session commit. Caller
    should commit the session.
    """

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _validate_transition(old_state: State, new_state: State) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(old_state, set())
        if new_state not in allowed:
            raise InvalidTransitionError(f"Invalid transition {old_state} -> {new_state}")

    def create_application_if_missing(self, message_id: str, history_id: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Application:
        if meta is None:
            meta = {}
        stmt = select(Application).where(Application.message_id == message_id)
        app = self.session.execute(stmt).scalars().first()
        if app:
            logger.debug("Application exists message_id=%s id=%s", message_id, app.id)
            return app
        processing_id = str(uuid4())
        app = Application(message_id=message_id, processing_id=processing_id, state=State.NEW.value, history_id=history_id, meta=meta)
        self.session.add(app)
        self.session.flush()
        logger.info("Created application %s (id=%s)", message_id, app.id)
        return app

    def get_application_by_message_id(self, message_id: str) -> Optional[Application]:
        stmt = select(Application).where(Application.message_id == message_id)
        return self.session.execute(stmt).scalars().first()

    def transition(self, application: Application, new_state: State, reason: Optional[str] = None) -> TransitionResult:
        old_state = State(application.state)
        if old_state == new_state:
            logger.debug("No-op transition for app %s state %s", application.id, new_state)
            return TransitionResult(application_id=application.id, old_state=old_state, new_state=new_state, message="No-op", success=True)
        self._validate_transition(old_state, new_state)
        application.state = new_state.value
        if reason:
            application.last_error = reason
        self.session.add(application)
        self.session.flush()
        logger.info("Transitioned application %s %s -> %s", application.id, old_state, new_state)
        return TransitionResult(application_id=application.id, old_state=old_state, new_state=new_state)

    def transition_by_message_id(self, message_id: str, new_state: State, reason: Optional[str] = None) -> TransitionResult:
        app = self.get_application_by_message_id(message_id)
        if not app:
            raise ValueError(f"No application found with message_id {message_id}")
        return self.transition(app, new_state, reason=reason)
