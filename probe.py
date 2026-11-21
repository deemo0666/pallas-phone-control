#!/usr/bin/env python3
"""Adapt upstream's Pallas Bonjour CLI and loopback listener to Pallas's QEMU guest."""
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

CONFIG = json.loads(Path('/root/workspace/.siboot-probe.json').read_text())
ROOT = Path(os.environ['SIBOOT_PALLAS_BIN'])


def bridge(**args):
    req = urllib.request.Request(f"http://10.0.2.2:{CONFIG['port']}/", json.dumps(args).encode(),
                                 {'Authorization': 'Bearer ' + CONFIG['key']})
    with urllib.request.urlopen(req, timeout=80) as response:
        return json.load(response)


def tunnel():
    payload = {'action': 'tunnel', 'interactive': os.environ.get('PALLAS_SIBOOT_AUTOMATIC') != '1'}
    request = urllib.request.Request(f"http://10.0.2.2:{CONFIG['port']}/", json.dumps(payload).encode(),
                                     {'Authorization': 'Bearer ' + CONFIG['key']})
    response = urllib.request.urlopen(request, timeout=135)
    try:
        reply = json.loads(response.readline(8192))
        if not reply.get('ok'):
            raise RuntimeError(reply['error']['message'])
        return response
    except BaseException:
        response.close()
        raise


def record_install(home, port):
    receipt = json.loads((home / 'runner-receipt.json').read_text())
    reply = bridge(action='renewal', op='installed', expires=receipt['expires'], port=port)
    if not reply['ok']:
        raise RuntimeError('无法保存续期计划')
    print('描述文件到期时间（Unix 秒）', receipt['expires'], flush=True)


async def copy_stream(reader, writer):
    while chunk := await reader.read(65536):
        writer.write(chunk)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


async def relay(reader, writer, target):
    peer = None
    try:
        other, peer = await asyncio.open_connection('127.0.0.1', target)
        await asyncio.gather(copy_stream(reader, peer), copy_stream(other, writer))
    except OSError:
        pass
    finally:
        writer.close()
        if peer:
            peer.close()


async def run(port, ipa=None):
    home = Path(os.environ.get("PALLAS_SIGN_HOME", ROOT / "state"))
    if not 0 < port < 65536:
        raise ValueError('invalid device port')
    if os.environ.get('PALLAS_DDI_ONLY') == '1':
        proc = await asyncio.create_subprocess_exec(str(ROOT/'siboot'), 'ddi', '--plain', '--terminal',
            '--home', str(home), '--port', str(port),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        async for raw in proc.stdout:
            line = raw.decode(errors='replace').strip()
            if line.startswith(('OK Developer image', 'Stopped:')):
                print(line, flush=True)
        return await proc.wait()
    if ipa and os.environ.get('PALLAS_RENEWAL') == '1':
        proc = await asyncio.create_subprocess_exec(str(ROOT/'siboot'), 'runner', '--plain', '--terminal',
            '--home', str(home), '--ipa', ipa, '--port', str(port), '--anisette', 'https://ani.iloader.app',
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        async for raw in proc.stdout:
            line = raw.decode(errors='replace').strip()
            if line.startswith(('OK Existing Apple session', 'OK Personal Team', 'OK Runner installation',
                                'OK Pallas runner', 'Stopped:')):
                print(line, flush=True)
        result = await proc.wait()
        if result == 0:
            record_install(home, port)
        return result
    # The upstream binary listens only on guest loopback. A local control socket lets
    # its CLI helper ask this parent to create a forward for the life of the probe.
    sock = ROOT / 'relay.sock'
    sock.unlink(missing_ok=True)
    forwards = []

    async def forward(reader, writer):
        try:
            target = int(await reader.readline())
            srv = await asyncio.start_server(lambda r, w: relay(r, w, target), '0.0.0.0', 0)
            forwards.append(srv)
            writer.write(f'{srv.sockets[0].getsockname()[1]}\n'.encode())
            await writer.drain()
        finally:
            writer.close()

    control = await asyncio.start_unix_server(forward, path=sock)
    bridge(action='stage', value='正在连接')
    print('配对状态页（在本机浏览器打开）', CONFIG['view'], flush=True)
    proc = await asyncio.create_subprocess_exec(str(ROOT/'siboot'), 'connect', '--plain', '--terminal',
        '--home', str(home), '--port', str(port),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    async def heartbeat():
        # The embedded shell streams only new output. Keep long Settings waits
        # from exhausting the host HTTP client's idle-body timeout.
        while True:
            await asyncio.sleep(30)
            print('配对验证仍在运行', flush=True)

    pulse = asyncio.create_task(heartbeat())
    tunnel_verified = False
    try:
        async for raw in proc.stdout:
            line = raw.decode(errors='replace').strip()
            code = re.search(r'Pairing code:\s*(\d{3})\s*(\d{3})', line)
            found = re.search(r'OK pairing service found at [\d.]+:(\d+)', line)
            if found:
                # A first pairing brought the device's pairing service up on its own port.
                port = int(found.group(1))
                print(line, flush=True)
            elif code:
                bridge(action='pin', code=''.join(code.groups()))
            elif 'is up in Settings' in line:
                bridge(action='stage', value='等待系统配对')
                print('等待系统配对', flush=True)
            elif line == 'OK The tunnel works':
                tunnel_verified = True
                print(line, flush=True)
            elif line.startswith(('Stopped:', 'OK this iPhone answers on', 'OK this iPhone accepts',
                                  'OK paired with', 'Settings connected:', 'paired: go back')):
                print(line, flush=True)
        result = await proc.wait()
        passed = result == 0 and tunnel_verified
        bridge(action='stage', value='配对隧道已验证' if passed else '验证未完成')
        if passed and ipa:
            from importlib.util import spec_from_file_location, module_from_spec
            spec = spec_from_file_location('runner_ui', Path(__file__).with_name('runner-ui.py'))
            ui = module_from_spec(spec)
            spec.loader.exec_module(ui)
            result = await ui.run(ROOT, home, ipa, port, CONFIG, bridge, relay)
            if result == 0:
                record_install(home, port)
            return result
        return 0 if passed else (result or 1)
    finally:
        pulse.cancel()
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        for server in [control, *forwards]:
            server.close()
            await server.wait_closed()
        sock.unlink(missing_ok=True)


def bonjour(args):
    if args[-1:] == ['--compact']:
        args.pop()
    action, *rest = args
    fields = {}
    if action == 'advertise':
        import socket
        kind, name, port, *txt = rest
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(ROOT/'relay.sock'))
            client.sendall((port+'\n').encode())
            forwarded = int(client.makefile('rb').readline())
        fields = dict(type=kind, name=name, port=forwarded, txt=txt)
    elif action == 'stop':
        fields = dict(id=rest[0])
    result = bridge(action=action, **fields)
    if not result['ok'] and action == 'advertise':
        # There is no interactive yes/no prompt in Pallas bash. Return once
        # so a denied local-network permission cannot spin the upstream retry loop.
        result['error']['code'] = 'pallas_advertise_failed'
    print(json.dumps(result))


if __name__ == '__main__':
    if Path(sys.argv[0]).name == 'pallas-open':
        from urllib.parse import urlsplit
        url = urlsplit(sys.argv[1])
        if url.hostname != '127.0.0.1' or not bridge(action='signer-page', path=url.path)['ok']:
            sys.exit(1)
        sys.exit(0)
    if sys.argv[1] == 'run':
        try:
            with tunnel():
                port = int(sys.argv[2])
                if os.environ.get('PALLAS_RENEWAL') == '1' or os.environ.get('PALLAS_DDI_ONLY') == '1':
                    # The pairing listener may have moved since the last installation.
                    detection = bridge(action='detect')
                    port = detection['data'].get('port') if detection.get('ok') else None
                    if not port:
                        raise RuntimeError('SiBoot pairing port unavailable')
                sys.exit(asyncio.run(run(port, sys.argv[3] if len(sys.argv) > 3 else None)))
        except (OSError, ValueError, RuntimeError) as error:
            sys.exit('Stopped: ' + str(error))
    bonjour(sys.argv[1:])
