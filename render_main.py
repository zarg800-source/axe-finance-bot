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
