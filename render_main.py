import os
import logging
import sqlite3
import calendar
import hashlib
import secrets
import json
import base64 as _b64
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, jsonify, send_file, request, redirect,
                   make_response, session, Response)
from threading import Thread
import time
import requests
import pytz
from main import main as bot_main

try:
    from main import AUTHORIZED_USER_ID
except ImportError as e:
    logging.error(f"Could not import AUTHORIZED_USER_ID from main.py: {e}")
    AUTHORIZED_USER_ID = int(os.environ.get('AUTHORIZED_USER_ID', '0'))

try:
    from main import CATEGORY_LIST
except ImportError as e:
    logging.error(f"Could not import CATEGORY_LIST from main.py: {e}")
    CATEGORY_LIST = []

try:
    from main import INCOME_CATEGORY_LIST
except ImportError as e:
    logging.error(f"Could not import INCOME_CATEGORY_LIST from main.py: {e}")
    INCOME_CATEGORY_LIST = []

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

# ── API: Categories ───────────────────────────────────────────────────────────
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
@app.route('/api/transactions')
@require_auth
def api_transactions():
    conn = get_db(); c = conn.cursor()
    c.execute(
        """SELECT amount, description, type, category, account, timestamp
           FROM transactions ORDER BY timestamp DESC LIMIT 30""")
    data = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(data)

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

# ── API: Category lists (for Quick Actions dropdowns) ─────────────────────────
@app.route('/api/category-lists')
@require_auth
def api_category_lists():
    return jsonify({
        'expense': [{'name': name, 'emoji': emoji} for emoji, name in CATEGORY_LIST],
        'income':  [{'name': name, 'emoji': emoji} for emoji, name in INCOME_CATEGORY_LIST]
    })

# ── API: Add income/expense transaction (Quick Actions) ───────────────────────
@app.route('/api/add-transaction', methods=['POST'])
@require_auth
def api_add_transaction():
    try:
        data = request.get_json(force=True, silent=True) or {}
        txn_type = data.get('type')
        if txn_type not in ('income', 'expense'):
            return jsonify({'success': False, 'error': 'Invalid transaction type.'}), 400

        try:
            amount = float(str(data.get('amount', '')).replace(',', '').replace('฿', ''))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid amount.'}), 400
        if amount <= 0:
            return jsonify({'success': False, 'error': 'Amount must be greater than zero.'}), 400

        category = (data.get('category') or '').strip()
        account = (data.get('account') or '').strip()
        if not category:
            return jsonify({'success': False, 'error': 'Please choose a category.'}), 400
        if not account:
            return jsonify({'success': False, 'error': 'Please choose an account.'}), 400
        description = (data.get('description') or '').strip() or category

        conn = get_db(); c = conn.cursor()
        c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, account))
        if not c.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': f"Account '{account}' not found."}), 400

        signed_amount = amount if txn_type == 'income' else -amount
        c.execute(
            "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, ?, ?, ?)",
            (AUTHORIZED_USER_ID, signed_amount, description, txn_type, category, account)
        )
        c.execute(
            "UPDATE accounts SET balance = balance + ? WHERE user_id = ? AND name = ?",
            (signed_amount, AUTHORIZED_USER_ID, account)
        )
        conn.commit()
        c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, account))
        new_balance = c.fetchone()['balance']
        conn.close()

        return jsonify({'success': True, 'new_balance': new_balance})
    except Exception as e:
        logging.error(f"add-transaction error: {e}")
        return jsonify({'success': False, 'error': 'Server error. Please try again.'}), 500

# ── API: Transfer between accounts (Quick Actions) ────────────────────────────
@app.route('/api/transfer', methods=['POST'])
@require_auth
def api_transfer():
    try:
        data = request.get_json(force=True, silent=True) or {}
        try:
            amount = float(str(data.get('amount', '')).replace(',', '').replace('฿', ''))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid amount.'}), 400
        if amount <= 0:
            return jsonify({'success': False, 'error': 'Amount must be greater than zero.'}), 400

        from_account = (data.get('from_account') or '').strip()
        to_account = (data.get('to_account') or '').strip()
        if not from_account or not to_account:
            return jsonify({'success': False, 'error': 'Please choose both accounts.'}), 400
        if from_account == to_account:
            return jsonify({'success': False, 'error': "From and To accounts can't be the same."}), 400

        conn = get_db(); c = conn.cursor()
        c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, from_account))
        if not c.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': f"Account '{from_account}' not found."}), 400
        c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, to_account))
        if not c.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': f"Account '{to_account}' not found."}), 400

        c.execute("UPDATE accounts SET balance = balance - ? WHERE user_id = ? AND name = ?", (amount, AUTHORIZED_USER_ID, from_account))
        c.execute("UPDATE accounts SET balance = balance + ? WHERE user_id = ? AND name = ?", (amount, AUTHORIZED_USER_ID, to_account))
        c.execute(
            "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, 'transfer', 'Transfer', ?)",
            (AUTHORIZED_USER_ID, -amount, f"Transfer to {to_account}", from_account)
        )
        c.execute(
            "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, 'transfer', 'Transfer', ?)",
            (AUTHORIZED_USER_ID, amount, f"Transfer from {from_account}", to_account)
        )
        conn.commit()

        c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, from_account))
        new_from = c.fetchone()['balance']
        c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, to_account))
        new_to = c.fetchone()['balance']
        conn.close()

        return jsonify({'success': True, 'from_balance': new_from, 'to_balance': new_to})
    except Exception as e:
        logging.error(f"transfer error: {e}")
        return jsonify({'success': False, 'error': 'Server error. Please try again.'}), 500

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
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    keep_alive_thread = Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    bot_main()
