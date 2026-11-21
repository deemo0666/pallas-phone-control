#!/bin/sh
set -eu
# Signer home from before the PallasBoot rename (plugin 0.6.x).
[ -d /root/.pallas-siboot ] && [ ! -e /root/.pallasboot ] && mv /root/.pallas-siboot /root/.pallasboot || true
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=/tmp/pallasboot-$(id -u)
mkdir -m 700 -p "$root"
# Prepare the persistent signing directory before handing a page link to the user.
export PALLAS_SIGN_HOME=/root/.pallasboot
if ! (mkdir -p "$PALLAS_SIGN_HOME" && touch "$PALLAS_SIGN_HOME/.writable") 2>/dev/null; then
    if ! mount -o remount,rw / || ! mkdir -p "$PALLAS_SIGN_HOME" || ! touch "$PALLAS_SIGN_HOME/.writable"; then
        echo '本机签装目录不可写。请在 Pallas 设置 → 权限为当前对话选择「完全权限」，再重试。' >&2
        exit 1
    fi
fi
chmod 700 "$PALLAS_SIGN_HOME"
if [ "${1:-}" = "--open" ]; then
    shift
    # The plugin runs the job: this shell's sandbox ends everything it started when it returns.
    view=$(python3 - "${1:-49152}" "${PALLAS_NEW_LOGIN:-}" <<'EOF'
import json, sys, urllib.request
cfg = json.load(open('/root/workspace/.pallasboot-probe.json'))
body = json.dumps({'action': 'install', 'port': int(sys.argv[1]), 'newLogin': sys.argv[2] == '1'}).encode()
req = urllib.request.Request(f"http://10.0.2.2:{cfg['port']}/", body, {'Authorization': 'Bearer ' + cfg['key']})
reply = json.load(urllib.request.urlopen(req, timeout=20))
if not reply['ok']:
    sys.exit(reply['error']['message'])
print(cfg['view'])
EOF
)
    echo "在 Pallas 内打开签装页面 $view"
    exit 0
fi
exec 9>"$root/run.lock"
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
