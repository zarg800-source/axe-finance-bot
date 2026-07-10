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
# Axe Finance is now a pure web app (no Telegram bot). Backup/Restore live in
# the dashboard's avatar menu (top-right "M" icon):
#   - Backup downloads the live .db file.
#   - Restore uploads a .db file and replaces the live database (with a
#     safety copy of the current DB saved first as finance.db.before_restore).
# ─────────────────────────────────────────────────────────────────────────────

exec python render_main.py
