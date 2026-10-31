import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_status_history import ApplicationStatusHistory
from app.models.followup import FollowUp
from app.models.user import User
from app.schemas.application import ApplicationCreate, ApplicationUpdate


class ApplicationNotFoundError(Exception):
    pass


class DuplicateApplicationError(Exception):
    pass


def _annotate_followup_fields(db: Session, application: Application) -> Application:
    """Populates computed, non-DB fields (followup_count, last_followup_at,
    next_followup_due_at, pending_followup_count) that ApplicationRead exposes to the
    frontend - derived from FollowUp rows + the user's cadence settings rather than
    denormalized columns, so there's a single source of truth for what's been sent."""
    from app.services.followup_service import followup_anchor, has_open_draft, slots_used

    sent = sorted((f for f in application.followups if f.status == "sent"), key=lambda f: f.sent_at)
    application.followup_count = len(sent)
    application.last_followup_at = sent[-1].sent_at if sent else None
    application.pending_followup_count = sum(1 for f in application.followups if f.status == "pending_approval")

    next_due = None
    if application.status == "applied" and not application.followup_opt_out and not has_open_draft(application):
        user = db.get(User, application.user_id)
        used = slots_used(application)
        if user is not None and user.followup_enabled and used < user.followup_max_count:
            anchor = followup_anchor(application)
            days = user.followup_interval_days if used else user.followup_first_days
            if anchor is not None:
                next_due = anchor + timedelta(days=days)
    application.next_followup_due_at = next_due
    return application


def create_application(db: Session, user_id: uuid.UUID, data: ApplicationCreate) -> Application:
    existing = db.scalar(
        select(Application).where(Application.user_id == user_id, Application.job_id == data.job_id)
    )
    if existing is not None:
        raise DuplicateApplicationError

    application = Application(
        user_id=user_id,
        job_id=data.job_id,
        resume_id=data.resume_id,
        status="saved",
    )
    db.add(application)
    db.flush()

    db.add(
        ApplicationStatusHistory(
            application_id=application.id, from_status=None, to_status="saved"
        )
    )
    db.commit()
    db.refresh(application)
    return _annotate_followup_fields(db, application)


def get_application(db: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> Application:
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user_id)
    )
    if application is None:
        raise ApplicationNotFoundError
    return _annotate_followup_fields(db, application)


def list_applications(
    db: Session,
    user_id: uuid.UUID,
    status_filter: str | None = None,
    job_id: uuid.UUID | None = None,
) -> list[Application]:
    stmt = select(Application).where(Application.user_id == user_id)
    if status_filter:
        stmt = stmt.where(Application.status == status_filter)
    if job_id:
        stmt = stmt.where(Application.job_id == job_id)
    applications = list(db.scalars(stmt))
    return [_annotate_followup_fields(db, a) for a in applications]


def update_application(
    db: Session, user_id: uuid.UUID, application_id: uuid.UUID, data: ApplicationUpdate
) -> Application:
    application = get_application(db, user_id, application_id)

    if data.status is not None and data.status != application.status:
        db.add(
            ApplicationStatusHistory(
                application_id=application.id,
                from_status=application.status,
                to_status=data.status,
            )
        )
        if data.status == "applied" and application.applied_at is None:
            application.applied_at = datetime.now(timezone.utc)
        application.status = data.status

    if data.notes is not None:
        application.notes = data.notes

    if data.followup_opt_out is not None:
        application.followup_opt_out = data.followup_opt_out

    db.commit()
    db.refresh(application)
    return _annotate_followup_fields(db, application)


def delete_application(db: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> None:
    application = get_application(db, user_id, application_id)
    db.delete(application)
    db.commit()


def list_followups(db: Session, user_id: uuid.UUID, application_id: uuid.UUID) -> list[FollowUp]:
    get_application(db, user_id, application_id)  # ownership check, raises if not found
    return list(
        db.scalars(
            select(FollowUp)
            .where(FollowUp.application_id == application_id)
            .order_by(FollowUp.sent_at)
        )
    )
