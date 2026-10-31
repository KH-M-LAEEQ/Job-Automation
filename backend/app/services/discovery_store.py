import hashlib
import json
from sqlalchemy import select, or_

from app.models.job import Job
from app.services.job_mapping import html_to_text, repair_text
from app.services.job_quality import canonical_url, fingerprint, now_iso, fit_column


def store_candidate(db, user_id, raw, plan):
    raw = {k: repair_text(v) if isinstance(v, str) and k not in ('url', 'external_id') else v for k, v in raw.items()}
    url = None if raw.get("shared_listing") else canonical_url(raw.get("url"))
    fp = fingerprint(raw.get('title'), raw.get('company'), raw.get('location'))
    external = raw['external_id']
    if len(external) > 255:
        external = external[:60] + ':' + hashlib.sha256(external.encode()).hexdigest()
    # Only exact identities merge here. Title/company/location fingerprints are a soft
    # signal (reconcile_identity) - two openings with the same title at the same office
    # are common and must stay separate rows.
    conditions = [Job.external_id == external]
    if url:
        conditions.append(Job.canonical_url == url)
    job = db.scalar(select(Job).where(Job.user_id == user_id, or_(*conditions)))
    created = job is None
    body = html_to_text(raw.get('description')) or raw.get('title') or ''
    digest = hashlib.sha256(body.encode()).hexdigest()
    if created:
        job = Job(user_id=user_id, source_type='crawl', external_id=external, source_url=raw.get('url'),
                  canonical_url=url, fingerprint=fp, raw_input_text=body, extraction_status='pending', requirements=[])
        db.add(job)
    research = dict(job.research or {})
    # Separate source snippet hash from enriched page hash to avoid endless rescoring.
    metadata_hash = hashlib.sha256(json.dumps({field: raw.get(field) for field in ('title', 'company', 'location', 'employment_type', 'work_mode', 'posted_at', 'remote_eligibility')}, sort_keys=True).encode()).hexdigest()
    metadata_changed = research.get('source_metadata_hash') != metadata_hash
    changed = research.get('source_content_hash') != digest or metadata_changed
    if changed:
        if created or len(body) >= len(job.raw_input_text or ''):
            job.raw_input_text = body
        for field in ('title', 'company', 'location', 'salary_range', 'employment_type', 'work_mode'):
            if raw.get(field):
                setattr(job, field, fit_column(field, raw[field]))
        research.update(source_content_hash=digest, source_metadata_hash=metadata_hash, content_updated_at=now_iso(), enrichment_state='pending')
        job.extraction_status = 'pending'
    research.setdefault('first_discovered_at', now_iso())
    research.update(last_seen_at=now_iso(), search_plan=plan, source=raw.get('source', 'unknown'))
    research['shared_listing'] = bool(raw.get('shared_listing'))
    if raw.get('discovered_from'):
        research['discovered_from'] = raw['discovered_from']
    sources = list(research.get('sources', []))
    provenance = {'source': raw.get('source'), 'id': external, 'url': raw.get('url')}
    if provenance not in sources:
        sources.append(provenance)
    research['sources'] = sources[:20]
    research.setdefault('state', 'unknown')
    research.setdefault('verification_status', 'unverified')
    if raw.get('posted_at'):
        research['posted_at'] = raw['posted_at']
        research['source_posted_at'] = raw['posted_at']
    if raw.get('application_url'):
        # Apply link published by the employer's own job-board feed: a candidate for the
        # reachability check when the rendered page hides its apply button. Still checked.
        research['feed_application_url'] = raw['application_url']
    if raw.get('remote_eligibility'):
        research['remote_eligibility'] = raw['remote_eligibility']
    job.research = research
    db.flush()  # next result in this batch can find the inserted identity
    return job, created


def _same_listing_source(a, b):
    """Two postings from the same source with different source IDs are different openings,
    even when title, company and location match."""
    source_a, source_b = (a.research or {}).get('source'), (b.research or {}).get('source')
    return bool(source_a) and source_a == source_b and a.external_id != b.external_id


def reconcile_identity(db, job):
    """Mark enriched cross-source duplicates without deleting IDs or application history."""
    data = dict(job.research or {})
    data.pop('duplicate_of', None)
    original = None
    if job.canonical_url:
        original = db.scalar(select(Job).where(Job.user_id == job.user_id, Job.id != job.id,
                                               Job.canonical_url == job.canonical_url).order_by(Job.created_at, Job.id))
    if original is None and job.fingerprint:
        db.flush()
        for other in db.scalars(select(Job).where(Job.user_id == job.user_id, Job.id != job.id,
                                                  Job.fingerprint == job.fingerprint).order_by(Job.created_at, Job.id)):
            if not _same_listing_source(job, other):
                original = other
                break
    if original is not None and (original.created_at, str(original.id)) < (job.created_at, str(job.id)):
        data['duplicate_of'] = str(original.id)
    job.research = data
