import os
import logging
import sqlite3
import calendar
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_file
from threading import Thread
import time
import requests
import pytz
from main import main as bot_main

# ── Config ─────────────────────────────────────────────────────────────────
DATABASE   = '/data/finance.db'
BANGKOK_TZ = pytz.timezone('Asia/Bangkok')
DASHBOARD_HTML = '/app/dashboard.html'

import hashlib
from datetime import timedelta
import secrets
from functools import wraps
from flask import Flask, jsonify, send_file, request, redirect, url_for, make_response, session

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=30)

# ── Dashboard password ────────────────────────────────────────────────────────
# Set DASHBOARD_PASSWORD in Render environment variables.
# If not set, dashboard is open (only do this if you know what you're doing).
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')

def _check_auth(password):
    """Constant-time password comparison to prevent timing attacks."""
    if not DASHBOARD_PASSWORD:
        return True  # No password set — open access
    return secrets.compare_digest(
        hashlib.sha256(password.encode()).hexdigest(),
        hashlib.sha256(DASHBOARD_PASSWORD.encode()).hexdigest()
    )

def require_auth(f):
    """Decorator that requires dashboard login."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_PASSWORD:
            return f(*args, **kwargs)  # No password configured
        if session.get('authenticated'):
            return f(*args, **kwargs)  # Already logged in
        return redirect('/login')
    return decorated

# ── Helpers ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def now_bkk():
    return datetime.now(BANGKOK_TZ)

# ── Health check ─────────────────────────────────────────────────────────────
@app.route('/')
def health_check():
    return "Bot is running!", 200

# Short URL redirect — visit /d instead of /dashboard
@app.route('/d')
@require_auth
def dashboard_redirect():
    from flask import redirect
    return redirect('/dashboard', code=301)

# ── Login / Logout ────────────────────────────────────────────────────────────
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

    # Inline login page — no external files needed
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Mike Finance — Login</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{height:100%;background:#07090f;font-family:'Outfit',sans-serif;-webkit-font-smoothing:antialiased}
  body{display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#0f1320;border:1px solid rgba(255,255,255,0.06);border-radius:16px;padding:40px 32px;width:min(340px,90vw);text-align:center}
  .logo{font-size:40px;margin-bottom:8px}
  .title{font-family:serif;font-size:26px;color:#dde3ed;letter-spacing:.04em;margin-bottom:4px}
  .title span{color:#f0b429;font-style:italic}
  .sub{font-size:12px;color:#4a566a;letter-spacing:.1em;text-transform:uppercase;margin-bottom:32px}
  input{width:100%;padding:14px 16px;background:#141926;border:1px solid rgba(255,255,255,0.08);border-radius:10px;color:#dde3ed;font-size:16px;outline:none;transition:border-color .2s;margin-bottom:16px;-webkit-appearance:none}
  input:focus{border-color:rgba(240,180,41,0.4)}
  button{width:100%;padding:14px;background:#f0b429;border:none;border-radius:10px;color:#07090f;font-size:15px;font-weight:700;cursor:pointer;letter-spacing:.04em;transition:opacity .2s}
  button:active{opacity:.85}
  .error{color:#f0645a;font-size:13px;margin-bottom:16px;padding:10px;background:rgba(240,100,90,0.1);border-radius:8px}
</style>
</head>
<body>
<div class="card">
  <div class="logo">💰</div>
  <div class="title">Mike <span>Finance</span></div>
  <div class="sub">Personal Dashboard</div>
  {error_html}
  <form method="POST" action="/login">
    <input type="password" name="password" placeholder="Enter password" autofocus autocomplete="current-password">
    <button type="submit">Unlock</button>
  </form>
</div>
</body>
</html>"""

    error_html = f'<div class="error">{error}</div>' if error else ''
    resp = make_response(html.replace('{error_html}', error_html))
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@require_auth
def dashboard():
    return send_file(DASHBOARD_HTML)

# ── API: Account Balances ─────────────────────────────────────────────────────
@app.route('/api/balances')
@require_auth
def api_balances():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, balance FROM accounts ORDER BY id")
    accounts = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(accounts)

# ── API: This-month vs Last-month Summary ────────────────────────────────────
@app.route('/api/summary')
@require_auth
def api_summary():
    conn = get_db()
    c = conn.cursor()
    now = now_bkk()

    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if this_start.month == 1:
        last_start = this_start.replace(year=this_start.year - 1, month=12)
    else:
        last_start = this_start.replace(month=this_start.month - 1)

    def month_totals(start_str, end_str):
        c.execute(
            """SELECT type, SUM(ABS(amount)) as total
               FROM transactions
               WHERE timestamp >= ? AND timestamp < ?
               AND type != 'transfer'
               GROUP BY type""",
            (start_str, end_str)
        )
        r = {row['type']: float(row['total'] or 0) for row in c.fetchall()}
        return r.get('income', 0.0), r.get('expense', 0.0)

    this_inc, this_exp = month_totals(
        this_start.strftime('%Y-%m-%d %H:%M:%S'),
        now.strftime('%Y-%m-%d %H:%M:%S')
    )
    last_inc, last_exp = month_totals(
        last_start.strftime('%Y-%m-%d %H:%M:%S'),
        this_start.strftime('%Y-%m-%d %H:%M:%S')
    )
    conn.close()

    return jsonify({
        'this_month': {
            'income':  this_inc,
            'expense': this_exp,
            'net':     this_inc - this_exp
        },
        'last_month': {
            'income':  last_inc,
            'expense': last_exp,
            'net':     last_inc - last_exp
        }
    })

# ── API: Expense by Category (this month) ────────────────────────────────────
@app.route('/api/categories')
@require_auth
def api_categories():
    conn = get_db()
    c = conn.cursor()
    month_start = now_bkk().replace(day=1, hour=0, minute=0, second=0).strftime('%Y-%m-%d')
    c.execute(
        """SELECT category, SUM(ABS(amount)) as total
           FROM transactions
           WHERE type='expense' AND timestamp >= ?
           GROUP BY category
           ORDER BY total DESC LIMIT 8""",
        (month_start,)
    )
    cats = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(cats)

# ── API: 6-Month Income vs Expense Trend ─────────────────────────────────────
@app.route('/api/monthly')
@require_auth
def api_monthly():
    conn = get_db()
    c = conn.cursor()
    now = now_bkk()
    monthly = []

    for i in range(5, -1, -1):
        month = now.month - i
        year  = now.year
        while month <= 0:
            month += 12
            year  -= 1

        month_start = f"{year}-{month:02d}-01"
        if month == 12:
            month_end = f"{year + 1}-01-01"
        else:
            month_end = f"{year}-{month + 1:02d}-01"

        c.execute(
            """SELECT type, SUM(ABS(amount)) as total
               FROM transactions
               WHERE timestamp >= ? AND timestamp < ?
               AND type != 'transfer'
               GROUP BY type""",
            (month_start, month_end)
        )
        result = {row['type']: float(row['total'] or 0) for row in c.fetchall()}
        monthly.append({
            'month':   calendar.month_abbr[month],
            'income':  result.get('income',  0.0),
            'expense': result.get('expense', 0.0)
        })

    conn.close()
    return jsonify(monthly)

# ── API: Recent Transactions ──────────────────────────────────────────────────
@app.route('/api/transactions')
@require_auth
def api_transactions():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """SELECT amount, description, type, category, account, timestamp
           FROM transactions
           ORDER BY timestamp DESC LIMIT 20"""
    )
    txns = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(txns)

# ── API: Full detail for a specific month ─────────────────────────────────────
@app.route('/api/month/<int:year>/<int:month>')
@require_auth
def api_month_detail(year, month):
    conn = get_db()
    c = conn.cursor()

    month_start = f"{year}-{month:02d}-01"
    if month == 12:
        month_end = f"{year + 1}-01-01"
    else:
        month_end = f"{year}-{month + 1:02d}-01"

    # Totals
    c.execute(
        """SELECT type, SUM(ABS(amount)) as total
           FROM transactions
           WHERE timestamp >= ? AND timestamp < ?
           AND type != 'transfer'
           GROUP BY type""",
        (month_start, month_end)
    )
    totals = {row['type']: float(row['total'] or 0) for row in c.fetchall()}
    income  = totals.get('income',  0.0)
    expense = totals.get('expense', 0.0)

    # Categories
    c.execute(
        """SELECT category, SUM(ABS(amount)) as total
           FROM transactions
           WHERE type='expense' AND timestamp >= ? AND timestamp < ?
           GROUP BY category
           ORDER BY total DESC""",
        (month_start, month_end)
    )
    categories = [dict(r) for r in c.fetchall()]

    # All transactions
    c.execute(
        """SELECT amount, description, type, category, account, timestamp
           FROM transactions
           WHERE timestamp >= ? AND timestamp < ?
           ORDER BY timestamp DESC""",
        (month_start, month_end)
    )
    transactions = [dict(r) for r in c.fetchall()]

    conn.close()
    return jsonify({
        'year':         year,
        'month':        month,
        'income':       income,
        'expense':      expense,
        'net':          income - expense,
        'categories':   categories,
        'transactions': transactions
    })

# ── API: List all months that have data ───────────────────────────────────────
@app.route('/api/months')
@require_auth
def api_months():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """SELECT DISTINCT strftime('%Y', timestamp) as year,
                           strftime('%m', timestamp) as month
           FROM transactions
           ORDER BY year DESC, month DESC"""
    )
    months = [{'year': int(r['year']), 'month': int(r['month'])} for r in c.fetchall()]
    conn.close()
    return jsonify(months)



# ── PWA: Manifest, Icons, Service Worker ─────────────────────────────────────
import base64 as _b64
import json as _json

_ICON_192 = "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"
_ICON_512 = "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"

@app.route('/manifest.json')
def pwa_manifest():
    manifest = {
        "name": "Mike Finance",
        "short_name": "Finance",
        "description": "Personal finance tracker",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#07090f",
        "theme_color": "#07090f",
        "orientation": "portrait",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
        ]
    }
    from flask import Response
    return Response(_json.dumps(manifest), mimetype='application/json')

@app.route('/icon-192.png')
def serve_icon_192():
    from flask import Response
    return Response(_b64.b64decode(_ICON_192), mimetype='image/png',
                    headers={"Cache-Control": "public, max-age=604800"})

@app.route('/icon-512.png')
def serve_icon_512():
    from flask import Response
    return Response(_b64.b64decode(_ICON_512), mimetype='image/png',
                    headers={"Cache-Control": "public, max-age=604800"})

@app.route('/sw.js')
def service_worker():
    from flask import Response
    sw = """
const CACHE='mike-finance-v6';
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/dashboard','/icon-192.png'])));self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',e=>{
  if(e.request.url.includes('/api/')){
    e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
  }else{
    e.respondWith(fetch(e.request).then(res=>{const c=res.clone();caches.open(CACHE).then(ca=>ca.put(e.request,c));return res;}).catch(()=>caches.match(e.request)));
  }
});
"""
    return Response(sw, mimetype='application/javascript',
                    headers={"Service-Worker-Allowed": "/"})


@app.errorhandler(404)
def not_found(e):
    from flask import jsonify
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def server_error(e):
    from flask import jsonify
    return jsonify({"error": "Internal server error"}), 500


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
