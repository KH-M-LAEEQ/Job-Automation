import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import AIParseError, AIRefusalError
from app.ai.parse_resume import parse_resume
from app.ai.schemas.resume_profile_schema import ResumeProfile
from app.models.resume import Resume
from app.models.user import User
from app.parsers.docx_parser import extract_text_from_docx
from app.parsers.pdf_parser import extract_text_from_pdf
from app.config import get_settings
from app.storage.file_storage import delete_stored_file, save_encrypted_file

# How many of a resume's AI-suggested target roles get joined into the profile's
# search_keywords. Matches crawl_service.MAX_ROLE_PHRASES - each role becomes a separate
# crawl query per source, so keep these two caps in sync (no point storing a role that the
# crawl will never actually search).
MAX_AUTO_SEARCH_ROLES = 4


class ResumeNotFoundError(Exception):
    pass


class ResumeFileError(Exception):
    """The upload is not a readable PDF/DOCX within the size limit."""


# A DOCX is a zip archive; refuse archives that expand to something absurd (zip bombs).
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024


def _detect_type(content: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        if b"%PDF-" not in content[:1024]:
            raise ResumeFileError("This file is not a valid PDF")
        return "pdf"
    if name.endswith(".docx"):
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise ResumeFileError("This file is not a valid DOCX document")
                if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED:
                    raise ResumeFileError("This DOCX document is too large to process")
        except zipfile.BadZipFile as e:
            raise ResumeFileError("This file is not a valid DOCX document") from e
        return "docx"
    raise ResumeFileError("Only PDF and DOCX files are supported")


def _extract_text(content: bytes, file_type: str) -> str:
    try:
        text = extract_text_from_pdf(content) if file_type == "pdf" else extract_text_from_docx(content)
    except Exception as e:
        raise ResumeFileError("Could not read text from this file. Try exporting it again as PDF or DOCX.") from e
    if not text.strip():
        raise ResumeFileError("No text found in this file. Scanned images are not supported.")
    return text


def _apply_profile_defaults(db: Session, user_id: uuid.UUID, profile: ResumeProfile) -> None:
    """Fill in blank profile fields (Settings page) from the primary resume. Never
    overwrites a value the user already set themselves."""
    user = db.get(User, user_id)
    if user is None:
        return
    # Suggestions are exposed on the parsed CV; explicitly saved preferences are untouched.
    if not user.country and profile.country:
        user.country = profile.country
    if not user.city and profile.city:
        user.city = profile.city
    if not user.search_keywords and profile.target_roles:
        user.search_keywords = ", ".join(profile.target_roles[:MAX_AUTO_SEARCH_ROLES])


def _run_parse(db: Session, resume: Resume) -> Resume:
    resume.parse_status = "parsing"
    db.commit()

    try:
        profile = parse_resume(resume.raw_text)
    except AIRefusalError as e:
        resume.parse_status = "failed"
        resume.parse_error = str(e)
    except AIParseError as e:
        resume.parse_status = "failed"
        resume.parse_error = str(e)
    else:
        resume.structured_profile = profile.model_dump()
        resume.parse_status = "parsed"
        resume.parse_error = None
        if resume.is_primary:
            _apply_profile_defaults(db, resume.user_id, profile)

    db.commit()
    db.refresh(resume)
    return resume


def upload_resume(db: Session, user_id: uuid.UUID, file: UploadFile) -> Resume:
    limit = get_settings().max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise ResumeFileError(f"Files must be {get_settings().max_upload_mb} MB or smaller")
    file_type = _detect_type(content, file.filename or "")
    raw_text = _extract_text(content, file_type)
    # Stored only once the file is known to be readable, so failed uploads leave nothing behind.
    file_path = save_encrypted_file(content, "." + file_type)

    is_first_resume = db.scalar(select(Resume.id).where(Resume.user_id == user_id).limit(1)) is None

    resume = Resume(
        user_id=user_id,
        original_filename=file.filename or "resume",
        file_path=file_path,
        file_type=file_type,
        raw_text=raw_text,
        parse_status="pending",
        is_primary=is_first_resume,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    return _run_parse(db, resume)


def get_resume(db: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    resume = db.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    if resume is None:
        raise ResumeNotFoundError
    return resume


def list_resumes(db: Session, user_id: uuid.UUID) -> list[Resume]:
    return list(db.scalars(select(Resume).where(Resume.user_id == user_id)))


def reparse_resume(db: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    resume = get_resume(db, user_id, resume_id)
    return _run_parse(db, resume)


def set_primary_resume(db: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
    resume = get_resume(db, user_id, resume_id)
    db.query(Resume).filter(Resume.user_id == user_id, Resume.id != resume_id).update(
        {"is_primary": False}
    )
    resume.is_primary = True
    db.commit()
    db.refresh(resume)
    return resume


def delete_resume(db: Session, user_id: uuid.UUID, resume_id: uuid.UUID) -> None:
    resume = get_resume(db, user_id, resume_id)
    file_path = resume.file_path
    db.delete(resume)
    db.commit()
    delete_stored_file(file_path)
