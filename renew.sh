#!/bin/sh
set -eu
# Signer home from before the PallasBoot rename (plugin 0.6.x).
[ -d /root/.pallas-siboot ] && [ ! -e /root/.pallasboot ] && mv /root/.pallas-siboot /root/.pallasboot || true
case ${1:-status} in
    now)
        base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
        if [ -z "${2:-}" ]; then
            port=$(sh "$0" port)
        else
            port=$2
        fi
        export PALLAS_RENEWAL=1
        exec sh "$base/install.sh" "$port"
        ;;
    ddi)
        # A restart unmounts the developer image the runner needs: mount it again.
        base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
        if [ -z "${2:-}" ]; then
            port=$(sh "$0" port)
        else
            port=$2
        fi
        export PALLAS_DDI_ONLY=1
        exec sh "$base/install.sh" "$port"
        ;;
    enable|disable|status|port)
        exec python3 - "${1:-status}" <<'PY'
import json, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path
cfg = json.loads(Path('/root/workspace/.pallasboot-probe.json').read_text())
op = sys.argv[1]
payload = {'action':'renewal', 'op':'status' if op == 'port' else op}
req = urllib.request.Request(f"http://10.0.2.2:{cfg['port']}/", json.dumps(payload).encode(),
                             {'Authorization':'Bearer ' + cfg['key']})
with urllib.request.urlopen(req, timeout=15) as res:
    reply = json.load(res)
if not reply['ok']:
    sys.exit(reply['error']['message'])
state = reply['data']
if not state.get('port'):
    sys.exit('请先完成一次签装。')
if op == 'port':
    print(state['port'])
else:
    print('自动续期' + ('已开启' if state['enabled'] else '已关闭'))
    print('签名到期', datetime.fromtimestamp(state['expires'], timezone.utc).isoformat())
    if state.get('lastError'):
        print(state['lastError'])
PY
        ;;
    *) echo 'renew.sh [status|enable|disable|now|ddi]' >&2; exit 2 ;;
esac
