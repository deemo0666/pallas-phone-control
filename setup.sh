#!/bin/sh
# Guided setup for the agent: status, start, wait. See SKILL.md.
set -eu
# Signer home from before the PallasBoot rename (plugin 0.6.x).
[ -d /root/.pallas-siboot ] && [ ! -e /root/.pallasboot ] && mv /root/.pallas-siboot /root/.pallasboot || true
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$base/setup.py" "$@"
