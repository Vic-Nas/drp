#!/usr/bin/env bash
# db_reset.sh
# Run this to wipe all app data from the Railway PostgreSQL DB.
# Your .env must have DB_URL set.
# Usage: bash db_reset.sh
#
# This does NOT drop the database or touch Django internal tables
# (django_migrations, django_content_type, etc.).
# After running this, do: python manage.py makemigrations && python manage.py migrate

set -e

# Load DB_URL from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep DB_URL | xargs)
fi

if [ -z "$DB_URL" ]; then
  echo "❌  DB_URL not found in .env"
  exit 1
fi

echo "⚠️  This will DELETE all rows from all application tables."
read -p "Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

echo "🔄  Truncating application tables..."

psql "$DB_URL" <<'SQL'
-- Disable FK checks temporarily
SET session_replication_role = replica;

TRUNCATE TABLE
  core_savedrop,
  core_drop,
  core_userprofile,
  auth_user_groups,
  auth_user_user_permissions,
  auth_user
RESTART IDENTITY CASCADE;

-- Re-enable FK checks
SET session_replication_role = DEFAULT;

SQL

echo "✅  Done. Run: python manage.py migrate"
