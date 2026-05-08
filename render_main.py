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
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Mike Finance</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Anton&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;-webkit-font-smoothing:antialiased}
body{font-family:'DM Sans',sans-serif;background:#eef2ff;display:flex;align-items:center;justify-content:center;min-height:100vh}
@media(prefers-color-scheme:dark){
  body{background:#080d1a}
  .w{background:#131e30;border-color:rgba(0,102,255,.12)}
  .t{background:linear-gradient(135deg,#3b82f6,#60a5fa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .s{color:#7a8fad}
  input{background:#1a2640;border-color:rgba(255,255,255,.1);color:#e4ecf7}
  input::placeholder{color:#3d5070}
  input:focus{border-color:rgba(0,130,255,.5);box-shadow:0 0 0 3px rgba(0,82,255,.15)}
  .er{background:rgba(248,113,113,.12);color:#f87171}
}
.w{background:#fff;border:1px solid rgba(0,82,255,.08);border-radius:24px;padding:44px 36px;width:min(360px,92vw);box-shadow:0 20px 60px rgba(0,82,255,.1);display:flex;flex-direction:column;align-items:center}
.lr{width:64px;height:64px;border-radius:18px;background:linear-gradient(135deg,#0052FF,#1A80FF);display:grid;place-items:center;margin-bottom:20px;box-shadow:0 8px 24px rgba(0,82,255,.35)}
.t{font-family:'Anton',sans-serif;font-size:24px;letter-spacing:1px;background:linear-gradient(135deg,#0052FF,#1A80FF);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}
.s{font-size:13px;color:#8899bb;margin-bottom:32px}
.f{width:100%}
.iw{position:relative;margin-bottom:14px}
.li{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#99aac8;pointer-events:none}
input{width:100%;padding:13px 16px 13px 42px;border:1.5px solid rgba(0,82,255,.14);border-radius:12px;background:#f5f7ff;color:#0d1b3e;font-size:15px;font-family:'DM Sans',sans-serif;outline:none;transition:border-color .18s,box-shadow .18s}
input:focus{border-color:rgba(0,82,255,.45);box-shadow:0 0 0 3px rgba(0,82,255,.1)}
input::placeholder{color:#b0bdd4}
.btn{width:100%;padding:14px;border:none;border-radius:12px;background:linear-gradient(135deg,#0052FF,#1A80FF);color:#fff;font-size:15px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;box-shadow:0 6px 20px rgba(0,82,255,.35);transition:opacity .18s}
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
</html>"""
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
