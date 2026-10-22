#!/bin/bash
set -euo pipefail

for db in identity workflow media bookmark blog agent; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    SELECT 'CREATE DATABASE ${db}'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${db}')\gexec
EOSQL
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname blog -c "CREATE EXTENSION IF NOT EXISTS vector;"
