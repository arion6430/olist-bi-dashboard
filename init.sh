#!/bin/bash
set -e

echo "=== Running Superset DB migrations ==="
superset db upgrade

echo "=== Creating admin user ==="
superset fab create-admin \
  --username "$ADMIN_USERNAME" \
  --firstname "$ADMIN_FIRSTNAME" \
  --lastname "$ADMIN_LASTNAME" \
  --email "$ADMIN_EMAIL" \
  --password "$ADMIN_PASSWORD" || echo "Admin may already exist, continuing..."

echo "=== Initializing roles and permissions ==="
superset init

echo "=== Superset initialization complete! ==="
