#!/bin/sh
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root="$base/bin"
mkdir -m 700 "$root"
# Prepare the persistent signing directory before handing a page link to the user.
export PALLAS_SIGN_HOME=/root/.pallasboot
if ! touch "$PALLAS_SIGN_HOME/.writable"; then
    echo '本机签装目录不可写。' >&2
    exit 1
fi
chmod 700 "$PALLAS_SIGN_HOME"
exec 9>"$PALLAS_SIGN_HOME/.run.lock"
flock -n 9 || { echo 'Another pallasboot job is running.' >&2; exit 1; }
(cd "$base" && sha256sum -c runner.sha256)
# The runner starts only with the developer image mounted; the signer mounts what this downloads.
python3 "$base/ddi.py"
cp "$base/pallasboot-runner-aarch64" "$root/pallasboot"
cp "$base/probe.py" "$root/pallas-bonjour"
cp "$base/probe.py" "$root/pallas-open"
chmod 700 "$root/pallasboot" "$root/pallas-bonjour" "$root/pallas-open"
export SIBOOT_PALLAS_BIN="$root"
exec python3 "$base/probe.py" run "${1:-49152}" "$base/ScreenRunner.ipa"
