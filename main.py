#!/usr/bin/env python3
"""
Mike's Personal Finance Tracker Bot (v20 async)
Tracks income, expenses, balances across multiple accounts.
Supports natural language logging, photo receipts, recurring subscriptions,
and weekly reports with month-over-month comparison.
"""

import logging
import sqlite3
import os
import re
import base64
from datetime import datetime, timedelta, date
from functools import wraps

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters
)
from dotenv import load_dotenv
import pytz
from openai import OpenAI

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.log'))
    ]
)
logger = logging.getLogger(__name__)

# Config
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
AUTHORIZED_USER_ID = int(os.getenv('AUTHORIZED_USER_ID'))
DATABASE_NAME = os.path.join('/data', 'finance.db')
BANGKOK_TZ = pytz.timezone('Asia/Bangkok')

# OpenAI client for receipt processing
ai_client = OpenAI()

# ─── Categories ───────────────────────────────────────────────────────────────
CATEGORIES = {
    'food': ('Food & Drinks', '🍜'),
    'food & drinks': ('Food & Drinks', '🍜'),
    'restaurant': ('Food & Drinks', '🍜'),
    'street food': ('Food & Drinks', '🍜'),
    'cafe': ('Food & Drinks', '🍜'),
    'lunch': ('Food & Drinks', '🍜'),
    'dinner': ('Food & Drinks', '🍜'),
    'breakfast': ('Food & Drinks', '🍜'),
    'pepsi': ('Food & Drinks', '🍜'),
    'coke': ('Food & Drinks', '🍜'),
    'snack': ('Food & Drinks', '🍜'),
    'coffee': ('Coffee', '☕'),
    'starbucks': ('Coffee', '☕'),
    'cafe amazon': ('Coffee', '☕'),
    'transport': ('Transport', '🚕'),
    'grab': ('Transport', '🚕'),
    'bts': ('Transport', '🚕'),
    'mrt': ('Transport', '🚕'),
    'taxi': ('Transport', '🚕'),
    'motorbike': ('Transport', '🚕'),
    'bolt': ('Transport', '🚕'),
    'bike': ('Transport', '🚕'),
    'groceries': ('Groceries', '🛒'),
    'supermarket': ('Groceries', '🛒'),
    'market': ('Groceries', '🛒'),
    'big c': ('Groceries', '🛒'),
    'lotus': ('Groceries', '🛒'),
    'tops': ('Groceries', '🛒'),
    'makro': ('Groceries', '🛒'),
    '7-eleven': ('Groceries', '🛒'),
    '711': ('Groceries', '🛒'),
    'housing': ('Housing', '🏠'),
    'rent': ('Housing', '🏠'),
    'utilities': ('Housing', '🏠'),
    'electric': ('Housing', '🏠'),
    'water bill': ('Housing', '🏠'),
    'water': ('Housing', '🏠'),
    'internet': ('Housing', '🏠'),
    'wifi': ('Housing', '🏠'),
    'health': ('Health', '💊'),
    'pharmacy': ('Health', '💊'),
    'clinic': ('Health', '💊'),
    'hospital': ('Health', '💊'),
    'medicine': ('Health', '💊'),
    'shopping': ('Shopping', '👗'),
    'clothes': ('Shopping', '👗'),
    'accessories': ('Shopping', '👗'),
    'uniqlo': ('Shopping', '👗'),
    'headphones': ('Shopping', '👗'),
    'sennheiser': ('Shopping', '👗'),
    'entertainment': ('Entertainment', '🎉'),
    'movies': ('Entertainment', '🎉'),
    'movie': ('Entertainment', '🎉'),
    'concert': ('Entertainment', '🎉'),
    'night out': ('Entertainment', '🎉'),
    'bar': ('Entertainment', '🎉'),
    'subscription': ('Subscriptions', '📱'),
    'subscriptions': ('Subscriptions', '📱'),
    'youtube': ('Subscriptions', '📱'),
    'netflix': ('Subscriptions', '📱'),
    'spotify': ('Subscriptions', '📱'),
    'google one': ('Subscriptions', '📱'),
    'travel': ('Travel', '✈️'),
    'hotel': ('Travel', '✈️'),
    'flight': ('Travel', '✈️'),
    'trip': ('Travel', '✈️'),
    'school': ('School', '🎓'),
    'tuition': ('School', '🎓'),
    'books': ('School', '🎓'),
    'language': ('School', '🎓'),
    'italian': ('School', '🎓'),
    'class': ('School', '🎓'),
    'salary': ('Income', '💵'),
    'freelance': ('Income', '💵'),
    'gallery': ('Income', '💵'),
    'artwork': ('Income', '💵'),
    'sold': ('Income', '💵'),
    'commission': ('Income', '💵'),
    'transfer': ('Income', '💵'),
}

CATEGORY_LIST = [
    ('🍜', 'Food & Drinks'),
    ('☕', 'Coffee'),
    ('🚕', 'Transport'),
    ('🛒', 'Groceries'),
    ('🏠', 'Housing'),
    ('💊', 'Health'),
    ('👗', 'Shopping'),
    ('🎉', 'Entertainment'),
    ('📱', 'Subscriptions'),
    ('✈️', 'Travel'),
    ('🎓', 'School'),
    ('🧾', 'Other'),
]

ACCOUNT_KEYWORDS = {
    'bank': 'Bangkok Bank',
    'bangkok bank': 'Bangkok Bank',
    'bbl': 'Bangkok Bank',
    'true money': 'True Money Wallet',
    'truemoney': 'True Money Wallet',
    'true wallet': 'True Money Wallet',
    'mrt': 'MRT EMV Visa',
    'emv': 'MRT EMV Visa',
    'visa': 'MRT EMV Visa',
    'rabbit': 'Rabbit Card',
    'rabbit card': 'Rabbit Card',
    'cash': 'Cash',
}


# ─── Database ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        balance REAL NOT NULL DEFAULT 0.0,
        UNIQUE(user_id, name)
    );
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        emoji TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        type TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'Other',
        account TEXT NOT NULL DEFAULT 'Cash',
        timestamp DATETIME DEFAULT (datetime('now', '+7 hours'))
    );
    CREATE TABLE IF NOT EXISTS recurring_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL DEFAULT 'Subscriptions',
        account TEXT NOT NULL DEFAULT 'Cash',
        next_due_date DATE NOT NULL,
        frequency TEXT NOT NULL DEFAULT 'monthly'
    );
    """)
    for emoji, name in CATEGORY_LIST:
        c.execute("INSERT OR IGNORE INTO categories (name, emoji) VALUES (?, ?)", (name, emoji))
    uid = AUTHORIZED_USER_ID
    for user_id, name, balance in [
        (uid, 'Bangkok Bank', 2137.24),
        (uid, 'True Money Wallet', 6.00),
        (uid, 'MRT EMV Visa', 133.79),
        (uid, 'Rabbit Card', 0.00),
        (uid, 'Cash', 0.00),
    ]:
        c.execute("INSERT OR IGNORE INTO accounts (user_id, name, balance) VALUES (?, ?, ?)", (user_id, name, balance))
    for user_id, name, amount, cat, account, due, freq in [
        (uid, 'YouTube Premium (10GB)', 204.67, 'Subscriptions', 'Bangkok Bank', '2026-04-29', 'monthly'),
        (uid, 'Google One 30GB', 30.00, 'Subscriptions', 'Bangkok Bank', '2026-04-25', 'monthly'),
    ]:
        c.execute("SELECT id FROM recurring_subscriptions WHERE user_id = ? AND name = ?", (user_id, name))
        if not c.fetchone():
            c.execute(
                "INSERT INTO recurring_subscriptions (user_id, name, amount, category, account, next_due_date, frequency) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, name, amount, cat, account, due, freq)
            )
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Auth decorator ───────────────────────────────────────────────────────────
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != AUTHORIZED_USER_ID:
            logger.warning(f"Unauthorized access attempt by {user_id}")
            await update.message.reply_text("Sorry, this bot is private. 🔒")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# ─── Helpers ──────────────────────────────────────────────────────────────────
def detect_category(text):
    text_lower = text.lower()
    sorted_keywords = sorted(CATEGORIES.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if keyword in text_lower:
            return CATEGORIES[keyword]
    return ('Other', '🧾')


def detect_account(text):
    text_lower = text.lower()
    sorted_keywords = sorted(ACCOUNT_KEYWORDS.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if keyword in text_lower:
            return ACCOUNT_KEYWORDS[keyword]
    return 'Cash'


# ─── Commands ─────────────────────────────────────────────────────────────────
@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hey Mike! 👋 I'm your personal finance tracker.\n\n"
        "Just text me things like:\n"
        "• \"spent ฿150 BTS\"\n"
        "• \"received ฿5,000 from gallery\"\n"
        "• \"paid ฿200 coffee starbucks bank\"\n\n"
        "Or send me a photo of a receipt! 📸\n\n"
        "Use /help to see all commands."
    )


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Commands:*\n\n"
        "/start — Welcome message\n"
        "/help — This help menu\n"
        "/balance — Show all account balances\n"
        "/report — Get financial summary\n"
        "/categories — List categories\n"
        "/subscriptions — Show recurring subscriptions\n"
        "/addsubscription — Add a subscription\n"
        "/deletesubscription — Remove a subscription\n"
        "/transfer — Transfer between accounts\n"
        "/delete — Delete last transaction\n"
        "/history — Recent transactions\n"
        "/updatebalance — Update an account balance\n\n"
        "💬 *Natural language:*\n"
        "\"spent ฿150 BTS\" — logs expense\n"
        "\"received ฿5000 salary bank\" — logs income\n"
        "\"paid ฿45 coffee\" — logs expense\n\n"
        "📸 Send a receipt photo to log it!\n\n"
        "💡 Add account name at the end: bank, true money, mrt, rabbit, cash",
        parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, balance FROM accounts WHERE user_id = ? ORDER BY id", (AUTHORIZED_USER_ID,))
    accounts = c.fetchall()
    conn.close()

    total = sum(a['balance'] for a in accounts)
    emojis = {'Bangkok Bank': '🏦', 'True Money Wallet': '📱', 'MRT EMV Visa': '🚇', 'Rabbit Card': '🐇', 'Cash': '💵'}
    lines = ["💰 *Account Balances:*\n"]
    for a in accounts:
        e = emojis.get(a['name'], '💰')
        lines.append(f"{e} {a['name']}: ฿{a['balance']:,.2f}")
    lines.append(f"\n🏧 *Total: ฿{total:,.2f}*")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📂 *Expense Categories:*\n"]
    for emoji, name in CATEGORY_LIST:
        lines.append(f"{emoji} {name}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10",
        (AUTHORIZED_USER_ID,)
    )
    txns = c.fetchall()
    conn.close()

    if not txns:
        await update.message.reply_text("No transactions yet.")
        return

    lines = ["📜 *Recent Transactions:*\n"]
    for t in txns:
        emoji = "💵" if t['type'] == 'income' else "💸"
        lines.append(
            f"{emoji} ฿{abs(t['amount']):,.2f} — {t['description']}\n"
            f"   📂 {t['category']} | 🏦 {t['account']} | {t['timestamp'][:16]}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, amount, account, description FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (AUTHORIZED_USER_ID,)
    )
    txn = c.fetchone()
    if not txn:
        await update.message.reply_text("No transactions to delete.")
        conn.close()
        return

    c.execute("DELETE FROM transactions WHERE id = ?", (txn['id'],))
    c.execute(
        "UPDATE accounts SET balance = balance - ? WHERE user_id = ? AND name = ?",
        (txn['amount'], AUTHORIZED_USER_ID, txn['account'])
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"🗑 Deleted last transaction (฿{abs(txn['amount']):,.2f} from {txn['account']})."
    )


@restricted
async def cmd_update_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: /updatebalance <account> <amount>\n"
            "Example: /updatebalance rabbit 250"
        )
        return
    account_name = detect_account(args[0])
    try:
        new_balance = float(args[1].replace(',', ''))
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE accounts SET balance = ? WHERE user_id = ? AND name = ?",
        (new_balance, AUTHORIZED_USER_ID, account_name)
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ {account_name} balance updated to ฿{new_balance:,.2f}")


@restricted
async def cmd_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT name, amount, account, next_due_date FROM recurring_subscriptions WHERE user_id = ? ORDER BY next_due_date",
        (AUTHORIZED_USER_ID,)
    )
    subs = c.fetchall()
    conn.close()

    if not subs:
        await update.message.reply_text("No recurring subscriptions.")
        return

    lines = ["🔄 *Recurring Subscriptions:*\n"]
    for s in subs:
        lines.append(
            f"📱 {s['name']}: ฿{s['amount']:,.2f}/month\n"
            f"  Account: {s['account']} | Next: {s['next_due_date']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_add_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: /addsubscription <name> <amount> <account> [next_due_date]\n"
            "Example: /addsubscription Netflix 399 bank 2026-05-01"
        )
        return
    name = args[0]
    try:
        amount = float(args[1].replace(',', ''))
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return
    account = detect_account(args[2])
    next_due = args[3] if len(args) > 3 else str(date.today() + timedelta(days=30))

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO recurring_subscriptions (user_id, name, amount, category, account, next_due_date, frequency) "
        "VALUES (?, ?, ?, 'Subscriptions', ?, ?, 'monthly')",
        (AUTHORIZED_USER_ID, name, amount, account, next_due)
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Subscription '{name}' added: ฿{amount:,.2f}/month from {account}, next due {next_due}")


@restricted
async def cmd_delete_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /deletesubscription <name>")
        return
    name = " ".join(args)
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "DELETE FROM recurring_subscriptions WHERE user_id = ? AND name LIKE ?",
        (AUTHORIZED_USER_ID, f"%{name}%")
    )
    if c.rowcount > 0:
        conn.commit()
        await update.message.reply_text(f"🗑 Subscription matching '{name}' deleted.")
    else:
        await update.message.reply_text(f"No subscription found matching '{name}'.")
    conn.close()


@restricted
async def cmd_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: /transfer <amount> <from> <to>\n"
            "Accounts: bank, truemoney, mrt, rabbit, cash\n"
            "Example: /transfer 45 cash bank\n"
            "Example: /transfer 200 bank truemoney"
        )
        return
    try:
        amount = float(args[0].replace(',', '').replace('฿', ''))
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return
    if amount <= 0:
        await update.message.reply_text("Amount must be greater than zero.")
        return

    from_account = detect_account(" ".join(args[1:-1]) if len(args) > 3 else args[1])
    to_account = detect_account(args[-1])
    if from_account == to_account:
        await update.message.reply_text("From and To accounts can't be the same.")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, from_account))
    if not c.fetchone():
        await update.message.reply_text(f"Account '{from_account}' not found.")
        conn.close()
        return
    c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, to_account))
    if not c.fetchone():
        await update.message.reply_text(f"Account '{to_account}' not found.")
        conn.close()
        return

    c.execute("UPDATE accounts SET balance = balance - ? WHERE user_id = ? AND name = ?", (amount, AUTHORIZED_USER_ID, from_account))
    c.execute("UPDATE accounts SET balance = balance + ? WHERE user_id = ? AND name = ?", (amount, AUTHORIZED_USER_ID, to_account))
    c.execute(
        "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, 'expense', 'Other', ?)",
        (AUTHORIZED_USER_ID, -amount, f"Transfer to {to_account}", from_account)
    )
    c.execute(
        "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, 'income', 'Other', ?)",
        (AUTHORIZED_USER_ID, amount, f"Transfer from {from_account}", to_account)
    )
    conn.commit()
    c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, from_account))
    new_from = c.fetchone()['balance']
    c.execute("SELECT balance FROM accounts WHERE user_id = ? AND name = ?", (AUTHORIZED_USER_ID, to_account))
    new_to = c.fetchone()['balance']
    conn.close()
    await update.message.reply_text(
        f"🔄 Transfer complete!\n\n"
        f"💸 {from_account}: -฿{amount:,.2f} → ฿{new_from:,.2f}\n"
        f"💵 {to_account}: +฿{amount:,.2f} → ฿{new_to:,.2f}"
    )


# ─── Natural language handler ────────────────────────────────────────────────
@restricted
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    text_lower = text.lower().strip()

    is_expense = False
    is_income = False
    expense_words = ['spent', 'paid', 'buy', 'bought', 'pay', 'cost', 'expense']
    income_words = ['received', 'got', 'earned', 'income', 'sold', 'salary', 'freelance', 'commission', 'transfer in']

    for w in expense_words:
        if w in text_lower:
            is_expense = True
            break
    for w in income_words:
        if w in text_lower:
            is_income = True
            break

    if not is_expense and not is_income:
        await update.message.reply_text(
            "I couldn't tell if that's income or expense. 🤔\n"
            "Try: \"spent ฿150 BTS\" or \"received ฿5000 salary\""
        )
        return

    amount_match = re.search(r'[฿฿B]?\s*([\d,]+(?:\.\d{1,2})?)', text)
    if not amount_match:
        await update.message.reply_text("I couldn't find an amount. Please include something like ฿150 or 150.")
        return

    amount = float(amount_match.group(1).replace(',', ''))
    if amount <= 0:
        await update.message.reply_text("Amount must be greater than zero.")
        return

    cat_name, cat_emoji = detect_category(text)
    account_name = detect_account(text)

    desc = text
    desc = re.sub(r'[฿฿B]?\s*[\d,]+(?:\.\d{1,2})?', '', desc, count=1)
    for w in expense_words + income_words:
        desc = re.sub(r'\b' + w + r'\b', '', desc, flags=re.IGNORECASE)
    for kw in ACCOUNT_KEYWORDS:
        desc = re.sub(r'\b' + re.escape(kw) + r'\b', '', desc, flags=re.IGNORECASE)
    desc = re.sub(r'\s+', ' ', desc).strip(' .,;:-')
    if not desc:
        desc = cat_name

    txn_type = 'income' if is_income else 'expense'
    db_amount = amount if is_income else -amount

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, ?, ?, ?)",
        (AUTHORIZED_USER_ID, db_amount, desc, txn_type, cat_name, account_name)
    )
    c.execute(
        "UPDATE accounts SET balance = balance + ? WHERE user_id = ? AND name = ?",
        (db_amount, AUTHORIZED_USER_ID, account_name)
    )
    conn.commit()
    conn.close()

    if is_income:
        await update.message.reply_text(
            f"💵 Logged income: +฿{amount:,.2f}\n📝 {desc}\n🏦 {account_name}\n📂 {cat_emoji} {cat_name}"
        )
    else:
        await update.message.reply_text(
            f"💸 Logged expense: -฿{amount:,.2f}\n📝 {desc}\n🏦 {account_name}\n📂 {cat_emoji} {cat_name}"
        )


# ─── Photo receipt handling ───────────────────────────────────────────────────
@restricted
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or ""
    caption_lower = caption.lower().strip()

    await update.message.reply_text("📸 Processing your receipt... give me a moment.")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        b64_image = base64.b64encode(photo_bytes).decode('utf-8')

        response = ai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a receipt/bank transfer slip parser. Extract information from the image.\n"
                        "Look for:\n"
                        "- The total amount or transfer amount\n"
                        "- The 'Note' or 'Memo' field if present (this is the user's description of what they bought/paid for)\n"
                        "- The bank or source (e.g., Bangkok Bank, KBank, SCB, True Money, etc.)\n"
                        "- Whether this is money going OUT (payment/transfer/expense) or money coming IN (received/deposit)\n\n"
                        "Respond in this exact format:\n"
                        "AMOUNT: <number only, no currency symbol>\n"
                        "NOTE: <the Note/Memo field from the receipt, or a short description of the transaction>\n"
                        "BANK: <bank name if visible, otherwise UNKNOWN>\n"
                        "DIRECTION: <OUT or IN>\n"
                        "CATEGORY: <one of: Food & Drinks, Coffee, Transport, Groceries, Housing, Health, Shopping, Entertainment, Subscriptions, Travel, School, Other>\n"
                        "If you cannot read the receipt, respond with AMOUNT: 0"
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Please extract the amount, note, bank, and direction from this receipt/slip.{' User caption: ' + caption if caption else ''}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                    ]
                }
            ],
            max_tokens=300
        )

        result = response.choices[0].message.content
        logger.info(f"AI receipt result: {result}")

        amount_match = re.search(r'AMOUNT:\s*([\d,]+(?:\.\d{1,2})?)', result)
        note_match = re.search(r'NOTE:\s*(.+)', result)
        bank_match = re.search(r'BANK:\s*(.+)', result)
        direction_match = re.search(r'DIRECTION:\s*(OUT|IN)', result, re.IGNORECASE)
        cat_match = re.search(r'CATEGORY:\s*(.+)', result)

        if not amount_match or float(amount_match.group(1).replace(',', '')) == 0:
            await update.message.reply_text(
                "😅 I couldn't read the receipt clearly. Please log it manually:\n"
                "Example: \"spent ฿150 food\""
            )
            return

        amount = float(amount_match.group(1).replace(',', ''))
        desc = note_match.group(1).strip() if note_match else "Receipt scan"
        cat_name = cat_match.group(1).strip() if cat_match else "Other"
        direction = direction_match.group(1).upper() if direction_match else "OUT"

        # Detect account: caption > AI bank detection > default
        account_name = 'Cash'
        if caption_lower:
            account_name = detect_account(caption_lower)
        if account_name == 'Cash' and bank_match:
            bank_text = bank_match.group(1).strip().lower()
            if bank_text != 'unknown':
                if 'bangkok' in bank_text or 'bbl' in bank_text:
                    account_name = 'Bangkok Bank'
                elif 'true' in bank_text:
                    account_name = 'True Money Wallet'
                elif 'rabbit' in bank_text:
                    account_name = 'Rabbit Card'
                elif 'mrt' in bank_text or 'emv' in bank_text:
                    account_name = 'MRT EMV Visa'

        # Better category from note
        if desc and desc != "Receipt scan":
            detected_cat, _ = detect_category(desc)
            if detected_cat != 'Other':
                cat_name = detected_cat

        valid_cats = [name for _, name in CATEGORY_LIST]
        if cat_name not in valid_cats:
            cat_name = "Other"

        cat_emoji = "🧾"
        for e, n in CATEGORY_LIST:
            if n == cat_name:
                cat_emoji = e
                break

        # Direction from caption override
        is_income = direction == "IN"
        if caption_lower:
            for w in ['received', 'got', 'earned', 'income', 'money in', 'salary']:
                if w in caption_lower:
                    is_income = True
                    break
            for w in ['spent', 'paid', 'money out', 'buy', 'bought']:
                if w in caption_lower:
                    is_income = False
                    break

        db_amount = amount if is_income else -amount
        txn_type = 'income' if is_income else 'expense'

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, ?, ?, ?)",
            (AUTHORIZED_USER_ID, db_amount, desc, txn_type, cat_name, account_name)
        )
        c.execute(
            "UPDATE accounts SET balance = balance + ? WHERE user_id = ? AND name = ?",
            (db_amount, AUTHORIZED_USER_ID, account_name)
        )
        conn.commit()
        conn.close()

        sign = "💵 +" if is_income else "💸 -"
        await update.message.reply_text(
            f"📸 Receipt logged!\n"
            f"{sign}฿{amount:,.2f}\n"
            f"📝 {desc}\n"
            f"📂 {cat_emoji} {cat_name}\n"
            f"🏦 {account_name}\n\n"
            f"Wrong? Use /delete to remove it."
        )

    except Exception as e:
        logger.error(f"Error processing receipt: {e}")
        await update.message.reply_text(
            "😅 Something went wrong processing the receipt. Please log it manually:\n"
            "Example: \"spent ฿150 food\""
        )


# ─── Reports ──────────────────────────────────────────────────────────────────
def generate_report(user_id):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(BANGKOK_TZ)
    today = now.date()

    c.execute("SELECT name, balance FROM accounts WHERE user_id = ? ORDER BY id", (user_id,))
    accounts = c.fetchall()
    total_balance = sum(a['balance'] for a in accounts)

    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    this_month_start = today.replace(day=1)
    last_month_end = this_month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    def get_period_stats(start, end):
        c.execute(
            "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE 0 END), 0) as income, "
            "COALESCE(SUM(CASE WHEN type='expense' THEN ABS(amount) ELSE 0 END), 0) as expense "
            "FROM transactions WHERE user_id = ? AND date(timestamp) >= ? AND date(timestamp) <= ?",
            (user_id, start, end)
        )
        return c.fetchone()

    def get_category_breakdown(start, end):
        c.execute(
            "SELECT category, SUM(ABS(amount)) as total "
            "FROM transactions WHERE user_id = ? AND type = 'expense' "
            "AND date(timestamp) >= ? AND date(timestamp) <= ? "
            "GROUP BY category ORDER BY total DESC",
            (user_id, start, end)
        )
        return c.fetchall()

    this_week = get_period_stats(this_week_start, today)
    last_week = get_period_stats(last_week_start, this_week_start - timedelta(days=1))
    this_month = get_period_stats(this_month_start, today)
    last_month = get_period_stats(last_month_start, last_month_end)
    this_week_cats = get_category_breakdown(this_week_start, today)
    conn.close()

    report = f"📊 *Weekly Financial Report*\n"
    report += f"📅 {now.strftime('%A, %B %d, %Y')}\n\n"
    report += "💰 *Account Balances:*\n"
    for acc in accounts:
        emoji = {'Bangkok Bank': '🏦', 'True Money Wallet': '📱', 'MRT EMV Visa': '🚇', 'Rabbit Card': '🐇'}.get(acc['name'], '💵')
        report += f"  {emoji} {acc['name']}: ฿{acc['balance']:,.2f}\n"
    report += f"  *Total: ฿{total_balance:,.2f}*\n\n"

    report += "📅 *This Week:*\n"
    report += f"  💵 Income: ฿{this_week['income']:,.2f}\n"
    report += f"  💸 Expenses: ฿{this_week['expense']:,.2f}\n"
    net_week = this_week['income'] - this_week['expense']
    report += f"  📊 Net: ฿{net_week:,.2f}\n\n"

    report += "🔄 *vs Last Week:*\n"
    report += f"  💵 Income: ฿{last_week['income']:,.2f}\n"
    report += f"  💸 Expenses: ฿{last_week['expense']:,.2f}\n"
    if last_week['expense'] > 0:
        pct = ((this_week['expense'] - last_week['expense']) / last_week['expense']) * 100
        d = "📈" if pct > 0 else "📉"
        report += f"  {d} Spending {abs(pct):.0f}% {'more' if pct > 0 else 'less'} than last week\n"
    report += "\n"

    report += "📅 *This Month:*\n"
    report += f"  💵 Income: ฿{this_month['income']:,.2f}\n"
    report += f"  💸 Expenses: ฿{this_month['expense']:,.2f}\n"
    net_month = this_month['income'] - this_month['expense']
    report += f"  📊 Net: ฿{net_month:,.2f}\n\n"

    report += "🔄 *vs Last Month:*\n"
    report += f"  💵 Income: ฿{last_month['income']:,.2f}\n"
    report += f"  💸 Expenses: ฿{last_month['expense']:,.2f}\n"
    if last_month['expense'] > 0:
        pct = ((this_month['expense'] - last_month['expense']) / last_month['expense']) * 100
        d = "📈" if pct > 0 else "📉"
        report += f"  {d} Spending {abs(pct):.0f}% {'more' if pct > 0 else 'less'} than last month\n"
    report += "\n"

    if this_week_cats:
        report += "📂 *This Week by Category:*\n"
        for cat in this_week_cats:
            cat_emoji = "🧾"
            for e, n in CATEGORY_LIST:
                if n == cat['category']:
                    cat_emoji = e
                    break
            report += f"  {cat_emoji} {cat['category']}: ฿{cat['total']:,.2f}\n"

    return report


@restricted
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    report = generate_report(AUTHORIZED_USER_ID)
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)


async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        report = generate_report(AUTHORIZED_USER_ID)
        await context.bot.send_message(
            chat_id=AUTHORIZED_USER_ID,
            text=report,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("Weekly report sent successfully.")
    except Exception as e:
        logger.error(f"Error sending weekly report: {e}")


# ─── Recurring subscription checker ──────────────────────────────────────────
async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    today = datetime.now(BANGKOK_TZ).date()

    c.execute(
        "SELECT id, user_id, name, amount, category, account, next_due_date, frequency "
        "FROM recurring_subscriptions WHERE next_due_date <= ?",
        (today,)
    )
    due_subs = c.fetchall()

    for sub in due_subs:
        amount = sub['amount']
        c.execute(
            "INSERT INTO transactions (user_id, amount, description, type, category, account) VALUES (?, ?, ?, 'expense', ?, ?)",
            (sub['user_id'], -amount, f"🔄 {sub['name']} (auto)", sub['category'], sub['account'])
        )
        c.execute(
            "UPDATE accounts SET balance = balance - ? WHERE user_id = ? AND name = ?",
            (amount, sub['user_id'], sub['account'])
        )

        due_date = datetime.strptime(sub['next_due_date'], "%Y-%m-%d").date()
        if sub['frequency'] == 'monthly':
            if due_date.month == 12:
                next_due = due_date.replace(year=due_date.year + 1, month=1)
            else:
                try:
                    next_due = due_date.replace(month=due_date.month + 1)
                except ValueError:
                    next_due = (due_date.replace(day=1) + timedelta(days=32)).replace(day=due_date.day)
        elif sub['frequency'] == 'weekly':
            next_due = due_date + timedelta(weeks=1)
        elif sub['frequency'] == 'yearly':
            next_due = due_date.replace(year=due_date.year + 1)
        else:
            next_due = due_date + timedelta(days=30)

        c.execute("UPDATE recurring_subscriptions SET next_due_date = ? WHERE id = ?", (next_due, sub['id']))

        try:
            await context.bot.send_message(
                chat_id=sub['user_id'],
                text=f"🔄 Auto-logged: {sub['name']}\n💸 -฿{amount:,.2f} from {sub['account']}"
            )
        except Exception as e:
            logger.error(f"Error notifying about subscription: {e}")

    conn.commit()
    conn.close()


# ─── Error handler ────────────────────────────────────────────────────────────
async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    init_db()
    logger.info("Database initialized.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # Error handler
    app.add_error_handler(error_handler)

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("updatebalance", cmd_update_balance))
    app.add_handler(CommandHandler("subscriptions", cmd_subscriptions))
    app.add_handler(CommandHandler("addsubscription", cmd_add_subscription))
    app.add_handler(CommandHandler("deletesubscription", cmd_delete_subscription))
    app.add_handler(CommandHandler("transfer", cmd_transfer))

    # Photo handler
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Text handler (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduled jobs using v20 JobQueue
    job_queue = app.job_queue

    # Daily subscription check at 8 AM Bangkok time
    target_time_subs = datetime.now(BANGKOK_TZ).replace(hour=8, minute=0, second=0, microsecond=0).timetz()
    job_queue.run_daily(check_subscriptions, time=target_time_subs, name='check_subs')

    # Weekly report every Monday at 9 AM Bangkok time
    target_time_report = datetime.now(BANGKOK_TZ).replace(hour=9, minute=0, second=0, microsecond=0).timetz()
    job_queue.run_daily(send_weekly_report, time=target_time_report, days=(0,), name='weekly_report')  # 0 = Monday

    logger.info("Scheduler configured. Weekly reports: Monday 9AM, Sub checks: daily 8AM (Bangkok time)")

    # Run with polling
    logger.info("Starting bot polling...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == '__main__':
    main()
