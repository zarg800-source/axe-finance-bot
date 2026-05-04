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
const CACHE='mike-finance-v3';
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
