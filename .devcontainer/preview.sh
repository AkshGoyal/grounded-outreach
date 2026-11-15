#!/usr/bin/env bash
# Start the browser workspace without automatic inbox polling.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -z "${OUTREACH_APP_PASSWORD:-}" ]]; then
  read -r -s -p "Choose a workspace login password (at least 12 characters): " OUTREACH_APP_PASSWORD
  echo
fi
if [[ ${#OUTREACH_APP_PASSWORD} -lt 12 ]]; then
  echo "Use a workspace password with at least 12 characters." >&2
  exit 1
fi
export OUTREACH_APP_PASSWORD

preview_bind=127.0.0.1
preview_url=http://127.0.0.1:8000
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  preview_bind=0.0.0.0
  preview_hostname="${CODESPACE_NAME}-8000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  preview_url="https://${preview_hostname}"
  export OUTREACH_ALLOWED_HOSTS="${OUTREACH_ALLOWED_HOSTS:-localhost,127.0.0.1,::1},${preview_hostname}"
fi

echo "Open ${preview_url} in your browser and sign in with the password you chose."
echo "Keep the Codespaces port Private. Automatic inbox polling is disabled."
echo "Research and mail actions still require their normal approval steps. Ctrl-C stops the app."
exec uv run --locked uvicorn outreach.web.app:create_app --factory --host "$preview_bind" --port 8000 --no-access-log
