import os
import logging
import sqlite3
import calendar
import hashlib
import secrets
import json
import shutil
import io
import base64 as _b64
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, jsonify, send_file, request, redirect,
                   make_response, session, Response)
from threading import Thread
import time
import requests
import pytz

# ── Axe Finance is a pure web app now — no Telegram anywhere ─────────────────
import core
from core import (
    AUTHORIZED_USER_ID, CATEGORY_LIST, INCOME_CATEGORY_LIST,
    init_db as core_init_db, process_due_subscriptions,
    generate_monthly_excel, upload_to_gdrive, GDRIVE_AVAILABLE,
    send_excel_email,
)
from receipt_parser import create_parser

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

# ── Receipt scanning (AI vision via OpenAI, same engine the old bot used) ────
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
_ai_client = None
if OPENAI_API_KEY and OPENAI_API_KEY.strip():
    try:
        from openai import OpenAI
        _ai_client = OpenAI()
        logging.info("OpenAI client initialized for receipt scanning.")
    except Exception as e:
        logging.warning(f"Could not initialize OpenAI client: {e}. Receipt scanning will use OCR fallback only.")

receipt_parser = create_parser(openai_client=_ai_client)

# ── Config ──────────────────────────────────────────────────────────────────
DATABASE   = '/data/finance.db'
BANGKOK_TZ = pytz.timezone('Asia/Bangkok')
DASHBOARD_HTML = '/app/dashboard.html'

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=30)

# ── Auth ─────────────────────────────────────────────────────────────────────
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')

def _check_auth(password):
    if not DASHBOARD_PASSWORD:
        return True
    return secrets.compare_digest(
        hashlib.sha256(password.encode()).hexdigest(),
        hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()
    )

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_PASSWORD:
            return f(*args, **kwargs)
        if session.get('authenticated'):
            return f(*args, **kwargs)
        return redirect('/login')
    return decorated

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def now_bkk():
    return datetime.now(BANGKOK_TZ)

# ── Health ───────────────────────────────────────────────────────────────────
@app.route('/')
def health_check():
    return "Bot is running!", 200

# ── Short URL ────────────────────────────────────────────────────────────────
@app.route('/d')
@require_auth
def dashboard_short():
    return redirect('/dashboard', code=302)

# ── Login / Logout ────────────────────────────────────────────────────────────
LOGIN_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Mike Finance</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;-webkit-font-smoothing:antialiased}
body{font-family:'DM Sans',sans-serif;background:#f5f5f7;display:flex;align-items:center;justify-content:center;min-height:100vh}
@media(prefers-color-scheme:dark){
  body{background:#000000}
  .w{background:#1c1c1e;border-color:rgba(255,255,255,.08)}
  .t{color:#f5f5f7;-webkit-text-fill-color:#f5f5f7}
  .s{color:#aeaeb2}
  input{background:#2c2c2e;border-color:rgba(255,255,255,.1);color:#f5f5f7}
  input::placeholder{color:#636366}
  input:focus{border-color:rgba(255,255,255,.35);box-shadow:0 0 0 3px rgba(255,255,255,.08)}
  .er{background:rgba(255,69,58,.12);color:#ff453a}
  .btn{background:#f5f5f7;color:#1d1d1f;box-shadow:0 6px 20px rgba(0,0,0,.3)}
}
.w{background:#fff;border:1px solid rgba(0,0,0,.08);border-radius:24px;padding:44px 36px;width:min(360px,92vw);box-shadow:0 20px 60px rgba(0,0,0,.08);display:flex;flex-direction:column;align-items:center}
.lr{width:64px;height:64px;border-radius:18px;background:#1d1d1f;display:grid;place-items:center;margin-bottom:20px;box-shadow:0 8px 24px rgba(0,0,0,.2)}
.t{font-family:'Anton',sans-serif;font-size:24px;letter-spacing:1px;color:#1d1d1f;margin-bottom:4px}
.s{font-size:13px;color:#8899bb;margin-bottom:32px}
.f{width:100%}
.iw{position:relative;margin-bottom:14px}
.li{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#99aac8;pointer-events:none}
input{width:100%;padding:13px 16px 13px 42px;border:1.5px solid rgba(0,0,0,.12);border-radius:12px;background:#f5f5f7;color:#1d1d1f;font-size:15px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .18s,box-shadow .18s}
input:focus{border-color:rgba(0,0,0,.35);box-shadow:0 0 0 3px rgba(0,0,0,.06)}
input::placeholder{color:#aeaeb2}
.btn{width:100%;padding:14px;border:none;border-radius:12px;background:#1d1d1f;color:#fff;font-size:15px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.15);transition:opacity .18s}
.btn:active{opacity:.85}
.er{width:100%;margin-bottom:14px;padding:11px 14px;background:#fee2e2;color:#ef4444;border-radius:10px;font-size:13px;font-weight:500}
</style>
</head>
<body>
<div class="w">
  <div class="lr">
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2">
      <path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>
    </svg>
  </div>
  <div class="t">MIKE FINANCE</div>
  <div class="s">Personal Finance Dashboard</div>
  {error_html}
  <form class="f" method="POST" action="/login">
    <div class="iw">
      <svg class="li" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="11" width="18" height="11" rx="2"/>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
      <input type="password" name="password" placeholder="Enter your password" autofocus autocomplete="current-password">
    </div>
    <button type="submit" class="btn">Unlock Dashboard</button>
  </form>
</div>
</body>
</html>'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if _check_auth(password):
            session['authenticated'] = True
            session.permanent = True
            return redirect('/dashboard')
        error = 'Wrong password. Try again.'
    error_html = f'<div class="er">{error}</div>' if error else ''
    resp = make_response(LOGIN_HTML.replace('{error_html}', error_html))
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ── Dashboard ────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@require_auth
def dashboard():
    return send_file(DASHBOARD_HTML)

# ── API: Balances ─────────────────────────────────────────────────────────────
@app.route('/api/balances')
@require_auth
def api_balances():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT name, balance FROM accounts ORDER BY id")
    data = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(data)

# ── API: Summary ──────────────────────────────────────────────────────────────
@app.route('/api/summary')
@require_auth
def api_summary():
    conn = get_db(); c = conn.cursor()
    now = now_bkk()
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if this_start.month == 1:
        last_start = this_start.replace(year=this_start.year - 1, month=12)
    else:
        last_start = this_start.replace(month=this_start.month - 1)

    def month_totals(s, e):
        c.execute(
            """SELECT type, SUM(ABS(amount)) as total FROM transactions
               WHERE timestamp >= ? AND timestamp < ? AND type != 'transfer'
               GROUP BY type""", (s, e))
        r = {row['type']: float(row['total'] or 0) for row in c.fetchall()}
        return r.get('income', 0.0), r.get('expense', 0.0)

    ti, te = month_totals(this_start.strftime('%Y-%m-%d %H:%M:%S'), now.strftime('%Y-%m-%d %H:%M:%S'))
    li, le = month_totals(last_start.strftime('%Y-%m-%d %H:%M:%S'), this_start.strftime('%Y-%m-%d %H:%M:%S'))
    conn.close()
    return jsonify({
        'this_month': {'income': ti, 'expense': te, 'net': ti - te},
        'last_month': {'income': li, 'expense': le, 'net': li - le}
    })

# ── API: Categories (top categories used this month, for charts) ─────────────
@app.route('/api/categories')
@require_auth
def api_categories():
    conn = get_db(); c = conn.cursor()
    ms = now_bkk().replace(day=1, hour=0, minute=0, second=0).strftime('%Y-%m-%d')
    c.execute(
        """SELECT category, SUM(ABS(amount)) as total FROM transactions
           WHERE type='expense' AND timestamp >= ?
           GROUP BY category ORDER BY total DESC LIMIT 8""", (ms,))
    data = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(data)

# ── API: Full category lists (for Add Income / Add Expense dropdowns) ────────
# Sourced from the same CATEGORY_LIST / INCOME_CATEGORY_LIST the Telegram bot
# uses, so the dashboard dropdowns never drift out of sync with the bot menus.
@app.route('/api/category-lists')
@require_auth
def api_category_lists():
    return jsonify({
        'expense': [{'name': name, 'emoji': emoji} for emoji, name in CATEGORY_LIST],
        'income': [{'name': name, 'emoji': emoji} for emoji, name in INCOME_CATEGORY_LIST]
    })

# ── API: Monthly trend ────────────────────────────────────────────────────────
@app.route('/api/monthly')
@require_auth
def api_monthly():
    conn = get_db(); c = conn.cursor()
    now = now_bkk(); monthly = []
    for i in range(5, -1, -1):
        m = now.month - i; y = now.year
        while m <= 0: m += 12; y -= 1
        ms = f"{y}-{m:02d}-01"
        me = f"{y+1}-01-01" if m == 12 else f"{y}-{m+1:02d}-01"
        c.execute(
            """SELECT type, SUM(ABS(amount)) as total FROM transactions
               WHERE timestamp >= ? AND timestamp < ? AND type != 'transfer'
               GROUP BY type""", (ms, me))
        r = {row['type']: float(row['total'] or 0) for row in c.fetchall()}
        monthly.append({'month': calendar.month_abbr[m], 'income': r.get('income', 0.0), 'expense': r.get('expense', 0.0)})
    conn.close()
    return jsonify(monthly)

# ── API: Recent transactions ──────────────────────────────────────────────────
@app.route('/api/transactions', methods=['GET'])
@require_auth
def api_transactions():
    conn = get_db(); c = conn.cursor()
    c.execute(
        """SELECT amount, description, type, category, account, timestamp
           FROM transactions ORDER BY timestamp DESC LIMIT 30""")
    data = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(data)

# ── API: Add a transaction (Quick Actions — Add Income / Add Expense) ────────
@app.route('/api/transactions', methods=['POST'])
@require_auth
def api_add_transaction():
    data = request.get_json(silent=True) or {}

    txn_type = (data.get('type') or '').strip().lower()
    if txn_type not in ('income', 'expense'):
        return jsonify({'error': "type must be 'income' or 'expense'"}), 400

    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid amount'}), 400
    if amount <= 0:
        return jsonify({'error': 'Amount must be greater than zero'}), 400

    category = (data.get('category') or 'Other').strip() or 'Other'
    account  = (data.get('account') or 'Cash').strip() or 'Cash'
    description = (data.get('description') or '').strip() or category

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM accounts WHERE name = ?", (account,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': f"Account '{account}' not found"}), 400

    signed_amount = amount if txn_type == 'income' else -amount
    ts = now_bkk().strftime('%Y-%m-%d %H:%M:%S')

    c.execute(
        """INSERT INTO transactions (user_id, amount, description, type, category, account, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (AUTHORIZED_USER_ID, signed_amount, description, txn_type, category, account, ts)
    )
    c.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (signed_amount, account))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── API: Transfer funds between accounts (Quick Actions — Transfer Funds) ────
@app.route('/api/transfer', methods=['POST'])
@require_auth
def api_transfer():
    data = request.get_json(silent=True) or {}

    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid amount'}), 400
    if amount <= 0:
        return jsonify({'error': 'Amount must be greater than zero'}), 400

    from_account = (data.get('from_account') or '').strip()
    to_account   = (data.get('to_account') or '').strip()
    if not from_account or not to_account:
        return jsonify({'error': 'Both accounts are required'}), 400
    if from_account == to_account:
        return jsonify({'error': 'From and To accounts must be different'}), 400

    conn = get_db(); c = conn.cursor()
    c.execute("SELECT 1 FROM accounts WHERE name = ?", (from_account,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': f"Account '{from_account}' not found"}), 400
    c.execute("SELECT 1 FROM accounts WHERE name = ?", (to_account,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': f"Account '{to_account}' not found"}), 400

    ts = now_bkk().strftime('%Y-%m-%d %H:%M:%S')
    c.execute(
        """INSERT INTO transactions (user_id, amount, description, type, category, account, timestamp)
           VALUES (?, ?, ?, 'transfer', 'Transfer', ?, ?)""",
        (AUTHORIZED_USER_ID, -amount, f"Transfer to {to_account}", from_account, ts)
    )
    c.execute(
        """INSERT INTO transactions (user_id, amount, description, type, category, account, timestamp)
           VALUES (?, ?, ?, 'transfer', 'Transfer', ?, ?)""",
        (AUTHORIZED_USER_ID, amount, f"Transfer from {from_account}", to_account, ts)
    )
    c.execute("UPDATE accounts SET balance = balance - ? WHERE name = ?", (amount, from_account))
    c.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (amount, to_account))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── API: Month detail ─────────────────────────────────────────────────────────
@app.route('/api/month/<int:year>/<int:month>')
@require_auth
def api_month_detail(year, month):
    conn = get_db(); c = conn.cursor()
    ms = f"{year}-{month:02d}-01"
    me = f"{year+1}-01-01" if month == 12 else f"{year}-{month+1:02d}-01"
    c.execute(
        """SELECT type, SUM(ABS(amount)) as total FROM transactions
           WHERE timestamp >= ? AND timestamp < ? AND type != 'transfer'
           GROUP BY type""", (ms, me))
    totals = {row['type']: float(row['total'] or 0) for row in c.fetchall()}
    inc = totals.get('income', 0.0); exp = totals.get('expense', 0.0)
    c.execute(
        """SELECT category, SUM(ABS(amount)) as total FROM transactions
           WHERE type='expense' AND timestamp >= ? AND timestamp < ?
           GROUP BY category ORDER BY total DESC""", (ms, me))
    cats = [dict(r) for r in c.fetchall()]
    c.execute(
        """SELECT amount, description, type, category, account, timestamp
           FROM transactions WHERE timestamp >= ? AND timestamp < ?
           ORDER BY timestamp DESC""", (ms, me))
    txns = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'year': year, 'month': month, 'income': inc,
                    'expense': exp, 'net': inc - exp,
                    'categories': cats, 'transactions': txns})

# ── API: List months ──────────────────────────────────────────────────────────
@app.route('/api/months')
@require_auth
def api_months():
    conn = get_db(); c = conn.cursor()
    c.execute("""SELECT DISTINCT strftime('%Y', timestamp) as year,
                               strftime('%m', timestamp) as month
               FROM transactions ORDER BY year DESC, month DESC""")
    data = [{'year': int(r['year']), 'month': int(r['month'])} for r in c.fetchall()]
    conn.close()
    return jsonify(data)

# ── PWA Assets ────────────────────────────────────────────────────────────────
_ICON_192 = "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"
_ICON_512 = "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"

@app.route('/manifest.json')
def pwa_manifest():
    m = {"name":"Mike Finance","short_name":"Finance","description":"Personal finance tracker",
         "start_url":"/dashboard","display":"standalone","background_color":"#000000",
         "theme_color":"#1d1d1f","orientation":"portrait",
         "icons":[{"src":"/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any maskable"},
                  {"src":"/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any maskable"}]}
    return Response(json.dumps(m), mimetype='application/json')

@app.route('/icon-192.png')
def icon_192():
    return Response(_b64.b64decode(_ICON_192), mimetype='image/png',
                    headers={"Cache-Control":"public, max-age=604800"})

@app.route('/icon-512.png')
def icon_512():
    return Response(_b64.b64decode(_ICON_512), mimetype='image/png',
                    headers={"Cache-Control":"public, max-age=604800"})

@app.route('/sw.js')
def service_worker():
    sw = """
const C='mf-v7';
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(['/dashboard','/icon-192.png'])));self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',e=>{
  if(e.request.url.includes('/api/')||e.request.url.includes('/login')||e.request.url.includes('/logout')){
    e.respondWith(fetch(e.request));
  } else {
    e.respondWith(fetch(e.request).then(r=>{const cl=r.clone();caches.open(C).then(c=>c.put(e.request,cl));return r;}).catch(()=>caches.match(e.request)));
  }
});
"""
    return Response(sw, mimetype='application/javascript',
                    headers={"Service-Worker-Allowed": "/"})

# ── Axe CFO Chatbot ───────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL   = 'gemini-2.5-flash'
GEMINI_URL     = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}'
CFO_HTML       = '/app/cfo-finance-bot.html'


def build_axe_system_prompt():
    conn = get_db()
    cur  = conn.cursor()
    now  = now_bkk()

    cur.execute("SELECT name, balance FROM accounts ORDER BY balance DESC")
    accounts      = [dict(r) for r in cur.fetchall()]
    total_balance = sum(a['balance'] for a in accounts)

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ms = month_start.strftime('%Y-%m-%d %H:%M:%S')
    ns = now.strftime('%Y-%m-%d %H:%M:%S')

    cur.execute("""SELECT type, SUM(ABS(amount)) as total FROM transactions
                 WHERE timestamp >= ? AND timestamp < ? AND type != 'transfer'
                 GROUP BY type""", (ms, ns))
    month_totals = {row['type']: float(row['total'] or 0) for row in cur.fetchall()}
    this_income  = month_totals.get('income', 0)
    this_expense = month_totals.get('expense', 0)

    if month_start.month == 1:
        last_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        last_start = month_start.replace(month=month_start.month - 1)
    ls = last_start.strftime('%Y-%m-%d %H:%M:%S')

    cur.execute("""SELECT type, SUM(ABS(amount)) as total FROM transactions
                 WHERE timestamp >= ? AND timestamp < ? AND type != 'transfer'
                 GROUP BY type""", (ls, ms))
    last_totals  = {row['type']: float(row['total'] or 0) for row in cur.fetchall()}
    last_income  = last_totals.get('income', 0)
    last_expense = last_totals.get('expense', 0)

    cur.execute("""SELECT category, SUM(ABS(amount)) as total, COUNT(*) as count
                 FROM transactions
                 WHERE type='expense' AND timestamp >= ?
                 GROUP BY category ORDER BY total DESC""", (ms,))
    categories = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT name, amount, account, next_due_date
                 FROM recurring_subscriptions ORDER BY next_due_date""")
    subscriptions = [dict(r) for r in cur.fetchall()]
    total_subs    = sum(s['amount'] for s in subscriptions)

    cur.execute("""SELECT amount, description, type, category, account, timestamp
                 FROM transactions ORDER BY timestamp DESC LIMIT 20""")
    recent = [dict(r) for r in cur.fetchall()]
    conn.close()

    days_elapsed      = max(now.day, 1)
    daily_avg         = this_expense / days_elapsed if days_elapsed > 0 else 0
    projected_monthly = daily_avg * 30
    savings_rate      = (((this_income - this_expense) / this_income) * 100) if this_income > 0 else 0

    accounts_str   = ' | '.join([f"{a['name']}: ฿{a['balance']:,.2f}" for a in accounts])
    categories_str = '\n'.join([f"- {cat['category']}: ฿{cat['total']:,.2f} ({cat['count']} transactions)" for cat in categories]) or 'No expenses yet'
    subs_str       = '\n'.join([f"- {s['name']}: ฿{s['amount']}/month from {s['account']}, next due {s['next_due_date']}" for s in subscriptions]) or 'None'
    recent_str     = '\n'.join([f"- {t['timestamp'][:10]}: {t['description']} ฿{abs(t['amount']):,.2f} [{t['category']}] {'IN' if t['amount'] > 0 else 'OUT'} ({t['account']})" for t in recent])

    return f"""You are Axe, Mike's personal finance advisor based in Bangkok, Thailand. You are backed by a team of 10 specialist finance managers who silently brief you before every response. You synthesize their insights and speak directly to Mike — one voice, one answer.

YOUR 10 SPECIALIST MANAGERS (internal only, Mike never sees them):
1. SPENDING ANALYST — patterns, spikes, latte factor
2. BUDGET COACH — 50/30/20 rule, Bangkok benchmarks
3. SUBSCRIPTION AUDITOR — cost vs value, duplicates
4. CASH FLOW MANAGER — liquidity, pay-yourself-first
5. CATEGORY SPECIALIST — healthy ratios per category
6. SAVINGS ADVISOR — emergency fund, savings rate targets
7. TRANSPORT TRACKER — BTS/MRT vs Grab/Bolt optimization
8. FOOD & LIFESTYLE MONITOR — street food vs restaurant balance
9. INVESTMENT TRACKER — surplus allocation, Thai SSF/RMF
10. MONTHLY HISTORIAN — trends, month-over-month, wins

YOUR PERSONALITY:
- Direct, confident, no fluff
- Bangkok lifestyle aware (BTS, Grab, street food, malls, nightlife)
- Always speaks in Thai Baht (฿)
- Blunt when needed, positive when deserved
- Specific actions not generic tips
- Use **bold** for key numbers
- Max 200 words unless full review requested
- Never make up numbers — only use data below

MIKE'S REAL-TIME DATA:

NET WORTH: ฿{total_balance:,.2f}
Accounts: {accounts_str}

THIS MONTH ({now.strftime('%B %Y')}):
- Income: ฿{this_income:,.2f}
- Expenses: ฿{this_expense:,.2f}
- Net: ฿{this_income - this_expense:,.2f}
- Savings Rate: {savings_rate:.1f}%
- Days elapsed: {days_elapsed} | Daily avg: ฿{daily_avg:,.0f} | Projected: ฿{projected_monthly:,.0f}

LAST MONTH:
- Income: ฿{last_income:,.2f} | Expenses: ฿{last_expense:,.2f} | Net: ฿{last_income - last_expense:,.2f}

SPENDING BY CATEGORY THIS MONTH:
{categories_str}

SUBSCRIPTIONS (Total: ฿{total_subs:,.2f}/month):
{subs_str}

RECENT TRANSACTIONS (last 20):
{recent_str}"""


@app.route('/cfo')
@require_auth
def cfo_page():
    return send_file(CFO_HTML)


@app.route('/api/cfo-chat', methods=['POST'])
@require_auth
def api_cfo_chat():
    try:
        if not GEMINI_API_KEY:
            return jsonify({'reply': 'Axe is not configured. Add GEMINI_API_KEY to your Render environment variables.'}), 200

        data     = request.get_json()
        messages = data.get('messages', [])
        if not messages:
            return jsonify({'reply': 'Hey Mike, ask me something about your finances!'}), 200

        system_prompt   = build_axe_system_prompt()
        gemini_contents = []
        for msg in messages:
            role = 'user' if msg['role'] == 'user' else 'model'
            gemini_contents.append({'role': role, 'parts': [{'text': msg['content']}]})

        payload = {
            'system_instruction': {'parts': [{'text': system_prompt}]},
            'contents': gemini_contents,
            'generationConfig': {'maxOutputTokens': 1200, 'temperature': 0.7}
        }

        resp = requests.post(
            GEMINI_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )

        if resp.status_code != 200:
            logging.error(f"Gemini API error: {resp.status_code} {resp.text}")
            return jsonify({'reply': 'Sorry, had trouble thinking. Please try again.'}), 200

        result     = resp.json()
        reply_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

        if not reply_text:
            return jsonify({'reply': "Couldn't generate a response. Please rephrase."}), 200

        return jsonify({'reply': reply_text})

    except Exception as e:
        logging.error(f"Axe chat error: {e}")
        return jsonify({'reply': f'Error: {str(e)}'}), 200


# ── Receipt Scanning (replaces the old Telegram photo handler) ───────────────
@app.route('/api/scan-receipt', methods=['POST'])
@require_auth
def api_scan_receipt():
    """
    Accepts a multipart/form-data upload:
      - photo: the receipt/bank-slip image (required)
      - caption: optional text the user typed alongside it (overrides
                 description/category detection, same as the old Telegram bot)
    Parses it with the same ReceiptParser (AI vision + OCR fallback) the
    Telegram bot used to use, logs the transaction, and returns the result
    so the Axe chat UI can show it and offer an Undo.
    """
    try:
        if 'photo' not in request.files or not request.files['photo'].filename:
            return jsonify({'success': False, 'error': 'No photo was uploaded.'}), 400

        photo_file = request.files['photo']
        photo_bytes = photo_file.read()
        if not photo_bytes:
            return jsonify({'success': False, 'error': 'The uploaded photo was empty.'}), 400

        caption = (request.form.get('caption') or '').strip()

        result = receipt_parser.parse(photo_bytes, caption=caption or None)

        if not result.amount or result.amount <= 0:
            return jsonify({
                'success': False,
                'error': "Couldn't read an amount from this receipt. Try a clearer photo, or log it manually from Quick Actions."
            }), 200

        amount = round(float(result.amount), 2)
        description = (result.description or 'Receipt scan').strip() or 'Receipt scan'
        category = result.category or 'Other'
        account = result.account or 'Bangkok Bank'

        conn = get_db()
        c = conn.cursor()

        # Make sure the detected account actually exists — fall back to Cash.
        c.execute("SELECT 1 FROM accounts WHERE name = ?", (account,))
        if not c.fetchone():
            account = 'Cash'

        ts = now_bkk().strftime('%Y-%m-%d %H:%M:%S')

        # ── Transfer (e.g. top-up to True Money / Rabbit / MRT) ──────────────
        if result.is_transfer:
            to_account = result.transfer_to or 'Cash'
            c.execute("SELECT 1 FROM accounts WHERE name = ?", (to_account,))
            if not to_account or not c.fetchone():
                to_account = 'Cash'
            if to_account == account:
                to_account = 'Cash' if account != 'Cash' else 'Bangkok Bank'

            c.execute(
                """INSERT INTO transactions (user_id, amount, description, type, category, account, timestamp)
                   VALUES (?, ?, ?, 'transfer', 'Transfer', ?, ?)""",
                (AUTHORIZED_USER_ID, -amount, f"Transfer to {to_account}", account, ts)
            )
            c.execute(
                """INSERT INTO transactions (user_id, amount, description, type, category, account, timestamp)
                   VALUES (?, ?, ?, 'transfer', 'Transfer', ?, ?)""",
                (AUTHORIZED_USER_ID, amount, f"Transfer from {account}", to_account, ts)
            )
            c.execute("UPDATE accounts SET balance = balance - ? WHERE name = ?", (amount, account))
            c.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (amount, to_account))
            conn.commit()
            conn.close()
            return jsonify({
                'success': True,
                'type': 'transfer',
                'amount': amount,
                'from_account': account,
                'to_account': to_account,
                'method': result.method,
            })

        # ── Regular income / expense ──────────────────────────────────────────
        txn_type = 'income' if result.direction == 'IN' else 'expense'
        signed_amount = amount if txn_type == 'income' else -amount

        c.execute(
            """INSERT INTO transactions (user_id, amount, description, type, category, account, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (AUTHORIZED_USER_ID, signed_amount, description, txn_type, category, account, ts)
        )
        c.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (signed_amount, account))
        conn.commit()
        c.execute("SELECT balance FROM accounts WHERE name = ?", (account,))
        new_balance = c.fetchone()['balance']
        conn.close()

        return jsonify({
            'success': True,
            'type': txn_type,
            'amount': amount,
            'description': description,
            'category': category,
            'account': account,
            'new_balance': new_balance,
            'method': result.method,
        })

    except Exception as e:
        logging.error(f"scan-receipt error: {e}")
        return jsonify({'success': False, 'error': 'Server error while scanning the receipt. Please try again.'}), 500


# ── Undo — deletes the most recent transaction (mirrors the old /delete) ─────
@app.route('/api/delete-last-transaction', methods=['POST'])
@require_auth
def api_delete_last_transaction():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT id, amount, account, description FROM transactions ORDER BY id DESC LIMIT 1"
        )
        txn = c.fetchone()
        if not txn:
            conn.close()
            return jsonify({'success': False, 'error': 'No transactions to undo.'}), 200

        c.execute("DELETE FROM transactions WHERE id = ?", (txn['id'],))
        c.execute("UPDATE accounts SET balance = balance - ? WHERE name = ?", (txn['amount'], txn['account']))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'description': txn['description']})
    except Exception as e:
        logging.error(f"delete-last-transaction error: {e}")
        return jsonify({'success': False, 'error': 'Server error. Please try again.'}), 500


# ── Database Backup (replaces the old Telegram /backup command) ──────────────
@app.route('/backup')
@require_auth
def download_backup():
    if not os.path.exists(DATABASE):
        return jsonify({"error": "Database file not found."}), 404
    now_str = now_bkk().strftime('%Y%m%d_%H%M')
    filename = f"finance_backup_{now_str}.db"
    return send_file(DATABASE, as_attachment=True, download_name=filename, mimetype='application/x-sqlite3')


# ── Monthly Report Export (polished 3-sheet Excel — Summary/Transactions/By Category) ──
@app.route('/export')
@require_auth
def download_export():
    """Download the polished monthly Excel report straight from the browser.
    Query params: ?year=YYYY&month=MM — defaults to the current Bangkok month."""
    try:
        now = now_bkk()
        year = request.args.get('year', type=int) or now.year
        month = request.args.get('month', type=int) or now.month
        if not (1 <= month <= 12):
            month = now.month

        excel_bytes = generate_monthly_excel(year, month)
        filename = f"Axe_Finance_{calendar.month_name[month]}_{year}.xlsx"
        return send_file(
            io.BytesIO(excel_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logging.error(f"export error: {e}")
        return jsonify({"error": "Could not generate the export. Please try again."}), 500


# ── Manual email backup test (now via Resend, since Render blocks SMTP) ─────
@app.route('/api/test-email-backup', methods=['POST', 'GET'])
@require_auth
def api_test_email_backup():
    """
    Manually trigger a monthly Excel export via email right now, instead of
    waiting for the 1st-of-month scheduled job. Lets you verify the whole
    pipeline (Resend API key -> send) without waiting.
    Usage: GET or POST /api/test-email-backup?year=2026&month=6
    Defaults to last month if year/month aren't given.
    """
    try:
        now = now_bkk()
        try:
            year = int(request.args.get('year', 0)) or (now.year if now.month > 1 else now.year - 1)
            month = int(request.args.get('month', 0)) or (now.month - 1 if now.month > 1 else 12)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'year/month must be integers, e.g. ?year=2026&month=6'}), 400

        diagnostics = {
            'resend_api_key_set': bool(os.environ.get('RESEND_API_KEY', '').strip()),
            'destination_email': os.environ.get('BACKUP_EMAIL_TO', '').strip() or 'NOT SET',
        }

        if not diagnostics['resend_api_key_set'] or diagnostics['destination_email'] == 'NOT SET':
            return jsonify({
                'success': False,
                'error': 'RESEND_API_KEY or BACKUP_EMAIL_TO environment variable is not set on Render.',
                'hint': 'Add RESEND_API_KEY (from resend.com → API Keys) and BACKUP_EMAIL_TO (the same email you signed up to Resend with, unless you have a verified custom domain).',
                'diagnostics': diagnostics,
            }), 200

        excel_bytes = generate_monthly_excel(year, month)
        filename = f"Axe_Finance_TEST_{calendar.month_name[month]}_{year}.xlsx"
        subject = f"Axe Finance — {calendar.month_name[month]} {year} Export (Test)"
        body = f"This is a manual test of the monthly backup email.\n\nAttached: {filename}"

        error = send_excel_email(excel_bytes, filename, subject, body)

        if not error:
            return jsonify({
                'success': True,
                'message': f'Emailed {filename} to {diagnostics["destination_email"]}.',
                'diagnostics': diagnostics,
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Email send failed: {error}',
                'hint': 'Most common cause on Resend\'s free tier: BACKUP_EMAIL_TO must exactly match the email address you used to sign up for Resend, unless you\'ve verified a custom domain.',
                'diagnostics': diagnostics,
            }), 200

    except Exception as e:
        logging.error(f"test-email-backup error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── Database Restore (replaces the old Telegram /restore document handler) ───
@app.route('/api/restore', methods=['POST'])
@require_auth
def api_restore():
    try:
        if 'backup' not in request.files or not request.files['backup'].filename:
            return jsonify({'success': False, 'error': 'No backup file was uploaded.'}), 400

        upload = request.files['backup']
        if not upload.filename.endswith('.db'):
            return jsonify({'success': False, 'error': "Please upload a '.db' file."}), 400

        file_bytes = upload.read()
        if not file_bytes:
            return jsonify({'success': False, 'error': 'The uploaded file was empty.'}), 400
        if len(file_bytes) > 50 * 1024 * 1024:
            return jsonify({'success': False, 'error': 'File too large. Maximum 50 MB.'}), 400
        if not file_bytes[:16].startswith(b'SQLite format 3'):
            return jsonify({'success': False, 'error': "This doesn't look like a valid SQLite database."}), 400

        tmp_path = '/tmp/restore_check.db'
        with open(tmp_path, 'wb') as f:
            f.write(file_bytes)

        try:
            vconn = sqlite3.connect(tmp_path)
            vc = vconn.cursor()
            vc.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in vc.fetchall()}
            required = {'transactions', 'accounts', 'recurring_subscriptions'}
            if not required.issubset(tables):
                vconn.close()
                missing = required - tables
                return jsonify({'success': False, 'error': f"Missing required tables: {', '.join(missing)}. This doesn't look like an Axe Finance backup."}), 400

            txn_cnt = vc.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            acc_cnt = vc.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            sub_cnt = vc.execute("SELECT COUNT(*) FROM recurring_subscriptions").fetchone()[0]
            vconn.close()
        except Exception as ve:
            return jsonify({'success': False, 'error': f'Could not open the database: {ve}'}), 400

        # Safety copy of the current live DB before overwriting.
        if os.path.exists(DATABASE):
            shutil.copy2(DATABASE, DATABASE + '.before_restore')

        shutil.copy2(tmp_path, DATABASE)
        logging.info(f"Database restored from uploaded file: {upload.filename}")

        return jsonify({
            'success': True,
            'transactions': txn_cnt,
            'accounts': acc_cnt,
            'subscriptions': sub_cnt,
        })
    except Exception as e:
        logging.error(f"restore error: {e}")
        return jsonify({'success': False, 'error': 'Server error while restoring. Your original database was not modified.'}), 500


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    # If request wants HTML (browser), redirect to dashboard
    if request.accept_mimetypes.accept_html:
        return redirect('/dashboard')
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

# ── Scheduled jobs (replaces the Telegram bot's JobQueue) ────────────────────
# These used to run inside the Telegram bot's event loop. Now that there's no
# bot, APScheduler runs them directly inside this Flask process.
from apscheduler.schedulers.background import BackgroundScheduler

def _job_process_subscriptions():
    try:
        processed = process_due_subscriptions()
        for name, amount, account, user_id in processed:
            logging.info(f"Auto-logged subscription: {name} -฿{amount:,.2f} from {account}")
    except Exception as e:
        logging.error(f"Subscription check job failed: {e}")

def _job_monthly_email_backup():
    """Runs daily; only actually emails on the 1st of the month, for the
    previous month — same cadence as the old Google Drive job."""
    try:
        now = now_bkk()
        if now.day != 1:
            return
        month = now.month - 1 if now.month > 1 else 12
        year = now.year if now.month > 1 else now.year - 1
        excel_bytes = generate_monthly_excel(year, month)
        filename = f"Axe_Finance_{calendar.month_name[month]}_{year}.xlsx"
        subject = f"Axe Finance — {calendar.month_name[month]} {year} Export"
        body = f"Here's your monthly Axe Finance export.\n\nAttached: {filename}"
        error = send_excel_email(excel_bytes, filename, subject, body)
        if not error:
            logging.info(f"Monthly email backup sent: {filename}")
        else:
            logging.warning(f"Monthly email backup failed for {filename}: {error}")
    except Exception as e:
        logging.error(f"Monthly email backup job failed: {e}")

scheduler = BackgroundScheduler(timezone=BANGKOK_TZ)
scheduler.add_job(_job_process_subscriptions, 'cron', hour=8, minute=0, id='check_subs')
scheduler.add_job(_job_monthly_email_backup, 'cron', hour=9, minute=5, id='monthly_email_backup')

# ── Flask runner ──────────────────────────────────────────────────────────────
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        try:
            requests.get(url)
        except Exception:
            pass
        time.sleep(600)

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    core_init_db()
    logging.info("Database initialized.")

    # Catch any subscriptions that came due while the app was offline.
    _job_process_subscriptions()

    scheduler.start()
    logging.info("Scheduler started. Sub checks: daily 8AM, Email backup: daily 9:05AM (Bangkok time)")

    keep_alive_thread = Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()

    run_flask()
