#!/bin/sh
# Bring back a hidden Developer Mode switch; the plugin runs this as a job. See reveal.py.
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=/tmp/pallas-siboot-$(id -u)
mkdir -m 700 -p "$root"
export PALLAS_SIGN_HOME=/root/.pallas-siboot
if ! (mkdir -p "$PALLAS_SIGN_HOME" && touch "$PALLAS_SIGN_HOME/.writable") 2>/dev/null; then
    if ! mount -o remount,rw / || ! mkdir -p "$PALLAS_SIGN_HOME" || ! touch "$PALLAS_SIGN_HOME/.writable"; then
        echo '本机签装目录不可写。请在 Pallas 设置 → 权限为当前对话选择「完全权限」，再重试。' >&2
        exit 1
    fi
fi
chmod 700 "$PALLAS_SIGN_HOME"
exec 9>"$root/run.lock"
flock -n 9 || { echo 'Another siboot job is running.' >&2; exit 1; }
(cd "$base" && sha256sum -c runner.sha256)
cp "$base/siboot-runner-aarch64" "$root/siboot"
cp "$base/probe.py" "$root/pallas-open"
chmod 700 "$root/siboot" "$root/pallas-open"
export SIBOOT_PALLAS_BIN="$root"
exec python3 "$base/reveal.py" "$base/ScreenRunner.ipa"
