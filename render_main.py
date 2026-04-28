import os
import logging
import asyncio
from flask import Flask
from threading import Thread
import time
import requests
from main import main as bot_main

# Flask app for health checks and keeping the bot alive
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

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
        except:
            pass
        time.sleep(600)

if __name__ == '__main__':
    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start keep-alive thread
    keep_alive_thread = Thread(target=keep_alive)
    keep_alive_thread.daemon = True
    keep_alive_thread.start()
    
    # Run the Telegram bot
    bot_main()
