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

app = Flask(__name__)

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
def dashboard_redirect():
    from flask import redirect
    return redirect('/dashboard', code=301)

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    return send_file(DASHBOARD_HTML)

# ── API: Account Balances ─────────────────────────────────────────────────────
@app.route('/api/balances')
def api_balances():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, balance FROM accounts ORDER BY id")
    accounts = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(accounts)

# ── API: This-month vs Last-month Summary ────────────────────────────────────
@app.route('/api/summary')
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
const CACHE='mike-finance-v4';
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
