"""One-off: encrypt CV files stored before at-rest encryption was added.

Back up the storage folder and database first. Run from backend/:
    venv\Scripts\python.exe -m scripts.encrypt_existing_resumes
Each plain file is encrypted to "<name>.enc", the database row is updated, and the
plain file is removed only after that commit succeeds. Safe to run more than once."""
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.resume import Resume
from app.storage.file_storage import delete_stored_file, save_encrypted_file


def main() -> None:
    converted = missing = 0
    with SessionLocal() as db:
        for resume in db.scalars(select(Resume)):
            if resume.file_path.endswith(".enc"):
                continue
            source = Path(resume.file_path)
            if not source.exists():
                missing += 1
                continue
            old_path = resume.file_path
            resume.file_path = save_encrypted_file(source.read_bytes(), source.suffix)
            db.commit()
            delete_stored_file(old_path)
            converted += 1
    print(f"Encrypted {converted} file(s); {missing} row(s) point at missing files.")


if __name__ == "__main__":
    main()
