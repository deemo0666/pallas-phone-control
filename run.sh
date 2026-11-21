#!/bin/sh
# Run from Pallas's local bash. Pairing state stays in the private guest temp directory.
set -eu
# Signer home from before the PallasBoot rename (plugin 0.6.x).
[ -d /root/.pallas-siboot ] && [ ! -e /root/.pallasboot ] && mv /root/.pallas-siboot /root/.pallasboot || true
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -r /root/workspace/.pallasboot-probe.json ] || { echo 'Enable the Pallas phone-control plugin first.' >&2; exit 1; }
root=/tmp/pallasboot-$(id -u)
mkdir -m 700 -p "$root"
exec 9>"$root/run.lock"
flock -n 9 || { echo 'A probe is already running.' >&2; exit 1; }
(cd "$base" && sha256sum -c runner.sha256)
cp "$base/pallasboot-runner-aarch64" "$root/pallasboot"
chmod 700 "$root/pallasboot"
if [ -d /root/.pallasboot ]; then export PALLAS_SIGN_HOME=/root/.pallasboot; fi
cp "$base/probe.py" "$root/pallas-bonjour"
chmod 700 "$root/pallas-bonjour"
export SIBOOT_PALLAS_BIN="$root"
exec python3 "$base/probe.py" run "${1:-49152}"
