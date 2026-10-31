"""Employer follow-ups: the scheduler only prepares drafts; nothing is emailed until the
user approves a specific draft. Sending claims the draft in the database before the SMTP
call, so a crash or error can never cause the same follow-up to be sent twice."""
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.generate_content import generate_followup_email
from app.ai.schemas.resume_profile_schema import ResumeProfile
from app.database import SessionLocal
from app.models.application import Application
from app.models.followup import FollowUp
from app.models.job import Job
from app.models.resume import Resume
from app.models.user import User
from app.services.email_account_service import EmailAccountNotFoundError, get_email_account
from app.services.email_service import EmailSendError, send_email
from app.services.job_mapping import job_to_extraction

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
# Statuses that use up one of the application's follow-up slots.
COUNTED_STATUSES = ("pending_approval", "sending", "sent", "discarded")


class FollowUpNotFoundError(Exception):
    pass


class FollowUpNotPendingError(Exception):
    pass


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def followup_anchor(application: Application) -> datetime | None:
    """When the follow-up clock last restarted: the latest decision on a follow-up,
    or the application date when there has been none."""
    decided = [_aware(f.decided_at or f.sent_at) for f in application.followups if f.status in ("sent", "discarded", "failed")]
    return max(decided) if decided else _aware(application.applied_at)


def slots_used(application: Application) -> int:
    return sum(1 for f in application.followups if f.status in COUNTED_STATUSES)


def has_open_draft(application: Application) -> bool:
    return any(f.status in ("pending_approval", "sending") for f in application.followups)


def _resume_for_application(
    db: Session, user_id: uuid.UUID, application: Application
) -> Resume | None:
    if application.resume_id is not None:
        return db.get(Resume, application.resume_id)
    return db.scalar(
        select(Resume).where(
            Resume.user_id == user_id,
            Resume.is_primary.is_(True),
            Resume.parse_status == "parsed",
        )
    )


def _eligible_applications(db: Session, user: User) -> list[Application]:
    now = datetime.now(timezone.utc)
    candidates = db.scalars(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .where(
            Application.user_id == user.id,
            Application.status == "applied",
            Application.followup_opt_out.is_(False),
            Job.contact_email.isnot(None),
        )
    )

    due: list[Application] = []
    for application in candidates:
        if has_open_draft(application) or slots_used(application) >= user.followup_max_count:
            continue
        anchor = followup_anchor(application)
        if anchor is None:
            continue
        threshold_days = user.followup_interval_days if slots_used(application) else user.followup_first_days
        if (now - anchor).days >= threshold_days:
            due.append(application)
    return due


def draft_followups_for_user(db: Session, user: User) -> list[FollowUp]:
    """Prepare drafts for due applications. Sends nothing."""
    if get_email_account(db, user.id) is None:
        return []

    drafts: list[FollowUp] = []
    for application in _eligible_applications(db, user):
        try:
            job = db.get(Job, application.job_id)
            recipient = (job.contact_email or "").strip()
            if not _EMAIL.match(recipient):
                continue
            resume = _resume_for_application(db, user.id, application)
            if resume is None or resume.structured_profile is None:
                continue
            profile = ResumeProfile(**resume.structured_profile)
            applied_at = _aware(application.applied_at)
            days_since_applied = (datetime.now(timezone.utc) - applied_at).days if applied_at else 0
            subject, body = generate_followup_email(
                profile, job_to_extraction(job), days_since_applied, slots_used(application) + 1
            )
            if not subject or not body:
                continue
            draft = FollowUp(application_id=application.id, status="pending_approval",
                             recipient=recipient, subject=subject[:300], content=body)
            application.followups.append(draft)
            db.commit()
            drafts.append(draft)
        except Exception:
            # One bad application never blocks the others; nothing was sent.
            db.rollback()
            log.exception("Could not draft follow-up for application %s", application.id)
    return drafts


def approve_and_send(
    db: Session, application: Application, followup_id: uuid.UUID,
    subject: str | None = None, content: str | None = None,
) -> FollowUp:
    followup = db.scalar(select(FollowUp).where(FollowUp.id == followup_id, FollowUp.application_id == application.id))
    if followup is None:
        raise FollowUpNotFoundError
    account = get_email_account(db, application.user_id)
    if account is None:
        raise EmailAccountNotFoundError

    values = {"status": "sending", "decided_at": datetime.now(timezone.utc)}
    if subject:
        values["subject"] = subject
    if content:
        values["content"] = content
    # Atomic claim: only one request can move this draft out of pending_approval.
    claimed = db.execute(
        update(FollowUp)
        .where(FollowUp.id == followup.id, FollowUp.status == "pending_approval")
        .values(**values)
    ).rowcount
    db.commit()
    if not claimed:
        raise FollowUpNotPendingError
    db.refresh(followup)

    try:
        send_email(account, followup.recipient, followup.subject, followup.content)
    except EmailSendError as e:
        followup.status = "failed"
        followup.error = str(e)[:1000]
        log.warning("Follow-up %s failed to send: %s", followup.id, e)
    else:
        followup.status = "sent"
        followup.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(followup)
    return followup


def discard_followup(db: Session, application: Application, followup_id: uuid.UUID) -> FollowUp:
    followup = db.scalar(select(FollowUp).where(FollowUp.id == followup_id, FollowUp.application_id == application.id))
    if followup is None:
        raise FollowUpNotFoundError
    claimed = db.execute(
        update(FollowUp)
        .where(FollowUp.id == followup.id, FollowUp.status == "pending_approval")
        .values(status="discarded", decided_at=datetime.now(timezone.utc))
    ).rowcount
    db.commit()
    if not claimed:
        raise FollowUpNotPendingError
    db.refresh(followup)
    return followup


def resolve_uncertain_send(db: Session, application: Application, followup_id: uuid.UUID, was_sent: bool) -> FollowUp:
    """A send interrupted mid-way (crash, timeout) stays in "sending" because the email may
    have left. Only the user can tell, from their mailbox's Sent folder; never retried here."""
    followup = db.scalar(select(FollowUp).where(FollowUp.id == followup_id, FollowUp.application_id == application.id))
    if followup is None:
        raise FollowUpNotFoundError
    values = {"status": "sent"} if was_sent else {"status": "failed", "error": "Not sent (confirmed by user)"}
    claimed = db.execute(
        update(FollowUp).where(FollowUp.id == followup.id, FollowUp.status == "sending").values(**values)
    ).rowcount
    db.commit()
    if not claimed:
        raise FollowUpNotPendingError
    db.refresh(followup)
    return followup


def _run_all_followups() -> None:
    """Entry point for the scheduler: prepare due follow-up drafts for users who opted in."""
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User).where(User.followup_enabled.is_(True))))
        for user in users:
            try:
                draft_followups_for_user(db, user)
            except Exception:
                db.rollback()
                log.exception("Follow-up drafting failed for user %s", user.id)
    finally:
        db.close()


def run_all_followups() -> None:
    from app.services.discovery_lock import discovery_lock
    with discovery_lock('employer-followups') as acquired:
        if acquired:
            _run_all_followups()
