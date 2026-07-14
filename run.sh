#!/usr/bin/env bash
# Launch the DTD Customizer app with the system Python (has PyGObject).
exec /usr/bin/python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/app/dtd-customizer.py" "$@"
