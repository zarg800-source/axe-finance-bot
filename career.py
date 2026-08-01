"""
career.py — Axe Career: Opportunity Radar (Phase 1)
=====================================================
Searches the web (via Tavily) for curatorial opportunities — open calls,
museum/gallery jobs, and curatorial grants & fellowships — scores them
against a minimal profile, and stores them for the Axe Career dashboard.

No Flask here, same pattern as core.py / receipt_parser.py: pure functions
+ direct SQLite access, imported by render_main.py.

Requires two env vars on Render:
  TAVILY_API_KEY  — from app.tavily.com (free tier: 1,000 searches/month)
  GEMINI_API_KEY  — same one Axe Finance's CFO chat already uses

Scoring is a transparent v1 heuristic, not gospel — three components:
  40% keyword overlap between your profile and the result (deterministic)
  20% deadline feasibility (can you realistically finish in time?)
  40% Gemini's relevance judgment (reads the actual snippet)
"""

import os
import re
import json
import logging
import sqlite3
import requests
from datetime import datetime, date

logger = logging.getLogger(__name__)

DATABASE = '/data/finance.db'  # same DB file as Finance — new tables only

TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY', '').strip()
TAVILY_URL = 'https://api.tavily.com/search'

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = 'gemini-2.5-flash'
GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}'

QUERY_TEMPLATES = {
    'open_call': 'curatorial open call {specialty} {year} exhibition submissions',
    'job':       'curator job {specialty} museum gallery hiring {location_clause}',
    'grant':     'curatorial grant fellowship {specialty} {year} funding',
}

MIN_SECONDS_BETWEEN_MANUAL_RUNS = 15 * 60  # throttle the "Refresh now" button


# ─── DB ───────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_career_db():
    conn = get_db(); c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS career_profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        specialty TEXT NOT NULL DEFAULT '',
        experience_level TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        remote_pref TEXT NOT NULL DEFAULT 'local_only',
        last_search_at DATETIME,
        updated_at DATETIME
    );
    CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        org TEXT DEFAULT '',
        url TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        deadline DATE,
        match_score REAL DEFAULT 0,
        prep_hours_est REAL,
        status TEXT NOT NULL DEFAULT 'new',
        found_at DATETIME,
        source_query TEXT
    );
    """)
    conn.commit(); conn.close()


def get_profile():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM career_profile WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def save_profile(specialty, experience_level, location, remote_pref):
    conn = get_db(); c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("""
        INSERT INTO career_profile (id, specialty, experience_level, location, remote_pref, updated_at)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            specialty=excluded.specialty,
            experience_level=excluded.experience_level,
            location=excluded.location,
            remote_pref=excluded.remote_pref,
            updated_at=excluded.updated_at
    """, (specialty.strip(), experience_level.strip(), location.strip(), remote_pref, now))
    conn.commit(); conn.close()


# ─── Tavily search ────────────────────────────────────────────────────────────
def _tavily_search(query, max_results=6):
    if not TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not set — Axe Career search skipped.")
        return []
    try:
        resp = requests.post(
            TAVILY_URL,
            headers={'Authorization': f'Bearer {TAVILY_API_KEY}', 'Content-Type': 'application/json'},
            json={
                'query': query,
                'search_depth': 'basic',
                'max_results': max_results,
                'topic': 'general',
                'include_answer': False,
                'include_raw_content': False,
            },
            timeout=20,
        )
        if resp.status_code != 200:
            logger.error(f"Tavily error {resp.status_code}: {resp.text[:300]}")
            return []
        return resp.json().get('results', [])
    except Exception as e:
        logger.error(f"Tavily request failed: {e}")
        return []


# ─── Scoring ──────────────────────────────────────────────────────────────────
def _keyword_overlap_score(profile, title, content):
    """Deterministic 0-1: how many of your own profile words show up in the
    result. Cheap and explainable, but it's a floor, not a ceiling — that's
    what the Gemini relevance pass is for."""
    keywords = set(re.findall(r'[a-z]{3,}', (profile['specialty'] + ' ' + profile['experience_level']).lower()))
    if not keywords:
        return 0.5
    text = (title + ' ' + content).lower()
    hits = sum(1 for k in keywords if k in text)
    return min(1.0, hits / len(keywords))


def _gemini_extract(profile, title, content, opp_type):
    """One Gemini call per new result: relevance judgment + structured
    fields. Never fabricates a deadline — only fills it in if the snippet
    actually states one. Falls back to conservative neutral defaults if
    Gemini is unavailable or returns something unparseable."""
    defaults = {'relevant': True, 'relevance_score': 50, 'deadline': None,
                'org': '', 'prep_hours_est': 4.0}
    if not GEMINI_API_KEY:
        return defaults

    prompt = f"""You are screening one web search result for a curator's opportunity radar.

CURATOR PROFILE:
- Specialty: {profile['specialty']}
- Experience level: {profile['experience_level']}
- Location / preference: {profile['location']} ({profile['remote_pref']})

RESULT (type guess: {opp_type}):
Title: {title}
Snippet: {content[:800]}

Return ONLY strict JSON, no markdown fences, matching exactly this shape:
{{"relevant": true or false, "relevance_score": 0-100 integer, "deadline": "YYYY-MM-DD" or null (only if a real date is stated in the snippet — never guess), "org": "organization name or empty string", "prep_hours_est": integer hours a strong application would realistically take}}"""

    try:
        resp = requests.post(
            GEMINI_URL,
            json={'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                  'generationConfig': {'maxOutputTokens': 300, 'temperature': 0.1}},
            headers={'Content-Type': 'application/json'},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning(f"Gemini extract failed {resp.status_code}: {resp.text[:200]}")
            return defaults
        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        text = re.sub(r'^```json|```$', '', text.strip(), flags=re.MULTILINE).strip()
        data = json.loads(text)
        return {
            'relevant': bool(data.get('relevant', True)),
            'relevance_score': max(0, min(100, int(data.get('relevance_score', 50)))),
            'deadline': data.get('deadline') or None,
            'org': (data.get('org') or '')[:120],
            'prep_hours_est': float(data.get('prep_hours_est') or 4),
        }
    except Exception as e:
        logger.warning(f"Gemini extract parse failed: {e}")
        return defaults


def _deadline_feasibility(deadline_str, prep_hours_est):
    """0-100. No deadline found -> neutral 60 (don't penalize what we
    couldn't read). Assumes ~2 focused hours/day available for applications
    — adjust here if that's unrealistic for you."""
    if not deadline_str:
        return 60
    try:
        deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
    except ValueError:
        return 60
    days_left = (deadline - date.today()).days
    if days_left < 0:
        return 0
    hours_available = days_left * 2
    if hours_available >= prep_hours_est:
        return 100
    return max(0, round(100 * hours_available / max(prep_hours_est, 1)))


# ─── Search + score + dedup ───────────────────────────────────────────────────
def run_search(max_per_type=6):
    """Runs all 3 query templates, scores + upserts genuinely new
    opportunities (deduped by URL). Returns (num_found, num_new)."""
    profile = get_profile()
    if not profile or not profile['specialty']:
        return 0, 0

    year = str(date.today().year)
    location_clause = 'remote' if profile['remote_pref'] == 'remote' else (profile['location'] or 'international')

    conn = get_db(); c = conn.cursor()
    num_found = 0
    num_new = 0

    for opp_type, template in QUERY_TEMPLATES.items():
        query = template.format(specialty=profile['specialty'], year=year, location_clause=location_clause)
        results = _tavily_search(query, max_results=max_per_type)
        for r in results:
            num_found += 1
            url = r.get('url', '')
            title = r.get('title', '') or 'Untitled'
            content = r.get('content', '') or ''
            if not url:
                continue

            c.execute("SELECT id FROM opportunities WHERE url = ?", (url,))
            if c.fetchone():
                continue  # already have this one

            kw_score = _keyword_overlap_score(profile, title, content)
            extracted = _gemini_extract(profile, title, content, opp_type)
            if not extracted['relevant']:
                continue

            deadline_score = _deadline_feasibility(extracted['deadline'], extracted['prep_hours_est'])
            match_score = round(
                0.4 * kw_score * 100 +
                0.2 * deadline_score +
                0.4 * extracted['relevance_score'],
                1
            )

            c.execute("""
                INSERT OR IGNORE INTO opportunities
                    (type, title, org, url, description, deadline, match_score,
                     prep_hours_est, status, found_at, source_query)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """, (opp_type, title, extracted['org'], url, content[:500],
                  extracted['deadline'], match_score, extracted['prep_hours_est'],
                  datetime.utcnow().isoformat(), query))
            if c.rowcount:
                num_new += 1

    c.execute("UPDATE career_profile SET last_search_at = ? WHERE id = 1", (datetime.utcnow().isoformat(),))
    conn.commit(); conn.close()
    return num_found, num_new


def can_run_manual_search():
    """Throttles the 'Refresh now' button so a few taps can't burn through
    the Tavily monthly quota. Returns (allowed: bool, seconds_remaining)."""
    profile = get_profile()
    if not profile or not profile.get('last_search_at'):
        return True, 0
    last = datetime.fromisoformat(profile['last_search_at'])
    elapsed = (datetime.utcnow() - last).total_seconds()
    remaining = MIN_SECONDS_BETWEEN_MANUAL_RUNS - elapsed
    return remaining <= 0, max(0, round(remaining))


# ─── Reading / updating results ───────────────────────────────────────────────
def list_opportunities(status=None, opp_type=None):
    conn = get_db(); c = conn.cursor()
    q = "SELECT * FROM opportunities WHERE 1=1"
    params = []
    if status:
        q += " AND status = ?"; params.append(status)
    if opp_type:
        q += " AND type = ?"; params.append(opp_type)
    q += " ORDER BY match_score DESC"
    c.execute(q, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def set_opportunity_status(opp_id, status):
    if status not in ('new', 'saved', 'dismissed'):
        return False
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE opportunities SET status = ? WHERE id = ?", (status, opp_id))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok
