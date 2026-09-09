#!/usr/bin/env sh
# One-shot migration entrypoint (runs once, then exits).
#
# Mirrors the production pattern of a dedicated migration step (init-container / Job / pipeline
# stage) rather than migrating inside the app's serve-startup — so it runs exactly once, not per
# API replica. In production you would run this as a pre-deploy step with approvals for risky
# changes; here it is a separate compose service the `api` depends_on.
set -eu

echo "[migrate] applying database migrations (alembic upgrade head)..."
alembic upgrade head

# Seed sample data ONLY in local/dev. Never seed production.
if [ "${ENVIRONMENT:-local}" = "local" ] || [ "${ENVIRONMENT:-local}" = "dev" ]; then
  echo "[migrate] seeding sample data (ENVIRONMENT=${ENVIRONMENT:-local})..."
  python -m scripts.seed
else
  echo "[migrate] skipping seed (ENVIRONMENT=${ENVIRONMENT:-local} is not local/dev)"
fi

echo "[migrate] done."
