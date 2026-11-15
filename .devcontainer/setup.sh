#!/usr/bin/env bash
# Runs once when the Codespace is created.
set -euo pipefail

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "Installing the project..."
uv sync --locked --extra dev

echo "Running the tests..."
uv run pytest -q

cat <<'MESSAGE'

  Ready.

  1. Run: bash .devcontainer/preview.sh
     Choose a workspace password, then open port 8000 from the Ports tab.
     Keep the port Private and use Open in Browser.

  2. To enable research, add Codespaces secrets named
     OUTREACH_OPENROUTER_API_KEY and OUTREACH_PARALLEL_API_KEY.
     Secrets configured in Codex Cloud do not automatically transfer here.
     Stop and restart the Codespace after adding its secrets.

  3. See docs/WORKSPACE_GUIDE.md for the approval workflow and mail setup.
     The preview does not automatically check inboxes or make paid AI calls.

MESSAGE
