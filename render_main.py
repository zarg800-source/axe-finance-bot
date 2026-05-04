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
const CACHE='mike-finance-v1';
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
