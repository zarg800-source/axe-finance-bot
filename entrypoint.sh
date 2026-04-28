#!/bin/sh

DB_PATH="/data/finance.db"
INITIAL_DB_PATH="/app/finance.db"
FORCE_RESTORE="/app/.force_restore"

# If the database doesn't exist on persistent disk, copy the bundled one
if [ ! -f "$DB_PATH" ]; then
  echo "No database found on persistent disk. Copying bundled database..."
  cp "$INITIAL_DB_PATH" "$DB_PATH"
  echo "Database initialized at $DB_PATH"
fi

# Force restore: if .force_restore file exists, overwrite the persistent DB
# (Used for one-time recovery — delete .force_restore from repo after recovery)
if [ -f "$FORCE_RESTORE" ]; then
  echo "Force restore flag detected! Overwriting persistent database..."
  cp "$INITIAL_DB_PATH" "$DB_PATH"
  echo "Database force-restored at $DB_PATH"
fi

exec python render_main.py
