#!/bin/sh
# Run from Pallas's local bash. Pairing state stays in the private guest temp directory.
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -r /root/workspace/.siboot-probe.json ] || { echo 'Enable the Pallas siboot probe host plugin first.' >&2; exit 1; }
root=/tmp/pallas-siboot-$(id -u)
mkdir -m 700 -p "$root"
exec 9>"$root/run.lock"
flock -n 9 || { echo 'A probe is already running.' >&2; exit 1; }
(cd "$base" && sha256sum -c runner.sha256)
cp "$base/siboot-runner-aarch64" "$root/siboot"
chmod 700 "$root/siboot"
if [ -d /root/.pallas-siboot ]; then export PALLAS_SIGN_HOME=/root/.pallas-siboot; fi
cp "$base/probe.py" "$root/pallas-bonjour"
chmod 700 "$root/pallas-bonjour"
export SIBOOT_PALLAS_BIN="$root"
exec python3 "$base/probe.py" run "${1:-49152}"
