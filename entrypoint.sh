#!/bin/sh

# The database is created automatically by init_db() in main.py
# It lives on the persistent disk at /data/finance.db
# No need to copy a seed file — init_db() handles table creation and account setup

exec python render_main.py
