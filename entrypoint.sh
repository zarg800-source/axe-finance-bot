#!/bin/sh

DB_PATH="/data/finance.db"
INITIAL_DB_PATH="/app/finance.db"

# Check if the database already exists in the persistent volume
if [ ! -f "$DB_PATH" ]; then
  echo "Initializing database in persistent volume..."
  cp "$INITIAL_DB_PATH" "$DB_PATH"
fi

# Execute the main application command
exec python render_main.py
