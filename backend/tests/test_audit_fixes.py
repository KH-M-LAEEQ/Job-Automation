"""Regression tests for the October 2026 production-readiness audit findings."""
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('EMAIL_ENCRYPTION_KEY', 'ZmFrZWtleWZha2VrZXlmYWtla2V5ZmFrZWtleWZha2U=')

from app.config import Settings
from app.services.job_quality import canonical_url, eligibility, fingerprint, verified_contact_email
from app.services.recommendation_policy import candidate_experience_years, known_mismatches, mandatory_evidence


def _job(text):
    return SimpleNamespace(requirements=[text], raw_input_text='')


PROFILE = {'experience': [{'start_date': '2024-01', 'end_date': 'present'}],
           'education': [{'degree': 'BS Computer Science', 'school': 'X'}]}


class RequirementDetectionTests(unittest.TestCase):
    def test_years_phrasings(self):
        for text in ('5+ yrs experience in backend development', 'At least three (3) years experience required',
                     "Minimum 4 years' professional software experience", '3-5 years of relevant industry experience'):
            _, concerns = mandatory_evidence(_job(text), PROFILE)
            self.assertTrue(any('years' in c for c in concerns), text)

    def test_zero_minimum_and_optional_are_not_concerns(self):
        for text in ('0-2 years experience, fresh graduates welcome', 'Experience with Kubernetes is a plus'):
            self.assertEqual(mandatory_evidence(_job(text), PROFILE)[1], [], text)

    def test_work_authorization_phrasings(self):
        for text in ('Must hold a valid US work permit / green card', 'Must be eligible to work in the UK',
                     'We are unable to sponsor visas for this role'):
            _, concerns = mandatory_evidence(_job(text), PROFILE)
            self.assertTrue(any('authorization' in c for c in concerns), text)

    def test_degree_requirement(self):
        _, concerns = mandatory_evidence(_job("Master's degree in Computer Science required"), PROFILE)
        self.assertTrue(any('master' in c for c in concerns))
        _, concerns = mandatory_evidence(_job("BS/MS degree in Computer Science required"), PROFILE)
        self.assertFalse(any('degree' in c for c in concerns))

    def test_known_mismatch_for_years_and_degree(self):
        mismatches = known_mismatches(_job('Minimum 8 years of experience; PhD degree required'), PROFILE)
        self.assertEqual(len(mismatches), 2)


class ExperienceYearsTests(unittest.TestCase):
    def test_gaps_are_not_counted(self):
        profile = {'experience': [{'start_date': '2015', 'end_date': '2015'},
                                  {'start_date': f'{datetime.now(timezone.utc).year - 2}-01', 'end_date': 'present'}]}
        self.assertLessEqual(candidate_experience_years(profile), 3)

    def test_overlapping_roles_merge(self):
        profile = {'experience': [{'start_date': 'Jan 2018', 'end_date': 'Dec 2021'},
                                  {'start_date': '2019-06', 'end_date': '2020-06'}]}
        self.assertEqual(candidate_experience_years(profile), 4)

    def test_unknown_stays_unknown(self):
        self.assertIsNone(candidate_experience_years({'experience': [{'start_date': None}]}))


class SeniorityTests(unittest.TestCase):
    def job(self, title):
        return SimpleNamespace(title=title, company='Acme', raw_input_text='', research={'verification_status': 'page_checked'},
                               employment_type=None, work_mode='onsite', location='Lahore', requirements=[])

    def test_senior_variants_rejected_for_entry_level(self):
        for title in ('Sr. Software Engineer', 'Software Engineer III', 'Engineering Manager', 'Solutions Architect'):
            self.assertIn('Seniority does not match', eligibility(self.job(title), {'seniority': ['entry level']})[0], title)

    def test_associate_roles_kept(self):
        for title in ('Associate Product Manager', 'Junior Software Engineer', 'Software Engineer II'):
            self.assertNotIn('Seniority does not match', eligibility(self.job(title), {'seniority': ['entry level']})[0], title)


class IdentityTests(unittest.TestCase):
    def test_tracking_params_removed(self):
        self.assertEqual(canonical_url('https://Example.com/jobs/1/?ref=li&gh_src=abc&utm_source=x'),
                         canonical_url('https://example.com/jobs/1'))

    def test_meaningful_params_kept(self):
        self.assertNotEqual(canonical_url('https://example.com/job?id=1'), canonical_url('https://example.com/job?id=2'))

    def test_fingerprint_normalizes_wording(self):
        base = fingerprint('Software Engineer', 'Acme Pvt Ltd', 'Lahore')
        for title, location in (('Software Engineer (Remote)', 'Lahore, Pakistan'), ('Software Engineer - Lahore', 'Lahore'),
                                ('Software Engineer (m/f/d)', 'Lahore'), ('Software Engineer [Full-time]', 'Lahore, PK')):
            self.assertEqual(base, fingerprint(title, 'Acme', location), title)
        self.assertNotEqual(base, fingerprint('Data Engineer', 'Acme', 'Lahore'))

    def test_fingerprint_keeps_team_and_specialism(self):
        self.assertNotEqual(fingerprint('Software Engineer (Backend)', 'Acme', 'Lahore'),
                            fingerprint('Software Engineer (Mobile)', 'Acme', 'Lahore, PK'))

    def test_contact_email_must_appear_in_posting(self):
        text = 'Send your CV to careers@acme.example before Friday.'
        self.assertEqual(verified_contact_email('careers@acme.example', text), 'careers@acme.example')
        self.assertIsNone(verified_contact_email('attacker@evil.example', text))
        self.assertIsNone(verified_contact_email('not an email', 'not an email'))


class ConfigTests(unittest.TestCase):
    def test_placeholder_and_short_secrets_refused(self):
        for secret in ('', 'dev-secret-change-me', 'change-me-to-a-long-random-string', 'short'):
            with self.assertRaises(RuntimeError):
                Settings(jwt_secret=secret, email_encryption_key='x', resume_encryption_key='x').assert_secure()

    def test_strong_secret_accepted(self):
        Settings(jwt_secret='q' * 20 + 'Z9x' * 10, email_encryption_key='x', resume_encryption_key='x').assert_secure()

    def test_resume_key_required(self):
        with self.assertRaises(RuntimeError):
            Settings(jwt_secret='q' * 20 + 'Z9x' * 10, email_encryption_key='x', resume_encryption_key='').assert_secure()


class SmtpValidationTests(unittest.TestCase):
    def test_private_hosts_and_odd_ports_refused(self):
        from app.services.email_service import validate_smtp_server
        for host, port in (('127.0.0.1', 587), ('10.0.0.5', 587), ('169.254.169.254', 25), ('8.8.8.8', 5432)):
            with self.assertRaises(ValueError):
                validate_smtp_server(host, port)

    def test_password_never_sent_without_tls(self):
        from app.services import email_service
        account = SimpleNamespace(from_name=None, from_email='me@example.com', smtp_host='8.8.8.8', smtp_port=587,
                                  use_tls=False, encrypted_password='x', smtp_username='me')
        with patch.object(email_service, 'decrypt_secret', return_value='pw'), patch.object(email_service.smtplib, 'SMTP') as smtp:
            with self.assertRaises(email_service.EmailSendError):
                email_service.send_email(account, 'hr@example.com', 'S', 'B')
            smtp.assert_not_called()


class UploadTests(unittest.TestCase):
    def setUp(self):
        from cryptography.fernet import Fernet
        from app.storage import file_storage
        self.dir = tempfile.mkdtemp()
        self.patches = [patch.object(file_storage.settings, 'file_storage_dir', self.dir),
                        patch.object(file_storage.settings, 'resume_encryption_key', Fernet.generate_key().decode())]
        for p in self.patches:
            p.start()
        file_storage._fernet.cache_clear()

    def tearDown(self):
        from app.storage import file_storage
        for p in self.patches:
            p.stop()
        file_storage._fernet.cache_clear()

    def upload(self, name, content):
        from app.services import resume_service
        return resume_service.upload_resume(None, None, SimpleNamespace(filename=name, file=io.BytesIO(content)))

    def test_wrong_content_and_oversize_rejected_without_leaving_files(self):
        from app.services.resume_service import ResumeFileError
        for name, content in (('cv.pdf', b'<script>x</script>'), ('cv.docx', b'not a zip'), ('cv.exe', b'MZ'),
                              ('cv.pdf', b'%PDF-1.4\n' + b'0' * (11 * 1024 * 1024)), ('cv.pdf', b'%PDF-1.4 broken')):
            with self.assertRaises(ResumeFileError, msg=name):
                self.upload(name, content)
        self.assertEqual(os.listdir(self.dir), [])

    def test_files_are_encrypted_and_deletable(self):
        from app.storage.file_storage import delete_stored_file, read_stored_file, save_encrypted_file
        path = save_encrypted_file(b'%PDF-1.4 secret CV text', '.pdf')
        self.assertTrue(path.endswith('.pdf.enc'))
        with open(path, 'rb') as f:
            self.assertNotIn(b'secret CV text', f.read())
        self.assertEqual(read_stored_file(path), b'%PDF-1.4 secret CV text')
        delete_stored_file(path)
        self.assertFalse(os.path.exists(path))

    def test_delete_refuses_paths_outside_storage(self):
        from app.storage.file_storage import delete_stored_file
        outside = tempfile.NamedTemporaryFile(delete=False)
        outside.close()
        delete_stored_file(outside.name)
        self.assertTrue(os.path.exists(outside.name))
        os.unlink(outside.name)


class ScoreCapTests(unittest.TestCase):
    """Second-audit regressions: the hard cap must only fire on real applicant requirements."""

    def score(self, summary, requirements, matched=('Python',)):
        from app.ai import score_match as sm
        from app.ai.schemas.job_extraction_schema import JobExtraction
        from app.ai.schemas.match_score_schema import MatchScore
        from app.ai.schemas.resume_profile_schema import ResumeProfile
        candidate = ResumeProfile(summary='Backend developer', skills=['Python', 'React.js', 'JavaScript'],
                                  experience=[{'title': 'Dev', 'company': 'X', 'start_date': '2023-01', 'end_date': 'present'}],
                                  education=[{'degree': 'BS Computer Science', 'school': 'Y'}])
        job = JobExtraction(title='Python Developer', requirements=list(requirements), description_summary=summary)
        fake = MatchScore(score=85, matched_skills=list(matched), missing_skills=[], rationale='Good fit.')
        with patch.object(sm, 'parse_structured', return_value=fake):
            return sm.score_match(candidate, job)

    def test_company_history_is_not_a_requirement(self):
        for summary in ('Acme is a software house with over 20 years of experience in fintech.',
                        'We have 15 years of experience building banking software.'):
            self.assertGreater(self.score(summary, ['Python']).score, 69, summary)

    def test_applicant_requirement_in_prose_still_counts(self):
        result = self.score('You will need at least 8 years of experience with Python.', ['Python'])
        self.assertEqual(result.score, 40)

    def test_equivalent_experience_is_not_a_hard_mismatch(self):
        result = self.score('Build APIs.', ["Master's degree in CS or equivalent practical experience required"])
        self.assertGreater(result.score, 40)
        self.assertLessEqual(result.score, 69)

    def test_skill_spelling_variants_are_kept(self):
        result = self.score('Build APIs.', ['Python', 'React', 'JS'], matched=('Python', 'React.js', 'JavaScript', 'Kotlin'))
        self.assertEqual(result.matched_skills, ['Python', 'React.js', 'JavaScript'])


class SeniorityWordingTests(unittest.TestCase):
    def test_ambiguous_words_need_context(self):
        from app.services.job_quality import too_senior
        cases = {'Staff Accountant': False, 'Lead Generation Specialist': False, 'Associate Product Manager': False,
                 'Senior Intern': False, 'Graduate Trainee Engineer': False, 'Senior Associate': True,
                 'Staff Software Engineer': True, 'Tech Lead': True, 'Software Engineer V': True, 'Engineering Manager': True}
        for title, expected in cases.items():
            self.assertEqual(too_senior(title), expected, title)


class ScraperTitleTests(unittest.TestCase):
    def test_abbreviations_match_page_wording(self):
        from app.services.job_sources.generic_company_scraper import _normalize
        page = _normalize('Open roles: Senior Software Engineer - Lahore; Junior Dev (Python)')
        for title in ('Sr. Software Engineer', 'Senior SW Engineer', 'Jr Developer'):
            self.assertIn(_normalize(title), page, title)
        self.assertNotIn(_normalize('Senior Data Scientist'), page)


class RateLimitTests(unittest.TestCase):
    def test_blocks_after_limit(self):
        from app.core.rate_limit import RateLimiter
        limiter = RateLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            limiter.hit('k')
        self.assertTrue(limiter.blocked('k'))
        limiter.reset('k')
        self.assertFalse(limiter.blocked('k'))


class ApiHardeningTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)  # no lifespan: no scheduler

    def test_wrong_passwords_from_one_address_do_not_lock_out_the_owner(self):
        from fastapi.testclient import TestClient
        from app.core import rate_limit
        from app.services.auth_service import InvalidCredentialsError
        rate_limit.login_failures_by_client_account.reset('203.0.113.9|victim@example.com')
        attacker = TestClient(self.app, client=('203.0.113.9', 5000))
        owner = TestClient(self.app, client=('198.51.100.7', 5000))
        body = {'email': 'victim@example.com', 'password': 'wrong-pass-1'}
        with patch('app.api.v1.auth.authenticate_user', side_effect=InvalidCredentialsError):
            codes = [attacker.post('/api/v1/auth/login', json=body).status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)
        user = SimpleNamespace(id=__import__('uuid').uuid4())
        with patch('app.api.v1.auth.authenticate_user', return_value=user):
            self.assertEqual(owner.post('/api/v1/auth/login', json=body).status_code, 200)

    def test_health_hides_error_details(self):
        from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
        from app import scheduler
        with self.assertLogs('app.scheduler', 'ERROR'):
            scheduler._record(JobExecutionEvent(EVENT_JOB_ERROR, 'probe_task', None, None,
                                                exception=RuntimeError('db.internal:5432 password failed')))
        body = self.client.get('/health').text
        scheduler.status.pop('probe_task', None)
        self.assertNotIn('db.internal', body)
        self.assertIn('probe_task', body)

    def test_chunked_upload_is_cut_off_at_the_limit(self):
        def chunks():
            for _ in range(12):
                yield b'0' * (1024 * 1024)
        response = self.client.post('/api/v1/resumes', content=chunks(),
                                    headers={'content-type': 'multipart/form-data; boundary=x'})
        self.assertEqual(response.status_code, 413)


class UncertainSendTests(unittest.TestCase):
    def test_user_resolves_interrupted_send_once(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.dialects.postgresql import JSONB
        compiles(JSONB, 'sqlite')(lambda type_, compiler, **kw: 'JSON')
        from app.database import Base
        import app.models  # noqa: F401
        from app.models.application import Application
        from app.models.followup import FollowUp
        from app.models.job import Job
        from app.models.user import User
        from app.services import followup_service
        engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        db = Session(engine, expire_on_commit=False)
        user = User(email='u@example.com', hashed_password='x', preferences={})
        db.add(user)
        db.flush()
        job = Job(user_id=user.id, source_type='text', raw_input_text='Role', extraction_status='extracted', requirements=[])
        db.add(job)
        db.flush()
        application = Application(user_id=user.id, job_id=job.id, status='applied')
        db.add(application)
        db.flush()
        stuck = FollowUp(application_id=application.id, status='sending', recipient='hr@example.com', subject='S', content='B')
        draft = FollowUp(application_id=application.id, status='pending_approval', recipient='hr@example.com', subject='S', content='B')
        db.add_all([stuck, draft])
        db.commit()
        self.assertEqual(followup_service.resolve_uncertain_send(db, application, stuck.id, True).status, 'sent')
        with self.assertRaises(followup_service.FollowUpNotPendingError):
            followup_service.resolve_uncertain_send(db, application, stuck.id, False)
        with self.assertRaises(followup_service.FollowUpNotPendingError):
            followup_service.resolve_uncertain_send(db, application, draft.id, True)  # drafts must be approved instead
        db.close()


if __name__ == '__main__':
    unittest.main()
