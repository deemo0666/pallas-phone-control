#!/bin/sh
# Guided setup for the agent: status, start, wait. See SKILL.md.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$base/setup.py" "$@"
