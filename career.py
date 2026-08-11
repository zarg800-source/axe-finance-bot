"""
career.py — Axe Career: Opportunity Radar (Phase 1) + Applications workflow
=============================================================================
Searches the web (via Tavily) for curatorial opportunities — open calls,
museum/gallery jobs, and curatorial grants & fellowships — scores them
against a minimal profile, and stores them for the Axe Career dashboard.

Also holds the Applications tracking workflow: once Mike marks an
opportunity as "Applied", a deeper application record is created here,
with its own 8-stage pipeline, a checklist, drafted content fields, and an
auto-generated status-change history (used as the application's timeline).

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

# ─── Applications workflow ──────────────────────────────────────────────────
# 8-stage pipeline. Order matters — used for simple "is this further along"
# comparisons in the UI (e.g. sort order), though the DB itself doesn't
# enforce sequential transitions; Mike can jump stages freely (e.g. straight
# to 'rejected' if a call closes early).
APPLICATION_STATUSES = [
    'draft', 'preparing', 'ready', 'submitted',
    'interview', 'accepted', 'rejected', 'archived',
]


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
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        opportunity_id INTEGER NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'draft',
        cover_letter TEXT DEFAULT '',
        proposal TEXT DEFAULT '',
        email_draft TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at DATETIME,
        updated_at DATETIME,
        FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
    );
    CREATE TABLE IF NOT EXISTS application_checklist_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME,
        FOREIGN KEY (application_id) REFERENCES applications(id)
    );
    CREATE TABLE IF NOT EXISTS application_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        changed_at DATETIME,
        FOREIGN KEY (application_id) REFERENCES applications(id)
    );
    """)
    conn.commit()

    # ── Idempotent backfill ──────────────────────────────────────────────
    # An earlier session already added 'applied' as an opportunity status
    # before the applications table existed. Any opportunity sitting at
    # status='applied' with no matching application row gets one created
    # now, seeded at the 'submitted' stage (the closest honest mapping —
    # "applied" meant "I sent it in").
    c.execute("""
        SELECT o.id FROM opportunities o
        LEFT JOIN applications a ON a.opportunity_id = o.id
        WHERE o.status = 'applied' AND a.id IS NULL
    """)
    orphaned = [r['id'] for r in c.fetchall()]
    now = datetime.utcnow().isoformat()
    for opp_id in orphaned:
        c.execute("""
            INSERT INTO applications (opportunity_id, status, created_at, updated_at)
            VALUES (?, 'submitted', ?, ?)
        """, (opp_id, now, now))
        new_app_id = c.lastrowid
        c.execute("""
            INSERT INTO application_status_history (application_id, status, changed_at)
            VALUES (?, 'submitted', ?)
        """, (new_app_id, now))
    if orphaned:
        logger.info(f"Backfilled {len(orphaned)} application record(s) from legacy 'applied' opportunities.")

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


# This is a single-user app for Mike specifically — no point making him fill
# out a form to tell the app what it already knows about him. These are my
# best-guess defaults based on what he's told me directly; they're editable
# any time via the same save_profile() call, just never forced upfront.
# NOT invented with false confidence — specialty and remote_pref are
# reasonable guesses, not verified facts, and worth him double-checking once.
DEFAULT_PROFILE = {
    'specialty': 'contemporary Southeast Asian art curating',
    'experience_level': 'mid-career',
    'location': 'Bangkok, Thailand',
    'remote_pref': 'relocate',
}


def ensure_profile_seeded():
    """Called once at startup. If no profile exists yet, seeds the
    best-guess defaults above so Axe Career works immediately with zero
    manual setup. Never overwrites a profile that already exists (e.g. one
    Mike has since edited)."""
    if get_profile() is not None:
        return False
    save_profile(**DEFAULT_PROFILE)
    return True



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
    if status not in ('new', 'saved', 'dismissed', 'applied'):
        return False
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE opportunities SET status = ? WHERE id = ?", (status, opp_id))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok


def add_manual_opportunity(title, opp_type, org='', url='', description='', deadline=None):
    """For opportunities Mike hears about outside the automatic search (a
    tip from a friend, an email, etc.) — not scored by Gemini since he's
    already vetted it himself; shown in the UI as 'Added manually' rather
    than given a fake match score."""
    conn = get_db(); c = conn.cursor()
    if not url:
        url = f"manual://{datetime.utcnow().isoformat()}"
    c.execute("""
        INSERT INTO opportunities
            (type, title, org, url, description, deadline, match_score,
             prep_hours_est, status, found_at, source_query)
        VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 'new', ?, 'manual')
    """, (opp_type, title.strip(), org.strip(), url, description.strip(),
          deadline or None, datetime.utcnow().isoformat()))
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    return new_id


def dashboard_summary():
    """Deterministic, honest content for Career's Dashboard tab — no extra
    Gemini call needed, everything here is computed straight from the DB.
    'AI-ranked' suggestions are real: match_score was already set by Gemini
    during the search itself, this just re-surfaces the top ones."""
    active = [o for o in list_opportunities() if o['status'] in ('new', 'saved')]
    with_deadline = sorted(
        [o for o in active if o['deadline']],
        key=lambda o: o['deadline']
    )
    top_matches = sorted(active, key=lambda o: o['match_score'] or 0, reverse=True)[:3]

    profile = get_profile()
    last_search = profile.get('last_search_at') if profile else None

    return {
        'total_active': len(active),
        'upcoming_deadlines': with_deadline[:5],
        'top_matches': top_matches,
        'last_search_at': last_search,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ── Applications workflow ────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def _row_to_dict(row):
    return dict(row) if row else None


def create_application(opportunity_id):
    """Creates an application record for an opportunity, idempotently — if
    one already exists for this opportunity, returns the existing one
    instead of erroring or duplicating. Also flips the parent opportunity's
    coarse status to 'applied' so Opportunities/Applications tabs agree.
    Returns the full application dict, or None if the opportunity_id is
    invalid."""
    conn = get_db(); c = conn.cursor()

    c.execute("SELECT id FROM opportunities WHERE id = ?", (opportunity_id,))
    if not c.fetchone():
        conn.close()
        return None

    c.execute("SELECT * FROM applications WHERE opportunity_id = ?", (opportunity_id,))
    existing = c.fetchone()
    if existing:
        conn.close()
        return _row_to_dict(existing)

    now = datetime.utcnow().isoformat()
    c.execute("""
        INSERT INTO applications (opportunity_id, status, created_at, updated_at)
        VALUES (?, 'draft', ?, ?)
    """, (opportunity_id, now, now))
    new_id = c.lastrowid
    c.execute("""
        INSERT INTO application_status_history (application_id, status, changed_at)
        VALUES (?, 'draft', ?)
    """, (new_id, now))
    c.execute("UPDATE opportunities SET status = 'applied' WHERE id = ?", (opportunity_id,))
    conn.commit()

    c.execute("SELECT * FROM applications WHERE id = ?", (new_id,))
    result = _row_to_dict(c.fetchone())
    conn.close()
    return result


def list_applications(status=None):
    """Returns applications joined with their parent opportunity's display
    fields (title/org/url/deadline/type), sorted newest-updated first."""
    conn = get_db(); c = conn.cursor()
    q = """
        SELECT a.*, o.title AS opp_title, o.org AS opp_org, o.url AS opp_url,
               o.deadline AS opp_deadline, o.type AS opp_type
        FROM applications a
        JOIN opportunities o ON o.id = a.opportunity_id
        WHERE 1=1
    """
    params = []
    if status:
        q += " AND a.status = ?"; params.append(status)
    q += " ORDER BY a.updated_at DESC"
    c.execute(q, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_application(app_id):
    """Full detail for one application: parent opportunity fields,
    checklist items, and status history — everything the detail modal
    needs in one call."""
    conn = get_db(); c = conn.cursor()
    c.execute("""
        SELECT a.*, o.title AS opp_title, o.org AS opp_org, o.url AS opp_url,
               o.deadline AS opp_deadline, o.type AS opp_type, o.description AS opp_description
        FROM applications a
        JOIN opportunities o ON o.id = a.opportunity_id
        WHERE a.id = ?
    """, (app_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    result = dict(row)

    c.execute("SELECT * FROM application_checklist_items WHERE application_id = ? ORDER BY id", (app_id,))
    result['checklist'] = [dict(r) for r in c.fetchall()]

    c.execute("SELECT status, changed_at FROM application_status_history WHERE application_id = ? ORDER BY changed_at", (app_id,))
    result['history'] = [dict(r) for r in c.fetchall()]

    conn.close()
    return result


def update_application_status(app_id, status):
    if status not in APPLICATION_STATUSES:
        return False
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM applications WHERE id = ?", (app_id,))
    if not c.fetchone():
        conn.close()
        return False
    now = datetime.utcnow().isoformat()
    c.execute("UPDATE applications SET status = ?, updated_at = ? WHERE id = ?", (status, now, app_id))
    c.execute("""
        INSERT INTO application_status_history (application_id, status, changed_at)
        VALUES (?, ?, ?)
    """, (app_id, status, now))
    conn.commit()
    conn.close()
    return True


def update_application_fields(app_id, cover_letter=None, proposal=None, email_draft=None, notes=None):
    """Partial update — only touches fields that were actually passed
    (None means 'leave unchanged', not 'clear it'). Used by the detail
    modal's autosave-on-blur for each textarea."""
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM applications WHERE id = ?", (app_id,))
    if not c.fetchone():
        conn.close()
        return False

    fields = []
    params = []
    if cover_letter is not None:
        fields.append("cover_letter = ?"); params.append(cover_letter)
    if proposal is not None:
        fields.append("proposal = ?"); params.append(proposal)
    if email_draft is not None:
        fields.append("email_draft = ?"); params.append(email_draft)
    if notes is not None:
        fields.append("notes = ?"); params.append(notes)

    if not fields:
        conn.close()
        return True  # nothing to do, not an error

    fields.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(app_id)

    c.execute(f"UPDATE applications SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True


def add_checklist_item(app_id, label):
    label = (label or '').strip()
    if not label:
        return None
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id FROM applications WHERE id = ?", (app_id,))
    if not c.fetchone():
        conn.close()
        return None
    now = datetime.utcnow().isoformat()
    c.execute("""
        INSERT INTO application_checklist_items (application_id, label, done, created_at)
        VALUES (?, ?, 0, ?)
    """, (app_id, label, now))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def toggle_checklist_item(item_id, done=None):
    """Flips done/not-done, or sets it explicitly if `done` (bool) is
    given. Returns the new done value, or None if the item doesn't exist."""
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT done, application_id FROM application_checklist_items WHERE id = ?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    new_done = (1 if done else 0) if done is not None else (0 if row['done'] else 1)
    c.execute("UPDATE application_checklist_items SET done = ? WHERE id = ?", (new_done, item_id))
    c.execute("UPDATE applications SET updated_at = ? WHERE id = ?",
              (datetime.utcnow().isoformat(), row['application_id']))
    conn.commit()
    conn.close()
    return bool(new_done)


def delete_checklist_item(item_id):
    conn = get_db(); c = conn.cursor()
    c.execute("DELETE FROM application_checklist_items WHERE id = ?", (item_id,))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok


def delete_application(app_id):
    """Deletes the application + its checklist/history, and reverts the
    parent opportunity back to 'saved' (not 'new' — Mike already looked at
    it once, that shouldn't be forgotten) so it reappears in Opportunities
    rather than vanishing."""
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT opportunity_id FROM applications WHERE id = ?", (app_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False
    opp_id = row['opportunity_id']
    c.execute("DELETE FROM application_checklist_items WHERE application_id = ?", (app_id,))
    c.execute("DELETE FROM application_status_history WHERE application_id = ?", (app_id,))
    c.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    c.execute("UPDATE opportunities SET status = 'saved' WHERE id = ?", (opp_id,))
    conn.commit()
    conn.close()
    return True


def build_career_chat_system_prompt():
    """Builds Career chat's system prompt fresh each turn from live profile
    + opportunity + application data. Persona: calm, concise, warm — never
    flatters, challenges weak ideas respectfully, never invents facts."""
    profile = get_profile() or {}
    summary = dashboard_summary()
    apps = list_applications()
    active_apps = [a for a in apps if a['status'] not in ('accepted', 'rejected', 'archived')]

    deadlines_str = '\n'.join(
        f"- {o['title']} ({o.get('org') or 'org unknown'}) — due {o['deadline']}"
        for o in summary['upcoming_deadlines']
    ) or 'None on file.'

    matches_str = '\n'.join(
        f"- {o['title']} — match {round(o.get('match_score') or 0)}/100"
        for o in summary['top_matches']
    ) or 'None scored yet.'

    apps_str = '\n'.join(
        f"- {a['opp_title']} — stage: {a['status']}"
        for a in active_apps
    ) or 'No applications in progress.'

    return f"""You are Axe, Mike's career advisor for curatorial work, based in Bangkok, Thailand.

MIKE'S PROFILE:
- Specialty: {profile.get('specialty', 'not set')}
- Experience level: {profile.get('experience_level', 'not set')}
- Location / preference: {profile.get('location', 'not set')} ({profile.get('remote_pref', 'not set')})

YOUR PERSONALITY:
- Calm, concise, warm — never flatters
- Challenges weak ideas respectfully rather than agreeing by default
- Never invents facts; says "I don't know" when uncertain
- Presents trade-offs before recommending one option
- Max ~200 words unless a full strategy is requested

LIVE DATA:

ACTIVE OPPORTUNITIES: {summary['total_active']}

UPCOMING DEADLINES:
{deadlines_str}

TOP-SCORED MATCHES:
{matches_str}

APPLICATIONS IN PROGRESS:
{apps_str}
"""
