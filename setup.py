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
PAIRED = Path('/run/pallasboot-paired')
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
# Written by Pallas (PhoneControl.noteRunner): whether the runner is on this iPhone, and the system version.
NOTE = Path('/root/workspace/.phone-control.json')
# Pairing from the device itself (Developer Mode › Other devices) came with iOS 27.
PAIRING_IOS = 27


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


def note():
    try:
        return json.loads(NOTE.read_text())
    except (OSError, ValueError):
        return {}


# Darwin kernel of each iOS before 27; 27 and later run kernel 26 or newer.
KERNEL_IOS = {25: '26', 24: '18', 23: '17', 22: '16'}


def system_version(state):
    """(iOS version, major) from Pallas's note, else from the kernel the plugin runs on
    (Pallas 0.5.5 writes no version). (None, None) when neither says."""
    version = str(note().get('ios') or '')
    try:
        return version, int(version.split('.')[0])
    except ValueError:
        pass
    kernel = str((state or {}).get('kernel') or '')
    try:
        major = int(kernel.split('.')[0])
    except ValueError:
        return None, None
    if major not in KERNEL_IOS:
        return None, None
    return f'{KERNEL_IOS[major]}（Darwin {kernel}）', int(KERNEL_IOS[major])


def too_old(state=None):
    """The system version when it cannot pair from the device and has no pairing yet, else None."""
    if PAIRED.is_file():
        return None
    if state is None and not note().get('ios'):
        try:
            state = bridge(action='state')
        except (OSError, RuntimeError, ValueError):
            return None
    version, major = system_version(state)
    return version if major is not None and major < PAIRING_IOS else None


def refuse_old(version):
    say('ios', version)
    say('next', 'ios_too_old')
    return 'ios_too_old'


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
        return 'signing_home_unavailable'
    # Codes from the signer (login.rs), not text: the agent explains them in the person's language.
    if 'paid_team' in reason or 'multiple_teams' in reason:
        return 'paid_account'
    return 'failed'


def status(detect=True):
    if not CONFIG.is_file():
        say('plugin', '未启用')
        say('next', 'enable_plugin')
        return 'enable_plugin'
    state = bridge(action='state')
    renewal = bridge(action='renewal', op='status')
    files = {'pairing': PAIRED.is_file() or bool(renewal.get('expires')), 'receipt': renewal.get('expires')}
    job = running()
    lines = log_lines()
    expires = renewal.get('expires') or files['receipt']
    say('plugin', BASE.name)
    say('page', state['view'])
    say('job', 'running' if job else 'idle')
    say('stage', state['stage'])
    say('installed_until', until(expires))
    if renewal.get('expires'):
        say('auto_renewal', ('on' if renewal.get('enabled') else 'off') +
            (f"（上次续期出错：{renewal['lastError']}）" if renewal.get('lastError') else ''))
    else:
        say('auto_renewal', 'none')
    # Pallas 0.5.5+ writes whether the runner is on this iPhone; the receipt stays when it is deleted.
    missing = note().get('runner') == 'missing'
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
    old = too_old(state)
    if old:
        return refuse_old(old)
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
    old = too_old()
    if old:
        return refuse_old(old)
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
        if not port and (PAIRED.is_file() or bridge(action='renewal', op='status').get('expires')):
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
    bridge(action='install', port=port, newLogin=new_login)
    say('link', bridge(action='state')['view'])
    # Report what the job reaches first: an existing pairing may go straight to the sign-in page.
    follow(25, initial=None)


def reveal(args):
    if running():
        say('note', '已有任务在运行，沿用它')
        return status(detect=False)
    old = too_old()
    if old:
        return refuse_old(old)
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
