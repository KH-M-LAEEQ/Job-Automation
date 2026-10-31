"""Real-PostgreSQL checks: migrations, advisory locks across connections, JSONB storage and
the follow-up claim. Run against a disposable database that has had `alembic upgrade head`:

    set DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/applypilot_test
    set TEST_DATABASE_URL=%DATABASE_URL%
    python -m unittest tests.test_postgres_integration

CI runs these with a Postgres service container."""
import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

TEST_DB = os.environ.get('TEST_DATABASE_URL')


@unittest.skipUnless(TEST_DB and TEST_DB == os.environ.get('DATABASE_URL'),
                     'Set TEST_DATABASE_URL and DATABASE_URL to the same disposable PostgreSQL database')
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import inspect
        from app.database import SessionLocal, engine
        cls.engine, cls.Session = engine, SessionLocal
        columns = {c['name'] for c in inspect(engine).get_columns('followups')}
        assert {'recipient', 'decided_at'} <= columns, 'run alembic upgrade head first'

    def setUp(self):
        from app.models.user import User
        self.db = self.Session()
        self.user = User(email=f'pg-{uuid.uuid4()}@example.com', hashed_password='x', preferences={})
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.rollback()
        self.db.delete(self.db.merge(self.user))
        self.db.commit()
        self.db.close()

    def test_advisory_lock_is_exclusive_across_connections(self):
        from app.services.discovery_lock import discovery_lock
        key = f'test-{uuid.uuid4()}'
        inner = []
        with discovery_lock(key) as first:
            thread = threading.Thread(target=lambda: inner.append(discovery_lock(key).__enter__()))
            thread.start()
            thread.join()
        self.assertTrue(first)
        self.assertEqual(inner, [False])
        with discovery_lock(key) as again:
            self.assertTrue(again)

    def test_jsonb_candidate_storage_and_distinct_openings(self):
        from app.services.discovery_store import store_candidate
        base = {'source': 'greenhouse', 'title': 'Software Engineer', 'company': 'Acme', 'location': 'Lahore',
                'description': 'Backend role with Python and PostgreSQL'}
        a, created_a = store_candidate(self.db, self.user.id, {**base, 'external_id': 'gh:1', 'url': 'https://example.com/jobs/1'}, {})
        b, created_b = store_candidate(self.db, self.user.id, {**base, 'external_id': 'gh:2', 'url': 'https://example.com/jobs/2'}, {})
        self.db.commit()
        self.assertTrue(created_a and created_b)
        self.db.expire_all()
        self.assertEqual(self.db.get(type(a), a.id).research['source'], 'greenhouse')

    def test_concurrent_approvals_send_once(self):
        from app.models.application import Application
        from app.models.followup import FollowUp
        from app.models.job import Job
        from app.services import followup_service
        job = Job(user_id=self.user.id, source_type='text', raw_input_text='Role', extraction_status='extracted', requirements=[])
        self.db.add(job)
        self.db.flush()
        application = Application(user_id=self.user.id, job_id=job.id, status='applied',
                                  applied_at=datetime.now(timezone.utc) - timedelta(days=10))
        self.db.add(application)
        self.db.flush()
        draft = FollowUp(application_id=application.id, status='pending_approval', recipient='hr@example.com',
                         subject='Following up', content='Hello')
        self.db.add(draft)
        self.db.commit()

        outcomes = []

        def approve():
            with self.Session() as db:
                app_row = db.get(Application, application.id)
                try:
                    outcomes.append(followup_service.approve_and_send(db, app_row, draft.id).status)
                except followup_service.FollowUpNotPendingError:
                    outcomes.append('refused')

        with patch.object(followup_service, 'get_email_account', return_value=MagicMock()), \
             patch.object(followup_service, 'send_email') as send:
            threads = [threading.Thread(target=approve) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(sorted(outcomes), ['refused', 'refused', 'refused', 'sent'])


if __name__ == '__main__':
    unittest.main()
