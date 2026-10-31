# ApplyPilot

Job discovery and application tracking with CV and portfolio based search planning,
structured vacancy enrichment, matching, and optional opportunity notifications.

## Stack

- Backend: FastAPI, PostgreSQL, SQLAlchemy/Alembic, APScheduler, NVIDIA LLM API, Playwright.
- Frontend: Next.js, TypeScript, Tailwind, React Query.
- Discovery: existing job boards and company adapters, plus Tavily web vacancy search.

## Local development (PowerShell)

Preserve existing `.env` files, JWT secrets, encryption keys, and database volumes.
For a new installation, copy the example environment files and configure them first.
NVIDIA credentials enable AI extraction and matching; Tavily enables general web
search. The backend refuses to start without a random `JWT_SECRET` (32+ characters,
not the example placeholder), `EMAIL_ENCRYPTION_KEY` and `RESUME_ENCRYPTION_KEY`.

From the project directory, start the database:

```powershell
docker compose up -d postgres
```

Back up any existing database before applying migrations. Then, from `backend`:

```powershell
# Create a virtual environment only if one does not already exist.
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m playwright install chromium
.\venv\Scripts\python.exe -m alembic upgrade head
# One-off, after backing up storage\resumes and the database: encrypt CVs uploaded earlier.
.\venv\Scripts\python.exe -m scripts.encrypt_existing_resumes
.\venv\Scripts\python.exe -m uvicorn app.main:app --port 8010
```

With `RUN_SCHEDULER=true` (the default) the API process also runs background work. To
run it separately, set `RUN_SCHEDULER=false` for the API and start
`.\venv\Scripts\python.exe -m app.worker`. `docker compose up` does this automatically
(`backend` + `worker` services; add `-f docker-compose.dev.yml` for reloading dev servers).

From `frontend`:

```powershell
npm ci
npm run dev -- --port 3010
```

Set backend `CORS_ORIGINS=http://localhost:3010` and frontend
`NEXT_PUBLIC_API_URL=http://localhost:8010/api/v1`.
Backend API documentation: http://localhost:8010/docs
Frontend: http://localhost:3010

The latest migration is `c1d2e3f4a5b6` (follow-up approval). See `UPGRADE.md` for the
implementation, verification results, and deployment limitations.

Employer follow-ups are never sent automatically: the scheduler prepares drafts, and each
one is emailed only after you review and approve it on the job page.

## Checks

From `backend`: `.\venv\Scripts\python.exe -m unittest discover -s tests -q`.
From `frontend`: `npm run lint`, `npm run typecheck`, and `npm run build`.
Live and paid integration tests are opt-in; ordinary tests mock external services.
PostgreSQL integration tests run when `TEST_DATABASE_URL` equals `DATABASE_URL` (a disposable,
migrated database). CI (`.github/workflows/ci.yml`) runs everything against Postgres 16.
