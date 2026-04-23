#!/usr/bin/env bash
# ACC Connector — install script (Linux & macOS)
#
# Usage:
#   ./install.sh
#   ./install.sh --extension-id <ID>   # also registers native messaging manifests
#
# Creates a dedicated venv at ~/.local/share/acc-connector/venv, installs the
# package into it, and optionally registers the native messaging host manifests
# for Chrome/Chromium and Firefox. No system-wide pip install, no elevation needed.

set -euo pipefail

EXTENSION_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --extension-id) EXTENSION_ID="$2"; shift 2 ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# ------------------------------------------------------------------ Python check
python3 -c "import sys; assert sys.version_info >= (3, 10), 'x'" 2>/dev/null || {
    echo "Error: Python 3.10 or later is required." >&2
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${HOME}/.local/share/acc-connector/venv"

# ------------------------------------------------------------------ Create / reuse venv
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "Creating venv at ${VENV_DIR}…"
    python3 -m venv "${VENV_DIR}"
fi

# ------------------------------------------------------------------ Install package
echo "Installing acc-connector-host into venv…"
"${VENV_DIR}/bin/pip" install --quiet -e "${SCRIPT_DIR}"
echo "Done."
echo ""

# ------------------------------------------------------------------ Register manifests
if [[ -n "$EXTENSION_ID" ]]; then
    echo "Registering native messaging manifests for extension ID: ${EXTENSION_ID}"
    "${VENV_DIR}/bin/acc-connector-setup" --extension-id "${EXTENSION_ID}"
else
    echo "To register native messaging manifests, load the extension in your"
    echo "browser, copy the Extension ID, then run:"
    echo ""
    echo "  ${VENV_DIR}/bin/acc-connector-setup --extension-id <YOUR_EXTENSION_ID>"
    echo ""
    echo "Or re-run this script:"
    echo "  ./install.sh --extension-id <YOUR_EXTENSION_ID>"
fi
