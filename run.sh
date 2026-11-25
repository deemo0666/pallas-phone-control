#!/bin/sh
# Compatibility entry for checking pairing from the local shell.
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$base/setup.sh" status
