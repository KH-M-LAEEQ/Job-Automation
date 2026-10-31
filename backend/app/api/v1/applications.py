import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.application import ApplicationCreate, ApplicationRead, ApplicationUpdate
from app.schemas.followup import FollowUpApprove, FollowUpRead, FollowUpResolve
from app.services.email_account_service import EmailAccountNotFoundError
from app.services.followup_service import (
    FollowUpNotFoundError,
    FollowUpNotPendingError,
    approve_and_send,
    discard_followup,
    resolve_uncertain_send,
)
from app.services.application_service import (
    ApplicationNotFoundError,
    DuplicateApplicationError,
    create_application,
    delete_application,
    get_application,
    list_applications,
    list_followups,
    update_application,
)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create(
    data: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationRead:
    try:
        return create_application(db, current_user.id, data)
    except DuplicateApplicationError:
        raise HTTPException(status_code=409, detail="An application for this job already exists")


@router.get("", response_model=list[ApplicationRead])
def get_applications(
    status_filter: str | None = Query(None, alias="status"),
    job_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApplicationRead]:
    return list_applications(db, current_user.id, status_filter, job_id)


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application_by_id(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationRead:
    try:
        return get_application(db, current_user.id, application_id)
    except ApplicationNotFoundError:
        raise HTTPException(status_code=404, detail="Application not found")


@router.patch("/{application_id}", response_model=ApplicationRead)
def update(
    application_id: uuid.UUID,
    data: ApplicationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApplicationRead:
    try:
        return update_application(db, current_user.id, application_id, data)
    except ApplicationNotFoundError:
        raise HTTPException(status_code=404, detail="Application not found")


@router.get("/{application_id}/followups", response_model=list[FollowUpRead])
def get_application_followups(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FollowUpRead]:
    try:
        return list_followups(db, current_user.id, application_id)
    except ApplicationNotFoundError:
        raise HTTPException(status_code=404, detail="Application not found")


@router.post("/{application_id}/followups/{followup_id}/send", response_model=FollowUpRead)
def send_followup(
    application_id: uuid.UUID,
    followup_id: uuid.UUID,
    data: FollowUpApprove,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpRead:
    """Explicit user approval: the only path that emails an employer."""
    try:
        application = get_application(db, current_user.id, application_id)
        return approve_and_send(db, application, followup_id, data.subject, data.content)
    except (ApplicationNotFoundError, FollowUpNotFoundError):
        raise HTTPException(status_code=404, detail="Follow-up not found")
    except FollowUpNotPendingError:
        raise HTTPException(status_code=409, detail="This follow-up is no longer awaiting approval")
    except EmailAccountNotFoundError:
        raise HTTPException(status_code=400, detail="Connect an email account before sending")


@router.post("/{application_id}/followups/{followup_id}/discard", response_model=FollowUpRead)
def discard(
    application_id: uuid.UUID,
    followup_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpRead:
    try:
        application = get_application(db, current_user.id, application_id)
        return discard_followup(db, application, followup_id)
    except (ApplicationNotFoundError, FollowUpNotFoundError):
        raise HTTPException(status_code=404, detail="Follow-up not found")
    except FollowUpNotPendingError:
        raise HTTPException(status_code=409, detail="This follow-up is no longer awaiting approval")


@router.post("/{application_id}/followups/{followup_id}/resolve", response_model=FollowUpRead)
def resolve(
    application_id: uuid.UUID,
    followup_id: uuid.UUID,
    data: FollowUpResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowUpRead:
    """Record whether an interrupted send went out, after the user checks their Sent folder."""
    try:
        application = get_application(db, current_user.id, application_id)
        return resolve_uncertain_send(db, application, followup_id, data.sent)
    except (ApplicationNotFoundError, FollowUpNotFoundError):
        raise HTTPException(status_code=404, detail="Follow-up not found")
    except FollowUpNotPendingError:
        raise HTTPException(status_code=409, detail="This follow-up is not awaiting confirmation")


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        delete_application(db, current_user.id, application_id)
    except ApplicationNotFoundError:
        raise HTTPException(status_code=404, detail="Application not found")
