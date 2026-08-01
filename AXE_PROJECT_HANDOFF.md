# Axe — Project Handoff

This document exists so a fresh Claude session (or a human) can pick up exactly
where this conversation left off, with zero prior context. Read this fully
before touching any code. The accompanying zip contains every source file in
its current, unfinished-but-working state.

**Nothing described here has been deployed to Render yet.** All of this is
local build files, not yet pushed to production.

---

## 1. Who this is for

**Min Thu Kha Kyaw ("Mike")** — independent curator from Myanmar, based in
Bangkok. Came into curating through art dealing (family framing/exhibition
business), not an academic path. Building toward a career as a respected
Southeast Asian contemporary curator.

Mike explicitly wants an AI partner (not just a tool) that:
- Is calm, concise, warm — never flatters, challenges weak ideas respectfully
- Never invents facts, says "I don't know" when uncertain
- Presents trade-offs before recommending one option
- Knows nothing about coding personally — needs finished, ready-to-deploy
  files, not patches or instructions to apply manually

**Full persona spec** was uploaded as a "Mike OS" system profile document —
if you need the complete version (writing style, values, memory categories,
etc.), ask Mike to re-upload it. The short version above is what's already
baked into the Career chatbot's system prompt (see `career.py`).

---

## 2. What Axe is

Axe is a personal, single-user "OS" — one account, one password, no
multi-tenancy. It started as **Axe Finance** (an existing, already-deployed
Flask + SQLite personal finance tracker with a chatbot). Mike wants to expand
it into multiple **Agents** (Finance, Career, Research, Travel, Network,
Vault), all reachable from one home screen, all sharing one visual design
system, one backend, one database file.

**Brand naming**: everything is "Axe [X]" — Axe Finance, Axe Career, etc. An
earlier working name was "Atlas OS" — that name is retired, do not use it.
If you see "Atlas" anywhere, it's a bug, rename it.

**The 🪓 emoji is Axe's mark** — replaces every instance of a plain "A"
letter used as Axe's icon/avatar (home screen brand mark, chat header icons,
chat message avatars). Mike's own avatar stays "M" — never touch that.

---

## 3. Architecture (already decided, don't relitigate)

- **Hosting**: existing Render web service (already paid, has a persistent
  disk at `/data` for `finance.db`). Everything new is added to this *same*
  service — no new hosting cost. Do not suggest a new host.
- **Backend**: Flask (`render_main.py`), single SQLite file (`finance.db`)
  on the persistent volume. New features = new tables in the same DB file,
  new Python modules imported into `render_main.py` (pattern: `core.py`,
  `receipt_parser.py`, `career.py` are all plain modules with DB access
  functions, no Flask code inside them — routes live only in
  `render_main.py`).
- **AI**: Google Gemini (`gemini-2.5-flash`) via direct HTTPS calls — same
  pattern everywhere (`GEMINI_API_KEY` env var, a system-prompt-builder
  function that reads live DB state fresh each turn, one `requests.post`
  call). No LangChain, no agent framework — deliberately simple.
- **Web search**: Tavily API (`TAVILY_API_KEY` env var) — free tier is
  1,000 searches/month, plenty for a single user. Chosen over
  SerpApi/Google Custom Search after comparing current options.
- **Auth**: single dashboard password (`DASHBOARD_PASSWORD` env var),
  Flask session, `@require_auth` decorator on every route. This covers the
  whole app, not per-Agent.
- **No coding literacy on Mike's end** — always deliver complete,
  ready-to-deploy files (or a zip), never a "patch instructions" document
  he has to apply by hand. This was a hard-learned lesson mid-project —
  earlier turns gave patch docs, which confused him. Don't regress.

---

## 4. Design system (do not deviate)

Every page must reuse Axe Finance's **exact** existing CSS tokens — this is
a hard constraint Mike has repeated multiple times ("I don't want to change
the color and theme of application"):

- Glassmorphism cards: `--glass-grad`, `--glass-bg`, `--glass-border`,
  `--glass-shadow` / `--glass-shadow-hover` (see `:root` blocks in
  `dashboard.html` for exact values, light + dark theme)
- Accent: sapphire blue — `--gold: #3763a8` (light) / `#7fa8e8` (dark) —
  the variable is named `--gold` for historical reasons but the color is
  blue, not gold. Don't rename the variable, just know what it means.
- Fonts: `Anton` (display/headers), `DM Sans` (body) — both loaded from
  Google Fonts
- Radius: `--radius-card: 22px`, `--radius-pill: 999px`
- Dark/light theme toggle via `data-theme` attribute + `localStorage`,
  same inline `<script>` snippet at the top of every page's `<head>` to
  prevent flash-of-wrong-theme
- A separate "editorial" brand exists (Neue Haas Grotesk, cream/red,
  minimal) from Mike's personal "Mike OS" profile document — **that is
  Mike's personal/portfolio brand, completely separate from Axe's app
  UI**. Never apply it to the app. This was explicitly clarified and
  confirmed twice.

---

## 5. What's actually built so far

### Axe Finance (pre-existing, unchanged)
Already deployed and working before this project started. Balances /
Overview / Analytics / Monthly History tabs inside `dashboard.html`, a
receipt-scanning chatbot at `/cfo` (`cfo-finance-bot.html`), backed by
`core.py` (categories, accounts, DB schema) and `receipt_parser.py` (AI
vision + OCR receipt parsing). This is the reference implementation for
the tab-bar navigation pattern — see Section 7, it's the template every
other Agent should copy.

### Axe Career (Phase 1 — built this session)
- **`career.py`** — profile storage (`career_profile` table), Tavily
  search across 3 query templates (curatorial open calls / jobs /
  grants), dedup by URL (`opportunities` table), hybrid scoring:
  - 40% keyword overlap between profile and result (deterministic)
  - 20% deadline feasibility (~2 hrs/day assumed availability)
  - 40% Gemini relevance judgment (reads the actual snippet)
  - **Deadlines are never guessed** — only filled in if the Gemini
    extraction finds an actual stated date in the snippet. This
    honesty constraint matters to Mike, don't relax it.
  - Manual refresh throttled to once per 15 min; daily 7 AM Bangkok
    cron also runs it automatically (both inside Tavily's free quota)
  - `build_career_chat_system_prompt()` — builds the Career chatbot's
    system prompt fresh each turn from live profile + opportunity data,
    persona lifted from Mike's "Mike OS" profile (calm, concise,
    challenges weak ideas, never invents facts)
- **`axe_career_home.html`** — Career's own mini-Bento landing (6
  tiles: Opportunities/Applications/AI Research/Network/Career
  Vault/Timeline) — **this is now considered the WRONG pattern, see
  Section 7, it's mid-rebuild into a tab-bar shell**
- **`axe_career_opportunities.html`** — the actual opportunity results
  grid + profile setup form (this part's logic is correct and reusable,
  just needs to become a tab pane instead of a separate page)
- **`axe_career_chat.html`** — standalone chat page, same shell as
  `cfo-finance-bot.html`. **Also mid-rebuild** — see Section 7, this
  needs to become an embedded "AI" tab, not a separate page.

### Axe Home (Phase 0 — built, then revised)
- **`axe_home.html`** — Bento home screen, 6 cards (Finance, Career,
  Research, Travel, Network, Vault — **Ideas and Settings were
  deliberately dropped** per Mike's mockup). Finance + Career show real
  data (Career's tile fetches a live "N new opportunities" count via
  `/api/career/opportunities?status=new`). Research/Travel/Network/Vault
  are dimmed, honestly say "Not set up yet" — never fabricate numbers
  for agents with no backend.
- Backed by a `spaces` DB table (`SPACES_SEED` in `render_main.py`) —
  adding/flipping an Agent to "live" is a data change, not a redeploy.
- **The "Ask Axe" search bar currently sits ABOVE the 6 cards — Mike's
  latest spec wants it BELOW them.** Small fix, not yet done.

---

## 6. Decisions Mike has explicitly locked in (don't re-ask these)

1. Brand: "Axe" everywhere, not "Atlas." 🪓 is the mark.
2. No Finance "alerts" notification concept — Finance's home tile stays
   neutral/calm, no live count needed.
3. Vault is **one shared concept**, not duplicated per-Agent. Mike caught
   this himself when "Career Vault" and home-level "Vault Agent" both
   existed — the fix is Career's vault view should be a *filtered view*
   into the one real Vault, not a second vault. (This fix was proposed
   but not yet implemented in code — see Section 8.)
4. Home screen: exactly 6 Agent cards (Finance, Career, Research, Travel,
   Network, Vault). No Ideas, no Settings, for now.
5. FAB (the floating "+" quick-add button): **keep on Finance** (already
   does real quick-add-transaction work). **Add to Career** too, for
   manually logging an opportunity that didn't come through search.
   **No FAB yet on Research/Travel/Network/Vault** — nothing to add
   into until those have real data models.
6. Every Agent should open into the **same tab-bar shell pattern**
   Finance already uses internally (bottom pill nav, tab panes, no
   full-page navigation between sub-views). See Section 7 — this is the
   biggest unresolved rebuild.
7. AI is available at two levels: a **global Axe** on the home screen
   (routes across agents, e.g. "can I afford this trip?" spans Finance +
   Travel), and a **scoped AI tab inside each Agent** (only knows that
   agent's data). Global home-screen AI is NOT built yet (see Section 9)
   — currently just a visual stub with a "not live yet" message.
8. The AI tab should be **visually distinct** — bigger/raised, centered
   in the bottom nav, using the 🪓 mark — not just a same-sized 5th icon.
   (Confirmation of this exact detail was still pending when the
   conversation was exported — see Section 8, Q1.)

---

## 7. THE ACTIVE TASK — tab-bar shell rebuild (read this carefully)

This is what the conversation was in the middle of when exported. Mike
sent this exact navigation spec (verbatim, this is the source of truth):

```
🏠 Home
Just six cards.
💰 Finance Agent   💼 Career Agent
🔍 Research Agent  ✈️ Travel Agent
🤝 Network Agent   🔐 Vault Agent
Below the cards: 🤖 Ask Axe...

💰 Finance Agent — tabs: Dashboard, Accounts, Transactions, Analytics, AI

💼 Career Agent — tabs: Dashboard, Opportunities, Applications, AI
  Dashboard shows: Today's Brief, Deadlines, AI Suggestions

🔍 Research Agent — tabs: Dashboard, Research, Library, AI
  Dashboard shows: Recent research, Saved reports, Research history

✈️ Travel Agent — tabs: Dashboard, Trips, Documents, AI
  Dashboard shows: Upcoming trips, Visa status, Passport expiry, Travel budget

🤝 Network Agent — tabs: Dashboard, People, Organizations, AI
  Dashboard shows: Follow-ups, Recent contacts, Important relationships

🔐 Vault Agent — tabs: Dashboard, Documents, Collections, AI
  Dashboard shows: Recent documents, Expiring documents, Quick access

🤖 Axe (Global AI) — accessible from every screen, can jump between agents
  Examples: "Find fellowships in Japan." "Can I afford this trip?"
  "Draft my application." "Find my passport." "Who should I contact today?"

Navigation Philosophy:
Home = Choose an Agent.
Inside each Agent = 3–4 focused tabs.
AI is always available and can jump between agents automatically.
```

Mike also shared a **screenshot of the current live Axe Finance Balances
tab** as the visual reference for what every Agent's shell should look
and feel like (dark theme, glass cards, bottom floating pill nav, FAB in
bottom-right). Match that exactly.

**Concrete rebuild plan, agreed but not yet executed:**

1. **Rebuild Finance's shell first** (smaller lift — it already has the
   tab-bar pattern internally, just needs tab renames + a new AI tab):
   - Rename tabs: Balances → **Accounts**, Overview → **Dashboard**,
     Monthly History → **Transactions**, Analytics stays **Analytics**
   - Add a 5th tab: **AI** — move the `/cfo` chat UI's logic *into*
     `dashboard.html` as a tab pane (not a separate page/route anymore)
   - Rebuild bottom nav to 5 items with AI raised/centered (pending
     final confirmation of the exact visual treatment, see Section 8 Q1)
   - Everything else (charts, account cards, Quick Actions, receipt
     scanning) stays exactly as-is — this is a navigation/shell change
     only, not a data or backend change
2. **Then apply the identical shell to Career** (bigger lift — Career
   currently has zero tab-bar structure, it's still Bento-of-6-tiles):
   - Tabs: Dashboard, Opportunities, Applications, AI
   - Dashboard tab shows: Today's Brief, Deadlines, AI Suggestions (new
     content, doesn't exist yet — needs light backend work, e.g.
     "deadlines" = opportunities sorted by nearest deadline)
   - Opportunities tab = the existing `axe_career_opportunities.html`
     logic, ported into a tab pane
   - **Applications tab = opportunities filtered to a new `applied`
     status** — don't build a new table, just add one more allowed
     value to the existing `opportunities.status` column (currently
     `new`/`saved`/`dismissed` in `career.py`'s
     `set_opportunity_status()` — add `'applied'`)
   - AI tab = `axe_career_chat.html`'s logic, ported into a tab pane
3. **Research/Travel/Network/Vault get the same tab-bar shell today,
   even with no real data** — empty states inside each tab, not the
   current dimmed-dead-link stub pages. This was Mike's explicit
   "consistent, easy to expand" philosophy.

---

## 8. Open questions — unresolved when this was exported

Ask Mike these before building further, don't assume:

1. **AI tab visual treatment**: confirm it should be a raised/enlarged
   center button in the bottom nav (like Cash App's center button
   pattern) using the 🪓 mark — Mike's answer was heading this direction
   but got tangled with a mis-communication about numbering; get an
   explicit yes/no on this specific detail before implementing.
2. **Do the standalone chat pages retire?** Once AI is an embedded tab
   inside each Agent's shell, should `/cfo` and `/axe-career-chat`
   (today's separate full-page chatbots) be deleted, or kept alive as
   bonus direct-link routes? Not yet answered.
3. **Vault de-duplication implementation**: Mike agreed Vault should be
   one shared thing, not "Career Vault" + home "Vault Agent" as two
   concepts — but the actual code fix (making Career's vault tab a
   filtered view into one real Vault backend) hasn't been built, because
   Vault itself doesn't have a backend yet. Whoever builds Vault should
   build it once, then give Career a filtered view, not a parallel table.
4. Check whether other cross-agent overlaps exist before building each
   one blind (Mike flagged this himself) — e.g. does "Timeline" in
   Career overlap with anything at the home level? Worth a quick sanity
   pass before each new Agent is built.

---

## 9. Explicitly NOT built yet — don't assume these exist

- Global home-screen "Ask Axe" router/classifier (Finance vs. Career vs.
  future agents) — visual stub only, says "can't act yet" if you type
  into it
- Research, Travel, Network, Vault — **zero backend**, no DB tables, no
  real logic, just placeholder tiles/stub pages today
- Ideas, Settings — dropped from the home screen entirely per Mike's
  latest 6-card spec (were part of an earlier 8-tile draft, now retired)
- Any multi-user support, any auth beyond the single shared password
- Any deployment automation — Mike copies files into his GitHub repo
  manually and lets Render auto-deploy; there's no CI/CD to configure

---

## 10. File manifest (in the accompanying zip)

| File | Role |
|---|---|
| `render_main.py` | Main Flask app — every route, all API endpoints, DB helpers, scheduled jobs |
| `core.py` | Finance domain logic — categories, accounts, DB schema/init, Excel export |
| `receipt_parser.py` | AI vision + OCR receipt parsing for Finance |
| `career.py` | Career domain logic — profile, Tavily search, scoring, chat system prompt |
| `dashboard.html` | Axe Finance's main SPA (tab-bar reference implementation) |
| `cfo-finance-bot.html` | Finance's standalone chatbot page (mid-rebuild — see Section 7) |
| `axe_home.html` | Home screen Bento grid |
| `axe_career_home.html` | Career's mini-Bento landing (being replaced by tab-bar shell) |
| `axe_career_opportunities.html` | Career's opportunity results grid + profile form |
| `axe_career_chat.html` | Career's standalone chatbot page (mid-rebuild — see Section 7) |
| `Dockerfile` | Container build — note it still does `COPY finance.db .`; the real repo must keep its bundled `finance.db` snapshot file, which is NOT in this zip (it's Mike's live data structure, not something to regenerate) |
| `entrypoint.sh` | Container startup — copies bundled `finance.db` to the persistent volume only on first-ever run, never overwrites existing data |
| `requirements.txt` | Python deps — unchanged from original Axe Finance, no new packages needed for anything built so far |

**Env vars required on Render**: `DASHBOARD_PASSWORD`, `FLASK_SECRET_KEY`,
`GEMINI_API_KEY` (Finance + Career chat both use it), `TAVILY_API_KEY`
(Career search), `AUTHORIZED_USER_ID`, optionally
`GOOGLE_SERVICE_ACCOUNT_JSON` / `RESEND_API_KEY` / `BACKUP_EMAIL_TO` for
Finance's existing backup features (pre-existing, unrelated to this
project).

---

## 11. How to pick this up

1. Read Sections 6 and 8 first — know what's locked vs. still open.
2. Get explicit answers to the 4 questions in Section 8 before building.
3. Rebuild Finance's shell (Section 7, step 1) — smallest, safest first
   move, proves the pattern before touching Career.
4. Then rebuild Career's shell (Section 7, step 2).
5. Then decide, with Mike, whether to stamp the same empty shell onto
   Research/Travel/Network/Vault now or wait until each has real data.
6. Always deliver a complete zip, never a patch — Mike doesn't code.
7. Never touch the color/theme system. Never rename "Axe" back to
   "Atlas." Never fabricate a status number for an Agent with no
   backend.
