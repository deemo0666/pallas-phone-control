#!/bin/sh
# Bring back a hidden Developer Mode switch; the plugin runs this as a job. See reveal.py.
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root="$base/bin"
mkdir -m 700 "$root"
export PALLAS_SIGN_HOME=/root/.pallasboot
if ! touch "$PALLAS_SIGN_HOME/.writable"; then
    echo '本机签装目录不可写。' >&2
    exit 1
fi
chmod 700 "$PALLAS_SIGN_HOME"
exec 9>"$PALLAS_SIGN_HOME/.run.lock"
flock -n 9 || { echo 'Another pallasboot job is running.' >&2; exit 1; }
(cd "$base" && sha256sum -c runner.sha256)
cp "$base/pallasboot-runner-aarch64" "$root/pallasboot"
cp "$base/probe.py" "$root/pallas-open"
chmod 700 "$root/pallasboot" "$root/pallas-open"
export SIBOOT_PALLAS_BIN="$root"
exec python3 "$base/reveal.py" "$base/ScreenRunner.ipa"
