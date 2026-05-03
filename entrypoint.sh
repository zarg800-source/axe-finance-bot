#!/bin/sh

DB_PATH="/data/finance.db"
INITIAL_DB_PATH="/app/finance.db"

# ── First run: copy bundled DB if none exists on persistent disk ──────────────
if [ ! -f "$DB_PATH" ]; then
  echo "No database found on persistent disk. Initialising from bundled snapshot..."
  cp "$INITIAL_DB_PATH" "$DB_PATH"
  echo "Database initialised at $DB_PATH"
else
  echo "Existing database found at $DB_PATH — leaving it untouched."
fi

# ── NOTE ─────────────────────────────────────────────────────────────────────
# The old .force_restore mechanism has been REMOVED intentionally.
# Restoring the bundled DB would erase all live transactions.
# To restore or backup your data, use the Telegram /backup command instead:
#   1. Send /backup to the bot — it sends you the live .db file.
#   2. Keep that file safe. Upload it to GitHub as finance.db if you need
#      to rebuild a service from scratch (along with a fresh deploy).
# ─────────────────────────────────────────────────────────────────────────────

exec python render_main.py
