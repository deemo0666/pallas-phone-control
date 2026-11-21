#!/usr/bin/env python3
"""Bring back a hidden Developer Mode switch on this device, with no computer.

iOS shows the switch once Safari offers an app whose provisioning profile names this device; an
app signed for other devices, or not signed, does not do it. So: learn this device's UDID from a
Profile Service profile the person installs, register the UDID with their free team, sign the
runner for it, and offer the runner from a Safari install page. Profiles and install manifests
both need a public HTTPS address, which a cloudflared quick tunnel gives this guest.

The plugin runs this as a job (index.cjs), so it outlives the agent's command, and the app keeps
itself running in the background while the job runs (PairingKeepAlive).
"""
import asyncio
import hashlib
import html
import io
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from urllib.parse import quote

BASE = Path(__file__).resolve().parent
HOME = Path(os.environ.get('PALLAS_SIGN_HOME', '/root/.pallasboot'))
ROOT = Path(os.environ['SIBOOT_PALLAS_BIN'])
CLOUDFLARED = ('https://github.com/cloudflare/cloudflared/releases/download/2026.11.1/cloudflared-linux-arm64',
               'b155cec3e48e489cfb8e5c602769fb8c771083018d8881d68b4d18a791567c5a')
WAIT = 15 * 60
# The stage the app reads as "turn the switch on now" (PhoneSetupWatch.revealedStage).
REVEALED = '请打开开发者模式'


def load(name, file):
    spec = spec_from_file_location(name, BASE / file)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load('probe', 'probe.py')
signer_ui = load('runner_ui', 'runner-ui.py')


def step(reveal=None, link=None, stage=None):
    probe.bridge(action='reveal', step=reveal, link=link, stage=stage)
    if stage:
        print(stage, flush=True)


def cloudflared():
    """The pinned cloudflared, downloaded once into the signing home."""
    path = HOME / 'bin' / 'cloudflared'
    url, digest = CLOUDFLARED

    def good():
        if not path.is_file():
            return False
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest() == digest

    if good():
        return path
    step(stage='正在下载安全链接组件（约 38 MB）')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix('.part')
    with urllib.request.urlopen(url, timeout=60) as res, open(tmp, 'wb') as out:
        shutil.copyfileobj(res, out, 1 << 20)
    os.replace(tmp, path)
    if not good():
        path.unlink(missing_ok=True)
        raise RuntimeError('安全链接组件校验失败')
    path.chmod(0o700)
    return path


class Site:
    """The pages Safari and Settings reach through the tunnel, under one random path."""

    def __init__(self):
        self.token = secrets.token_urlsafe(18)
        self.challenge = secrets.token_hex(16)
        self.base = None
        self.udid = None
        self.identified = threading.Event()
        self.app = None  # (ipa bytes, bundle id, version)
        self.fetched = threading.Event()
        self.manifest_fetched = threading.Event()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                print('http', self.command, self.path.replace(site.token, '…'), flush=True)

            def reply(self, code, mime, body, headers=()):
                self.send_response(code)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(body)

            def route(self):
                prefix = '/' + site.token + '/'
                return self.path[len(prefix):] if self.path.startswith(prefix) else None

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                path = self.route()
                if path == 'ping':
                    return self.reply(200, 'text/plain', site.challenge.encode())
                if path == '':
                    return self.reply(200, 'text/html; charset=utf-8', page(
                        '识别本机 · Identify this device',
                        '<p><a class=b href="udid.mobileconfig">下载「Pallas 识别本机」<br>Download the profile</a></p>'
                        '<p>下载后打开「设置」，点顶部的「已下载描述文件」安装。<br>'
                        'Then open Settings and install it from “Profile Downloaded”.</p>'))
                if path == 'udid.mobileconfig':
                    return self.reply(200, 'application/x-apple-aspen-config', site.profile())
                if path == 'identified':
                    return self.reply(200, 'text/html; charset=utf-8', page(
                        '已识别 · Done', '<p>回到 Pallas。<br>Go back to Pallas.</p>'))
                if path == 'install':
                    if not site.app:
                        return self.reply(200, 'text/html; charset=utf-8', page('请稍候 · Not ready', '<p>…</p>'))
                    link = 'itms-services://?action=download-manifest&url=' + quote(site.base + 'manifest.plist', safe='')
                    return self.reply(200, 'text/html; charset=utf-8', page(
                        '安装 · Install',
                        f'<p><a class=b href="{html.escape(link)}">安装「Pallas 手机操控」<br>Install</a></p>'
                        '<p>系统再问时也点「安装」。提示「无法安装」是正常的，接着打开「设置 › 隐私与安全性 › 开发者模式」。<br>'
                        'Tap Install again when asked. “Unable to Install” is expected: then open Settings › '
                        'Privacy &amp; Security › Developer Mode.</p>'))
                if path == 'manifest.plist' and site.app:
                    site.manifest_fetched.set()
                    return self.reply(200, 'application/xml', site.manifest())
                if path == 'app.ipa' and site.app:
                    self.reply(200, 'application/octet-stream', site.app[0])
                    site.fetched.set()
                    return
                self.reply(404, 'text/plain', b'')

            def do_POST(self):
                if self.route() != 'udid':
                    return self.reply(404, 'text/plain', b'')
                body = self.rfile.read(min(int(self.headers.get('Content-Length', 0)), 65536))
                # A PKCS#7 envelope around a plain plist; the plist is all this needs.
                match = re.search(rb'<\?xml.*?</plist>', body, re.S)
                try:
                    attrs = plistlib.loads(match.group()) if match else {}
                except Exception:
                    attrs = {}
                udid = str(attrs.get('UDID', ''))
                if attrs.get('CHALLENGE') != site.challenge or not re.fullmatch(r'[0-9A-Fa-f-]{24,40}', udid):
                    return self.reply(400, 'text/plain', b'')
                site.udid = udid
                site.identified.set()
                # Settings expects a redirect; it opens the page in Safari.
                self.reply(301, 'text/plain', b'', [('Location', site.base + 'identified')])

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def port(self):
        return self.server.server_address[1]

    def profile(self):
        return plistlib.dumps({
            'PayloadContent': {'URL': self.base + 'udid', 'DeviceAttributes': ['UDID', 'PRODUCT', 'VERSION'],
                               'Challenge': self.challenge},
            'PayloadOrganization': 'Pallas', 'PayloadDisplayName': 'Pallas 识别本机',
            'PayloadDescription': '只读取设备标识，用来让「开发者模式」出现。不会安装任何设置。'
                                  ' Reads this device’s identifier only. Nothing is installed.',
            'PayloadVersion': 1, 'PayloadUUID': str(uuid.uuid4()).upper(),
            'PayloadIdentifier': 'io.pallas.identify.' + self.challenge[:8], 'PayloadType': 'Profile Service'})

    def manifest(self):
        _, bundle, version = self.app
        return plistlib.dumps({'items': [{
            'assets': [{'kind': 'software-package', 'url': self.base + 'app.ipa'}],
            'metadata': {'bundle-identifier': bundle, 'bundle-version': version, 'kind': 'software',
                         'title': 'Pallas 手机操控'}}]})


def page(title, body):
    return ('<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>body{{font:17px -apple-system,system-ui;margin:32px 20px;'
            'line-height:1.5}a.b{display:block;text-align:center;padding:14px;border-radius:12px;background:#0a84ff;'
            'color:#fff;text-decoration:none;font-weight:600}</style>'
            f'<h2>{html.escape(title)}</h2>{body}').encode()


def open_tunnel(binary, site):
    proc = subprocess.Popen([str(binary), 'tunnel', '--no-autoupdate', '--protocol', 'http2',
                             '--url', f'http://127.0.0.1:{site.port}'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    found = {}

    def read():
        for line in proc.stderr:
            m = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if m and 'url' not in found:
                found['url'] = m.group()
            if 'Registered tunnel connection' in line:
                found['up'] = True
    threading.Thread(target=read, daemon=True).start()
    deadline = time.time() + 90
    while time.time() < deadline and not ('url' in found and found.get('up')):
        if proc.poll() is not None:
            raise RuntimeError('安全链接没有建立')
        time.sleep(.5)
    if 'url' not in found:
        proc.kill()
        raise RuntimeError('安全链接没有建立')
    site.base = found['url'] + '/' + site.token + '/'
    # The new hostname takes a few seconds to resolve; Safari must not be sent there before.
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(site.base + 'ping', timeout=8) as res:
                if res.read().decode() == site.challenge:
                    return proc
        except OSError:
            pass
        time.sleep(2)
    proc.kill()
    raise RuntimeError('安全链接暂时打不开')


def wait(event, what):
    if not event.wait(WAIT):
        raise RuntimeError(f'等了 {WAIT // 60} 分钟没等到{what}')


def package(out):
    apps = list((out / 'Payload').glob('*.app'))
    if len(apps) != 1:
        raise RuntimeError('签名结果不完整')
    info = plistlib.loads((apps[0] / 'Info.plist').read_bytes())
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sorted(apps[0].rglob('*')):
            arc = 'Payload/' + str(path.relative_to(out / 'Payload'))
            if path.is_symlink():
                zi = zipfile.ZipInfo(arc)
                zi.external_attr = (0o120777 << 16)
                z.writestr(zi, os.readlink(path))
            elif path.is_file():
                z.write(path, arc)
    return data.getvalue(), info['CFBundleIdentifier'], str(info.get('CFBundleVersion', '1'))


async def sign(site, ipa):
    out = Path(tempfile.mkdtemp(prefix='reveal-', dir=os.environ.get('TMPDIR', '/tmp')))
    try:
        command = ['reveal', '--web', '--home', str(HOME), '--ipa', str(ipa), '--udid', site.udid,
                   '--out', str(out), '--anisette', 'https://ani.iloader.app']
        result = await signer_ui.run(ROOT, HOME, ipa, None, probe.CONFIG, probe.bridge, probe.relay, command=command,
                                     stages={'OK Runner signed for this device'}, success='正在准备安装页')
        if result != 0:
            raise RuntimeError('SIGNER')
        site.app = package(out)
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main(ipa):
    site = Site()
    tunnel = None
    outcome = '签装中断'
    try:
        step(stage='正在准备安全链接')
        tunnel = open_tunnel(cloudflared(), site)
        print('安全链接已建立', flush=True)
        step('identify', site.base, '请在 Safari 下载「Pallas 识别本机」，再到设置里安装')
        wait(site.identified, '「Pallas 识别本机」装好')
        print('已识别本机', site.udid[:8] + '…', flush=True)
        step(stage='已识别本机，正在签名')
        try:
            asyncio.run(sign(site, ipa))
        except RuntimeError as error:
            if str(error) == 'SIGNER':
                outcome = None  # runner-ui already ended the web page with the signer's reason
                return 1
            raise
        step('install', site.base + 'install', '请在 Safari 打开安装页并点「安装」')
        wait(site.manifest_fetched, 'Safari 打开安装页')
        # iOS checks the profile after it has the app; the switch appears around then.
        site.fetched.wait(90)
        step('enable', None, REVEALED)
        time.sleep(20)
        outcome = REVEALED
        return 0
    except Exception as error:
        outcome = '签装失败：' + str(error)[:120]
        print(outcome, flush=True)
        return 1
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
        site.server.shutdown()
        if outcome:
            probe.bridge(action='end-web', outcome=outcome)
        probe.bridge(action='reveal', step=None, link=None)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
