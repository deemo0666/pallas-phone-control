#!/usr/bin/env python3
"""Guided setup for the agent (SKILL.md). Every command ends with `next: <step>`.

  status            check each step; already-done steps are skipped
  start [--port N] [--new-login]
                    find the device port, start pairing and install in the background, print the page link
  wait [SECONDS]    follow a running job until its stage changes (default 45 s), then print status
  reveal [--new-login]
                    Developer Mode is missing from Settings: start the job that brings the switch back
  ddi               mount the developer image the runner needs (a restart unmounts it)
  trusted           the person has trusted the runner's developer in Settings: go on to verify
  reset             remove the pairing, Apple sign-in and their keychain copy, to set up from scratch
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parent
CONFIG = Path('/root/workspace/.pallasboot-probe.json')
HOME = Path('/root/.pallasboot')
RUN = Path(f'/tmp/pallasboot-{os.getuid()}')
# Written by the install job the plugin runs (index.cjs runInstall).
LOG = Path('/root/workspace/.pallasboot-install.log')
WINDOW = 48 * 3600
BRIDGE = '10.0.2.2'
DONE = '手机操控已安装并已连接 Pallas'
# The stage a reveal job ends on (reveal.py REVEALED).
REVEALED = '请打开开发者模式'
REVEAL_NEXT = {'identify': 'identify_device', 'install': 'install_in_safari', 'enable': 'turn_on_developer_mode'}
IDLE_STAGES = {'waiting'}


def say(key, value):
    print(f'{key}: {value}', flush=True)


def bridge(timeout=20, **args):
    # Right after Pallas comes back to the front the plugin may still be taking its listener
    # back (listen-again.cjs): retry a refusal for a few seconds, reading the port each time.
    for attempt in range(8):
        cfg = json.loads(CONFIG.read_text())
        req = urllib.request.Request(f"http://{BRIDGE}:{cfg['port']}/", json.dumps(args).encode(),
                                     {'Authorization': 'Bearer ' + cfg['key']})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                reply = json.load(res)
            break
        except urllib.error.URLError as e:
            if not isinstance(e.reason, ConnectionRefusedError) or attempt == 7:
                raise
        time.sleep(1)
    if not reply['ok']:
        raise RuntimeError(reply['error']['message'])
    return reply.get('data') or {}


def running():
    # The plugin runs the job outside this command's sandbox, whose /tmp is private.
    try:
        if bridge(action='state').get('installing'):
            return True
    except (OSError, RuntimeError, ValueError):
        pass
    lock = RUN / 'run.lock'
    if not lock.exists():
        return False
    with open(lock, 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def log_lines():
    try:
        lines = LOG.read_text(errors='replace').splitlines()
    except OSError:
        return []
    return [s.strip() for s in lines if s.strip() and s.strip() != '配对验证仍在运行'][-8:]


def sign_home():
    if not HOME.is_dir():
        return 'missing'
    try:
        probe = HOME / '.writable'
        probe.touch()
        return 'writable'
    except OSError:
        return 'readonly'


def saved():
    def any_file(pattern):
        try:
            return any(p.is_file() for p in HOME.glob(pattern))
        except OSError:
            return False
    receipt = None
    try:
        receipt = json.loads((HOME / 'runner-receipt.json').read_text()).get('expires')
    except (OSError, ValueError):
        pass
    return {'pairing': any_file('*pair*'), 'session': any_file('isideload/**/developer_session.json'),
            'receipt': receipt}


def until(expires):
    if not expires:
        return 'none'
    left = int(expires - time.time())
    when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))
    if left <= 0:
        return f'{when}（已过期）'
    return f'{when}（剩 {left // 86400} 天 {left % 86400 // 3600} 小时）'


def failure_of(stage, lines):
    """The reason of the last job that ended without installing, or None."""
    stopped = next((s for s in reversed(lines) if s.startswith(('Stopped:', '签装失败', '本机签装目录不可写'))), None)
    if stage in (DONE, REVEALED):
        return None
    if stage.startswith(('签装失败', '签装中断')) or stage == '验证未完成':
        return stage if not stopped or stopped in stage else stage + ' / ' + stopped
    if stage in IDLE_STAGES and not stopped:
        return None
    return stopped or f'任务在「{stage}」时结束'


def classify(reason):
    if not reason:
        return 'failed'
    if '不可写' in reason:
        return 'full_access'
    if 'Expected Pallas' in reason:
        return 'host_unsupported'
    return 'failed'


def status(detect=True):
    if not CONFIG.is_file():
        say('plugin', '未启用')
        say('next', 'enable_plugin')
        return 'enable_plugin'
    state = bridge(action='state')
    renewal = bridge(action='renewal', op='status')
    if not running():
        # After a reinstall, put back the pairing and sign-in kept in the keychain (vault.py). This
        # command may not be allowed to write the signer's home; the install job restores it then.
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('vault', BASE / 'vault.py')
        vault = module_from_spec(spec)
        spec.loader.exec_module(vault)
        if HOME.is_dir() and sign_home() == 'writable':
            vault.quietly(vault.restore, lambda **args: bridge(**args), HOME)
    files = saved()
    job = running()
    lines = log_lines()
    expires = renewal.get('expires') or files['receipt']
    say('plugin', BASE.name)
    say('page', state['view'])
    say('job', 'running' if job else 'idle')
    say('stage', state['stage'])
    say('sign_home', sign_home())
    say('pairing_record', 'saved' if files['pairing'] else 'none')
    say('apple_session', 'saved' if files['session'] else 'none')
    say('installed_until', until(expires))
    if renewal.get('expires'):
        say('auto_renewal', ('on' if renewal.get('enabled') else 'off') +
            (f"（上次续期出错：{renewal['lastError']}）" if renewal.get('lastError') else ''))
    else:
        say('auto_renewal', 'none')
    # Pallas 0.5.5+ writes whether the runner is on this iPhone; the receipt stays when it is deleted.
    try:
        missing = json.loads(Path('/root/workspace/.phone-control.json').read_text()).get('runner') == 'missing'
    except (OSError, ValueError):
        missing = False
    if missing:
        say('runner', 'missing')
    if job:
        step = ('enter_code' if state['code'] else 'pair_in_settings' if state['stage'] == '等待系统配对'
                else 'sign_in' if state['signerPage'] else REVEAL_NEXT.get(state.get('reveal'), 'wait'))
        if state.get('link') and step in ('identify_device', 'install_in_safari'):
            say('link', state['link'])
        say('next', step)
        return step
    if state['stage'] == REVEALED:
        say('next', 'turn_on_developer_mode')
        return 'turn_on_developer_mode'

    reason = failure_of(state['stage'], lines)
    if reason:
        say('last_result', reason)
    if state.get('trustPending') and not missing:
        # Just installed: iOS will not start it until the person trusts its developer.
        say('next', 'trust_developer')
        return 'trust_developer'
    if not missing and (state['stage'] == DONE or (expires and expires - time.time() > WINDOW)):
        say('next', 'verify')
        return 'verify'
    if reason and classify(reason) != 'failed':
        say('next', classify(reason))
        return classify(reason)
    if not detect:
        say('next', 'failed' if reason else 'start')
        return 'failed' if reason else 'start'
    found = bridge(timeout=90, action='detect')
    lan = (found.get('lanError') or {}).get('code')
    say('local_network', {'authorization_denied': 'denied', 'no_lan_services': 'unavailable'}.get(lan, 'ok'))
    say('vpn', 'connected' if found['vpn'] else 'not_connected')
    port = found.get('port')
    say('port', f"{port}（{found['source']}）" if port else 'unknown')
    if len(found.get('open') or []) > 1:
        say('other_open_ports', ' '.join(map(str, found['open'][1:8])))
    step = ('host_unsupported' if lan == 'no_lan_services' else
            ('renew' if expires else 'start') if not found['vpn'] and found.get('builtinTunnel') else
            'connect_vpn' if not found['vpn'] else
            'allow_local_network' if lan == 'authorization_denied' else
            # Never paired: the device starts its pairing service only once it pairs, so start pairs
            # first; an earlier failure to find the service is no reason to stop.
            'port_unknown' if not port and files['pairing'] else
            'start' if not port else
            'failed' if reason else
            'renew' if expires else 'start')
    say('next', step)
    return step


def start(args):
    port = None
    new_login = '--new-login' in args
    if '--port' in args:
        port = int(args[args.index('--port') + 1])
    if running():
        say('note', '已有任务在运行，沿用它')
        say('link', bridge(action='state')['view'])
        return status(detect=False)
    if port is None:
        found = bridge(timeout=210, action='detect', startTunnel=True)
        lan = (found.get('lanError') or {}).get('code')
        if lan == 'no_lan_services':
            say('next', 'host_unsupported')
            return
        if not found['vpn']:
            say('vpn', 'not_connected')
            if found.get('tunnelError'):
                say('error', found['tunnelError'])
            say('next', 'tunnel_unavailable' if found.get('builtinTunnel') else 'connect_vpn')
            return
        if lan == 'authorization_denied':
            say('next', 'allow_local_network')
            return
        port = found.get('port')
        if not port and saved()['pairing']:
            say('port', 'unknown')
            say('next', 'port_unknown')
            return
        if not port:
            # A device that never paired has no pairing service on the network until it pairs:
            # pallasboot pairs first and finds the port after (any port here is only a first guess).
            say('port', 'unknown（这台设备还没配对过，先配对）')
            port = 49152
        else:
            say('port', f"{port}（{found['source']}）")
    env = dict(os.environ)
    if new_login:
        env['PALLAS_NEW_LOGIN'] = '1'
    run = subprocess.run(['sh', str(BASE / 'install.sh'), '--open', str(port)], env=env,
                         capture_output=True, text=True, timeout=60)
    out = (run.stdout + run.stderr).strip()
    if run.returncode != 0:
        say('error', out.splitlines()[-1] if out else f'install.sh 退出码 {run.returncode}')
        say('next', classify(out))
        return
    say('link', bridge(action='state')['view'])
    # Report what the job reaches first: an existing pairing may go straight to the sign-in page.
    follow(25, initial=None)


def reveal(args):
    if running():
        say('note', '已有任务在运行，沿用它')
        return status(detect=False)
    env = dict(os.environ)
    if '--new-login' in args:
        env['PALLAS_NEW_LOGIN'] = '1'
    bridge(action='install', mode='reveal', newLogin='--new-login' in args)
    # Report the first step that needs the person: the profile page, once the tunnel is up (the
    # first run also downloads cloudflared). Stage changes before that are not worth a turn.
    deadline = time.time() + 90
    time.sleep(2)
    while time.time() < deadline:
        state = bridge(action='state')
        if state.get('reveal') or state['signerPage'] or not running():
            break
        time.sleep(2)
    return status(detect=False)


def snapshot():
    state = bridge(action='state')
    return (running(), state['stage'], state['code'], state['signerPage'], state.get('reveal'), state.get('link'))


def follow(seconds, initial):
    begin = snapshot() if initial is None else initial
    deadline = time.time() + seconds
    time.sleep(2)
    while time.time() < deadline:
        now = snapshot()
        if now != begin or not now[0]:
            break
        time.sleep(2)
    return status(detect=False)


if __name__ == '__main__':
    cmd, *rest = sys.argv[1:] or ['status']
    try:
        if cmd == 'status':
            status()
        elif cmd == 'start':
            start(rest)
        elif cmd == 'reveal':
            reveal(rest)
        elif cmd == 'ddi':
            result = bridge(timeout=620, action='ddi')
            if result.get('detail'):
                say('developer_image', result['detail'])
            say('next', 'verify' if result.get('ok') else 'failed')
        elif cmd == 'trusted':
            bridge(action='trusted')
            status(detect=False)
        elif cmd == 'reset':
            bridge(timeout=120, action='reset')
            say('reset', 'done')
            status(detect=False)
        elif cmd == 'wait':
            follow(min(int(rest[0]) if rest else 45, 100), initial=None)
        else:
            sys.exit(__doc__)
    except (OSError, RuntimeError, ValueError) as e:
        say('error', e)
        say('next', 'failed')
