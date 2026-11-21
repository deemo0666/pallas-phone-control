#!/bin/sh
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=/tmp/pallas-siboot-$(id -u)
mkdir -m 700 -p "$root"
# Prepare the persistent signing directory before handing a page link to the user.
export PALLAS_SIGN_HOME=/root/.pallas-siboot
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
cfg = json.load(open('/root/workspace/.siboot-probe.json'))
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
flock -n 9 || { echo 'Another siboot job is running.' >&2; exit 1; }
(cd "$base" && sha256sum -c runner.sha256)
# The runner starts only with the developer image mounted; the signer mounts what this downloads.
python3 "$base/ddi.py"
cp "$base/siboot-runner-aarch64" "$root/siboot"
cp "$base/probe.py" "$root/pallas-bonjour"
cp "$base/probe.py" "$root/pallas-open"
chmod 700 "$root/siboot" "$root/pallas-bonjour" "$root/pallas-open"
export SIBOOT_PALLAS_BIN="$root"
exec python3 "$base/probe.py" run "${1:-49152}" "$base/ScreenRunner.ipa"
