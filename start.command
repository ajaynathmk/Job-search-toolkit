#!/bin/sh
# Double-click (macOS) or run (Linux) to start the job-search application.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 app.py "$@"
else
  echo "Python 3.10 or newer is needed: https://www.python.org/downloads/"
fi
