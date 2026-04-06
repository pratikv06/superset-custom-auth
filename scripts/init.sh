#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# init.sh — run once to bootstrap both the auth service and Superset.
#
# What it does:
#   1. Waits for Postgres and the auth service to be ready.
#   2. Runs Superset DB migrations and loads default roles/permissions.
#   3. Registers the initial admin user in the FastAPI auth service.
#   4. Provisions the same admin user in Superset's local DB.
# ---------------------------------------------------------------------------

set -euo pipefail

ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@superset.local}"
ADMIN_FIRST="${ADMIN_FIRST:-Admin}"
ADMIN_LAST="${ADMIN_LAST:-User}"

AUTH_SERVICE_URL="${AUTH_SERVICE_URL:-http://auth-service:8000}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

wait_for() {
  local name="$1" url="$2"
  echo "Waiting for $name …"
  until curl -sf "$url" > /dev/null 2>&1; do
    sleep 2
  done
  echo "$name is ready."
}

# ---------------------------------------------------------------------------
# 1. Wait for dependencies
# ---------------------------------------------------------------------------

wait_for "auth-service" "${AUTH_SERVICE_URL}/health"

# ---------------------------------------------------------------------------
# 2. Run Superset DB migrations
# ---------------------------------------------------------------------------

echo "Running Superset DB upgrade …"
superset db upgrade

echo "Initialising Superset roles and permissions …"
superset init

# ---------------------------------------------------------------------------
# 3. Register admin in the FastAPI auth service (idempotent)
# ---------------------------------------------------------------------------

echo "Registering admin in auth service …"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${AUTH_SERVICE_URL}/auth/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"username\": \"${ADMIN_USERNAME}\",
    \"email\": \"${ADMIN_EMAIL}\",
    \"password\": \"${ADMIN_PASSWORD}\",
    \"first_name\": \"${ADMIN_FIRST}\",
    \"last_name\": \"${ADMIN_LAST}\",
    \"is_admin\": true
  }")

if [ "$STATUS" = "201" ]; then
  echo "Admin registered in auth service."
elif [ "$STATUS" = "409" ]; then
  echo "Admin already exists in auth service — skipping."
else
  echo "WARNING: auth service returned HTTP $STATUS for register."
fi

# ---------------------------------------------------------------------------
# 4. Provision the same admin directly in Superset's DB
#    (needed so the first login can resolve roles before the user is synced)
# ---------------------------------------------------------------------------

echo "Provisioning admin in Superset …"
superset fab create-admin \
  --username  "${ADMIN_USERNAME}" \
  --firstname "${ADMIN_FIRST}" \
  --lastname  "${ADMIN_LAST}" \
  --email     "${ADMIN_EMAIL}" \
  --password  "${ADMIN_PASSWORD}" \
  2>&1 | grep -v "already exists" || true

# ---------------------------------------------------------------------------
# 5. Load example dashboards, charts and datasets
# ---------------------------------------------------------------------------

echo "Loading example data (this may take a few minutes) …"
superset load_examples

echo "Initialisation complete."
