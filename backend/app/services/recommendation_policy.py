"""One evidence gate for the dashboard and opportunity delivery; no model-only approval."""
import re
from datetime import datetime, timezone, timedelta

# Bump to force every stored posting through enrichment and rescoring again.
POLICY_VERSION = 3
COUNTRIES = {
    'pakistan': ('pakistan', 'pk'), 'united states': ('united states', 'usa', 'us', 'u.s.', 'united states of america'),
    'united kingdom': ('united kingdom', 'uk', 'u.k.', 'great britain'),
    # Bare 'CA' is deliberately not treated as a Canada alias - in job postings it is far
    # more often the US state California (e.g. "CA residents only"); 'canada' spelled out
    # or 'CAN' is unambiguous and still matches.
    'canada': ('canada', 'can'), 'india': ('india', 'in'), 'germany': ('germany', 'de'),
    'australia': ('australia', 'au'), 'united arab emirates': ('united arab emirates', 'uae'),
}


def country_names(value):
    text = str(value or '').lower()
    # Bare short codes are accepted; in prose, require uppercase to avoid "in"/"us" pronouns.
    found = set()
    for country, aliases in COUNTRIES.items():
        for alias in aliases:
            if len(alias) <= 3 and alias.isalpha():
                hit = text.strip(' \"[]{}') == alias or re.search(r'(?<!\w)' + re.escape(alias.upper()) + r'(?!\w)', str(value))
            else:
                hit = re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text)
            if hit:
                found.add(country)
    return found


def remote_restriction(restriction, country):
    if not country:
        return None, 'Candidate remote eligibility country is not set'
    if not restriction:
        return None, 'Remote applicant country eligibility unknown'
    wanted, allowed = country_names(country), country_names(restriction)
    lower = str(restriction).lower()
    for name in wanted:
        if re.search(r'\b(?:except|excluding|not (?:in|from)|not eligible in)\s+' + re.escape(name), lower):
            return 'Candidate country is explicitly excluded', None
    if any(w in lower for w in ('worldwide', 'anywhere', 'global')) and not re.search(r'\b(except|excluding|not eligible)\b', lower):
        return None, None
    if re.search(r'\b(except|excluding|not eligible)\b', lower):
        return None, f'Confirm regional exceptions for {country}: {restriction}'
    if wanted and allowed and wanted.isdisjoint(allowed):
        return f'Remote country restriction: {restriction}', None
    if wanted and allowed == wanted and not re.search(r'\b(except|excluding|not eligible)\b', lower):
        return None, None
    if wanted and wanted.intersection(allowed) and not re.search(r'\b(except|excluding|not eligible)\b', lower):
        return None, None
    return None, f'Confirm eligibility for {country}: {restriction}'


_NUMBER_WORDS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
    'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'twenty': 20,
}
_NUMBER = r'(?:\d+|' + '|'.join(_NUMBER_WORDS) + r')'
# "5 years of experience", "5+ yrs experience in", "three (3) years' professional software
# experience", "minimum 2-4 years relevant experience". Group 1 is the minimum.
_YEARS_PATTERN = re.compile(
    r'(?i)\b(' + _NUMBER + r')(?:\s*\(\d+\))?\s*(?:\+|plus)?\s*(?:(?:[-–]|to)\s*' + _NUMBER + r'\s*)?'
    r'\s*(?:years?|yrs?)\.?[\'’]?\s+(?:of\s+)?(?:[\w/-]+\s+){0,3}?experience'
)
_AUTHORIZATION = re.compile(
    r'(?i)(work authori[sz]ation|right to work|citizenship|security clearance|must be (?:a )?citizen'
    r'|eligible to work|authori[sz]ed to work|legally (?:able|entitled|permitted) to work|work permit'
    r'|green card|visa sponsorship (?:is )?(?:not|un)available|(?:no|not able to|cannot|unable to) (?:provide |offer )?(?:visa )?sponsor)'
)
_DEGREE_LEVELS = (('doctorate', r'ph\.?\s?d|doctorate|doctoral'), ('master', r"master'?s?|\bm\.?s\.?c?\b|\bmba\b"),
                  ('bachelor', r"bachelor'?s?|\bb\.?s\.?c?\b|\bb\.?e\b|\bb\.?tech\b|undergraduate degree"))
_DEGREE_RANK = {'bachelor': 1, 'master': 2, 'doctorate': 3}
_MONTHS = {m: i + 1 for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'))}


def _years_value(token):
    token = token.lower()
    return _NUMBER_WORDS.get(token, None) if not token.isdigit() else int(token)


def _month_index(value, *, end=False):
    """'2024-03', 'Mar 2024', '03/2024' or '2024' -> months since year 0; None if unparseable.
    A bare year counts from January for a start and through December for an end."""
    text = str(value or '').lower()
    year = re.search(r'(19|20)\d{2}', text)
    if not year:
        return None
    month = None
    numeric = re.search(r'(?:(19|20)\d{2}[-/.](\d{1,2})\b|\b(\d{1,2})[-/.](19|20)\d{2})', text)
    if numeric:
        month = int(numeric.group(2) or numeric.group(3))
    else:
        named = re.search(r'\b(' + '|'.join(_MONTHS) + r')[a-z]*\b', text)
        if named:
            month = _MONTHS[named.group(1)]
    if month is None or not 1 <= month <= 12:
        month = 12 if end else 1
    return int(year.group(0)) * 12 + month - 1


def candidate_experience_years(profile):
    """Total experience in whole years from the CV's dated roles, with overlapping roles
    merged and gaps excluded (an old internship does not stretch the total to today).
    Returns None when nothing parseable is present - callers treat that as unknown."""
    entries = (profile or {}).get('experience') or []
    now = datetime.now(timezone.utc)
    now_index = now.year * 12 + now.month - 1
    spans = []
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        start = _month_index(entry.get('start_date'))
        if start is None:
            continue
        end_raw = str(entry.get('end_date') or '')
        if not entry.get('end_date') or re.search(r'(?i)present|current|ongoing|now', end_raw):
            end = now_index
        else:
            end = _month_index(end_raw, end=True)
            if end is None:
                continue
        if end >= start:
            spans.append((start, min(end, now_index) + 1))
    if not spans:
        return None
    total, current_start, current_end = 0, None, None
    for start, end in sorted(spans):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    total += current_end - current_start
    return total // 12


def _degree_level(text, lowest=False):
    """Highest degree level named in text ('BS/MS required' asks for the lowest instead)."""
    found = [level for level, pattern in _DEGREE_LEVELS if re.search(r'(?i)' + pattern, text)]
    if not found:
        return None
    return (min if lowest else max)(found, key=_DEGREE_RANK.get)


def known_mismatches(job, profile):
    """Mandatory requirements the CV clearly does not meet (as opposed to unknowns)."""
    mismatches = []
    required_years, degree, degree_flexible = _requirement_facts(job)
    actual = candidate_experience_years(profile)
    if required_years and actual is not None and actual < required_years:
        mismatches.append(f'Requires {required_years}+ years of experience; CV shows about {actual}')
    education = (profile or {}).get('education') or []
    # "Master's degree or equivalent experience" can be met without the degree: a concern, not a mismatch.
    if degree and education and not degree_flexible:
        held = [_degree_level(' '.join(str(v) for v in (e.values() if isinstance(e, dict) else [e]))) for e in education]
        best = max((_DEGREE_RANK[h] for h in held if h), default=0)
        if best and best < _DEGREE_RANK[degree]:
            mismatches.append(f'Requires a {degree} degree; CV lists a lower degree')
    return mismatches


_OPTIONAL = re.compile(r'(?i)preferred|desirable|nice.to.have|not required|no .* required'
                       r'|\bis an? (?:plus|bonus|advantage)\b|\badvantageous\b|\bideal(?:ly)?\b|\bnice if\b|\bbenefit\b')
# Sentences about the employer ("Acme has over 20 years of experience in fintech").
_ABOUT_EMPLOYER = re.compile(r'(?i)^\s*(?:we|our|the company)\b|\b(?:we have|we\'ve|our (?:team|company|firm)|'
                             r'company (?:has|with)|founded|since \d{4}|in business|track record|industry leader|'
                             r'(?:company|firm|house|agency|organi[sz]ation|business|we|it) (?:has|with|brings) '
                             r'(?:over|more than|nearly|almost)\s+\w+\s+years)\b')
# Prose sentences only count as requirements with an explicit cue aimed at the applicant.
_APPLICANT_CUE = re.compile(r'(?i)\b(?:you|your|candidate|applicant|required|requires|requirement|must|minimum|'
                            r'at least|looking for|seeking|should have|need|qualifications?)\b')


def _mandatory_clauses(job, *, with_source=False):
    """Mandatory-looking clauses: extracted requirements, plus prose sentences as a fallback."""
    requirements = getattr(job, 'requirements', None) or []
    prose = re.split(r'[\n.;]', getattr(job, 'raw_input_text', '') or '')
    for clause, listed in [(c, True) for c in requirements] + [(c, False) for c in prose]:
        if not clause or _OPTIONAL.search(clause):
            continue
        yield (clause, listed) if with_source else clause


def _requirement_facts(job):
    """(minimum years, required degree level, whether the degree accepts equivalent experience)."""
    minima, degree, flexible = [], None, False
    for clause, listed in _mandatory_clauses(job, with_source=True):
        about_employer = bool(_ABOUT_EMPLOYER.search(clause))
        years = _YEARS_PATTERN.search(clause)
        if years and not about_employer and (listed or _APPLICANT_CUE.search(clause)):
            value = _years_value(years.group(1))
            if value is not None:
                minima.append(value)
        if not about_employer and re.search(r'(?i)\b(required|requires|must|minimum|at least)\b', clause):
            level = _degree_level(clause, lowest=True) if re.search(r'(?i)degree|bachelor|master|ph\.?\s?d|doctorate', clause) else None
            if level and (degree is None or _DEGREE_RANK[level] > _DEGREE_RANK[degree]):
                degree = level
                flexible = bool(re.search(r'(?i)\bor (?:an? )?(?:equivalent|related|comparable|relevant)\b|\bequivalent (?:practical |work )?experience\b', clause))
    return (max(minima) if minima else 0), degree, flexible


def mandatory_evidence(job, profile=None):
    """Fail uncertain mandatory conditions closed. Never infer dates, enrollment or visas."""
    rejected, concerns = [], []
    enrollment = authorization = False
    for clause in _mandatory_clauses(job):
        enrollment |= bool(re.search(r'(?i)(currently (?:enrolled|studying)|must be (?:a )?student|enrollment required)', clause))
        authorization |= bool(_AUTHORIZATION.search(clause))
    required_years, degree, _ = _requirement_facts(job)
    if degree:
        held = [_degree_level(' '.join(str(v) for v in (e.values() if isinstance(e, dict) else [e])))
                for e in (profile or {}).get('education', [])]
        if max((_DEGREE_RANK[h] for h in held if h), default=0) < _DEGREE_RANK[degree]:
            concerns.append(f'Confirm the required {degree} degree from CV evidence')
    if required_years > 0:
        # A posting that only ever mentions "0" or "0-N years" (e.g. "0-2 years, fresh
        # graduates welcome") isn't a minimum anyone could fail to meet.
        actual_years = candidate_experience_years(profile)
        if actual_years is None or actual_years < required_years:
            concerns.append(f'Confirm at least {required_years} years of relevant experience from CV evidence')
    if enrollment:
        evidence = ' '.join(str(e) for e in (profile or {}).get('education', []))
        if not re.search(r'(?i)currently enrolled|currently studying', evidence):
            concerns.append('Current student enrollment requires explicit confirmation')
    if authorization:
        concerns.append('Work authorization or citizenship requirement needs explicit confirmation')
    return rejected, concerns


def recommendation(job, user, resume, match, *, use_plan=True):
    from app.services.job_quality import eligibility, parse_date, current_plan
    from app.services.portfolio_service import candidate_profile
    from app.services.discovery_backlog import match_context
    prefs = {**(user.preferences or {})}
    prefs['max_age_days'] = prefs.get('max_age_days') or 30
    research = job.research or {}
    profile = candidate_profile(user, resume) if resume else {}
    rejected, concerns = eligibility(job, prefs, current_plan(job, user) if use_plan else None, profile)
    _, mandatory = mandatory_evidence(job, profile)
    concerns += mandatory
    now = datetime.now(timezone.utc)
    checked = parse_date(research.get('last_verified_at'))
    if research.get('state') != 'active':
        concerns.append('Opening is not confirmed active')
    if research.get('is_job_posting') is not True:
        concerns.append('Individual vacancy is not confirmed')
    if not job.company:
        concerns.append('Hiring company is unknown')
    if not checked or checked < now - timedelta(days=1) or checked > now + timedelta(minutes=5):
        concerns.append('Vacancy needs a current page check')
    if research.get('application_link_status') != 'reachable':
        concerns.append('Application destination has not been checked')
    if research.get('evidence_version') != POLICY_VERSION:
        concerns.append('Vacancy needs updated evidence checks')
    if not resume or resume.parse_status != 'parsed':
        concerns.append('A parsed primary CV is required')
    if not match or not resume or match.context_hash != match_context(user, resume, job):
        concerns.append('A current evidence-based match is required')
    else:
        concerns += (match.details or {}).get('eligibility_concerns', [])
        if match.match_score < 75:
            concerns.append('Estimated fit is below the recommendation threshold')
    rejected, concerns = list(dict.fromkeys(rejected)), list(dict.fromkeys(concerns))
    status = 'excluded' if rejected else 'needs_review' if concerns else 'recommended'
    return {'recommendation_status': status, 'recommendation_reasons': rejected + concerns,
            'exclusion_reasons': rejected, 'eligibility_concerns': concerns}
