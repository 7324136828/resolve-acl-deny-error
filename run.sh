#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Check for Python 3.9+
if command -v python3 &> /dev/null; then
    PY_BIN="python3"
elif command -v python &> /dev/null; then
    PY_BIN="python"
else
    echo "Error: Python 3.9 or newer is required, but neither python3 nor python was found."
    exit 1
fi

"$PY_BIN" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1 || {
    echo "Error: Python 3.9 or newer is required."
    exit 1
}

if [ -z "$1" ]; then
    "$PY_BIN" repair_acl.py --gui
else
    "$PY_BIN" repair_acl.py "$@"
fi
