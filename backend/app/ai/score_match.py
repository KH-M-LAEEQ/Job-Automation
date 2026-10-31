import re

from app.ai.client import parse_structured
from app.ai.prompts.match_scoring import MATCH_SCORING_SYSTEM_PROMPT
from app.ai.schemas.job_extraction_schema import JobExtraction
from app.ai.schemas.match_score_schema import MatchScore
from app.ai.schemas.resume_profile_schema import ResumeProfile
from app.config import get_settings

settings = get_settings()


_STOPWORDS = {'and', 'or', 'the', 'of', 'in', 'with', 'for', 'to', 'a', 'an', 'experience', 'skills', 'knowledge'}
# Common spellings of the same technology; each group is treated as one skill.
_SYNONYMS = [
    {'javascript', 'js', 'ecmascript'}, {'typescript', 'ts'}, {'react', 'reactjs'}, {'node', 'nodejs'},
    {'vue', 'vuejs'}, {'angular', 'angularjs'}, {'next', 'nextjs'}, {'express', 'expressjs'},
    {'postgresql', 'postgres', 'psql'}, {'mongodb', 'mongo'}, {'golang', 'go'}, {'kubernetes', 'k8s'},
    {'csharp', 'c#'}, {'cpp', 'c++'}, {'aws', 'amazon web services'}, {'gcp', 'google cloud'},
    {'ml', 'machine learning'}, {'ai', 'artificial intelligence'}, {'nlp', 'natural language processing'},
    {'llm', 'llms', 'large language models'}, {'ci/cd', 'cicd', 'continuous integration'},
]


def _canonical(word: str) -> str:
    word = word.rstrip('.')
    if word.endswith('.js'):
        word = word[:-3] + 'js'
    for group in _SYNONYMS:
        if word in group:
            return sorted(group)[0]
    return word


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = {_canonical(w) for w in re.findall(r'[a-z0-9][a-z0-9+#./]*', lowered)}
    for group in _SYNONYMS:  # multi-word spellings ("machine learning")
        if any(' ' in name and name in lowered for name in group):
            tokens.add(sorted(group)[0])
    return tokens


def _mentioned(skill: str, job_text: str) -> bool:
    """True when the skill (or a common spelling of it) appears in the job text."""
    job_tokens = _tokens(job_text)
    words = [w for w in _tokens(skill) if w not in _STOPWORDS]
    return any(w in job_tokens for w in words)


def score_match(profile: ResumeProfile, job: JobExtraction) -> MatchScore:
    user_content = (
        f"RESUME PROFILE:\n{profile.model_dump_json(indent=2)}\n\n"
        f"JOB:\n{job.model_dump_json(indent=2)}"
    )
    result = parse_structured(
        model=settings.match_scoring_model,
        system=MATCH_SCORING_SYSTEM_PROMPT,
        user_content=user_content,
        output_model=MatchScore,
        # Feeding the full job posting (not just a short summary) gives the model more to
        # reason about, so it tends to produce longer matched/missing skill lists and
        # rationale - 1024 was tight enough to occasionally truncate mid-JSON and fail
        # schema validation.
        max_tokens=2048,
    )
    # Enforce missing-evidence handling even when the model omits structured concerns.
    from types import SimpleNamespace
    from app.services.recommendation_policy import known_mismatches, mandatory_evidence
    job_evidence = SimpleNamespace(requirements=job.requirements, raw_input_text=job.description_summary)
    _, concerns = mandatory_evidence(job_evidence, profile.model_dump())
    mismatches = known_mismatches(job_evidence, profile.model_dump())
    result.eligibility_concerns = list(dict.fromkeys(result.eligibility_concerns + mismatches + concerns))
    if mismatches and result.score > 40:
        result.score = 40
        result.rationale += ' Score capped because a mandatory requirement is not met.'
    elif result.eligibility_concerns and result.score > 69:
        result.score = 69
        result.rationale += ' Score capped because mandatory eligibility is unresolved.'
    # A "matched" skill must be something the job actually asks for, not just a CV skill.
    job_text = ' '.join([*(job.requirements or []), job.description_summary or '', job.title or '']).lower()
    result.matched_skills = [skill for skill in result.matched_skills if _mentioned(skill, job_text)]
    names = [project.name for project in profile.projects if project.name]
    result.relevant_projects = [name for name in names if name in result.relevant_projects or name.lower() in result.rationale.lower()]
    if any('enrollment' in reason.lower() for reason in concerns):
        result.matched_skills = [skill for skill in result.matched_skills if not any(word in skill.lower() for word in ('enroll', 'student', 'studying'))]
    return result
