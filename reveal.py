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

# Text on the Safari pages and in the profile and install prompt, in the language of the app's
# own setup card (App/Localizable.xcstrings); English when the viewer's language is not here.
PAGE_TEXT = {
    "zh-Hans": {
        "identify_title": "识别本机",
        "download": "下载「Pallas 识别本机」",
        "identify_steps": [
            "Safari 问能不能下载时，点「允许」。",
            "打开「设置」，点最上面的「已下载描述文件」",
            "点右上角「安装」，输入锁屏密码，再点「安装」"
        ],
        "done_title": "已识别本机",
        "back": "回到 Pallas 继续。",
        "wait": "请稍候",
        "install_title": "在 Safari 安装",
        "install": "安装「Pallas 手机操控」",
        "install_steps": [
            "系统问要不要安装，点「安装」",
            "提示「无法安装」是正常的，点「完成」",
            "打开「设置 › 隐私与安全性」，划到最下面，点「开发者模式」"
        ],
        "profile_name": "Pallas 识别本机",
        "profile_note": "只读取设备标识，用来让「开发者模式」出现。不会安装任何设置。",
        "app_name": "Pallas 手机操控"
    },
    "zh-Hant": {
        "identify_title": "識別本機",
        "download": "下載「Pallas 識別本機」",
        "identify_steps": [
            "Safari 詢問能否下載時，點「允許」。",
            "開啟「設定」，點最上方的「已下載描述檔」",
            "點右上角「安裝」，輸入鎖定密碼，再點「安裝」"
        ],
        "done_title": "已識別本機",
        "back": "回到 Pallas 繼續。",
        "wait": "請稍候",
        "install_title": "在 Safari 安裝",
        "install": "安裝「Pallas 手機操控」",
        "install_steps": [
            "系統詢問是否安裝，點「安裝」",
            "顯示「無法安裝」是正常的，點「完成」",
            "開啟「設定 › 隱私權與安全性」，滑到最下面，點「開發者模式」"
        ],
        "profile_name": "Pallas 識別本機",
        "profile_note": "只讀取裝置識別碼，用來讓「開發者模式」出現。不會安裝任何設定。",
        "app_name": "Pallas 手機操控"
    },
    "en": {
        "identify_title": "Identify This Device",
        "download": "Download “Pallas Device ID”",
        "identify_steps": [
            "When Safari asks, tap “Allow”.",
            "Open Settings and tap “Profile Downloaded” at the top",
            "Tap “Install” at the top right, enter your passcode, then tap “Install”"
        ],
        "done_title": "Device identified",
        "back": "Go back to Pallas to continue.",
        "wait": "Please wait",
        "install_title": "Install in Safari",
        "install": "Install “Pallas Phone Control”",
        "install_steps": [
            "When asked to install, tap “Install”",
            "“Unable to Install” is expected; tap “Done”",
            "Open Settings › Privacy & Security, scroll to the bottom, and tap “Developer Mode”"
        ],
        "profile_name": "Pallas Device ID",
        "profile_note": "Reads this device’s identifier only, so that Developer Mode can appear. Nothing is installed.",
        "app_name": "Pallas Phone Control"
    },
    "ja": {
        "identify_title": "このデバイスを識別",
        "download": "「Pallas デバイス識別」をダウンロード",
        "identify_steps": [
            "Safari に聞かれたら「許可」をタップします。",
            "「設定」を開き、一番上の「プロファイルがダウンロードされました」をタップ",
            "右上の「インストール」をタップし、パスコードを入力して、もう一度「インストール」をタップ"
        ],
        "done_title": "このデバイスを識別しました",
        "back": "Pallas に戻って続けてください。",
        "wait": "しばらくお待ちください",
        "install_title": "Safari でインストール",
        "install": "「Pallas スマホ操作」をインストール",
        "install_steps": [
            "インストールするか聞かれたら「インストール」をタップ",
            "「インストールできません」と表示されても問題ありません。「完了」をタップ",
            "「設定 › プライバシーとセキュリティ」を開き、一番下までスクロールして「デベロッパモード」をタップ"
        ],
        "profile_name": "Pallas デバイス識別",
        "profile_note": "デバイスの識別子だけを読み取り、デベロッパモードを表示できるようにします。設定は何もインストールされません。",
        "app_name": "Pallas スマホ操作"
    },
    "ko": {
        "identify_title": "이 기기 식별",
        "download": "“Pallas 기기 식별” 다운로드",
        "identify_steps": [
            "Safari가 물으면 “허용”을 탭하세요.",
            "“설정”을 열고 맨 위의 “프로파일이 다운로드됨” 탭",
            "오른쪽 위의 “설치”를 탭하고 암호를 입력한 다음 다시 “설치” 탭"
        ],
        "done_title": "기기를 식별했습니다",
        "back": "Pallas로 돌아가 계속하세요.",
        "wait": "잠시 기다려 주세요",
        "install_title": "Safari에서 설치",
        "install": "“Pallas 휴대폰 제어” 설치",
        "install_steps": [
            "설치할지 물으면 “설치” 탭",
            "“설치할 수 없음”이 표시되는 것은 정상이니 “완료” 탭",
            "“설정 › 개인정보 보호 및 보안”을 열고 맨 아래로 스크롤해 “개발자 모드” 탭"
        ],
        "profile_name": "Pallas 기기 식별",
        "profile_note": "개발자 모드가 나타나도록 이 기기의 식별자만 읽습니다. 아무것도 설치되지 않습니다.",
        "app_name": "Pallas 휴대폰 제어"
    },
    "es": {
        "identify_title": "Identificar este dispositivo",
        "download": "Descargar “Pallas Identificación del dispositivo”",
        "identify_steps": [
            "Cuando Safari pregunte, toca “Permitir”.",
            "Abre Ajustes y toca “Perfil descargado” arriba del todo",
            "Toca “Instalar” arriba a la derecha, introduce tu código y vuelve a tocar “Instalar”"
        ],
        "done_title": "Dispositivo identificado",
        "back": "Vuelve a Pallas para continuar.",
        "wait": "Espera un momento",
        "install_title": "Instalar en Safari",
        "install": "Instalar “Pallas Control del teléfono”",
        "install_steps": [
            "Cuando pregunte si quieres instalar, toca “Instalar”",
            "Es normal que diga “No se puede instalar”; toca “OK”",
            "Abre Ajustes › Privacidad y seguridad, desplázate hasta abajo y toca “Modo de desarrollador”"
        ],
        "profile_name": "Pallas Identificación del dispositivo",
        "profile_note": "Solo lee el identificador de este dispositivo para que aparezca el Modo de desarrollador. No se instala nada.",
        "app_name": "Pallas Control del teléfono"
    },
    "fr": {
        "identify_title": "Identifier cet appareil",
        "download": "Télécharger « Pallas Identification de l’appareil »",
        "identify_steps": [
            "Quand Safari le demande, touchez « Autoriser ».",
            "Ouvrez Réglages et touchez « Profil téléchargé » tout en haut",
            "Touchez « Installer » en haut à droite, saisissez votre code, puis touchez à nouveau « Installer »"
        ],
        "done_title": "Appareil identifié",
        "back": "Revenez dans Pallas pour continuer.",
        "wait": "Veuillez patienter",
        "install_title": "Installer dans Safari",
        "install": "Installer « Pallas Contrôle du téléphone »",
        "install_steps": [
            "Quand le système demande s’il faut installer, touchez « Installer »",
            "Le message « Impossible d’installer » est normal ; touchez « OK »",
            "Ouvrez Réglages › Confidentialité et sécurité, faites défiler jusqu’en bas et touchez « Mode développeur »"
        ],
        "profile_name": "Pallas Identification de l’appareil",
        "profile_note": "Lit uniquement l’identifiant de cet appareil, pour que le Mode développeur puisse apparaître. Rien n’est installé.",
        "app_name": "Pallas Contrôle du téléphone"
    },
    "de": {
        "identify_title": "Dieses Gerät erkennen",
        "download": "„Pallas Geräteerkennung“ laden",
        "identify_steps": [
            "Wenn Safari fragt, tippe auf „Erlauben“.",
            "Öffne die Einstellungen und tippe ganz oben auf „Profil geladen“",
            "Tippe oben rechts auf „Installieren“, gib deinen Code ein und tippe erneut auf „Installieren“"
        ],
        "done_title": "Gerät erkannt",
        "back": "Kehre zu Pallas zurück, um fortzufahren.",
        "wait": "Bitte warten",
        "install_title": "In Safari installieren",
        "install": "„Pallas Telefonsteuerung“ installieren",
        "install_steps": [
            "Wenn gefragt wird, ob installiert werden soll, tippe auf „Installieren“",
            "Die Meldung „… kann nicht installiert werden“ ist normal – tippe auf „Fertig“",
            "Öffne „Einstellungen › Datenschutz & Sicherheit“, scrolle ganz nach unten und tippe auf „Entwicklermodus“"
        ],
        "profile_name": "Pallas Geräteerkennung",
        "profile_note": "Liest nur die Kennung dieses Geräts, damit der Entwicklermodus erscheinen kann. Es wird nichts installiert.",
        "app_name": "Pallas Telefonsteuerung"
    },
    "pt-BR": {
        "identify_title": "Identificar este dispositivo",
        "download": "Baixar “Pallas Identificação do dispositivo”",
        "identify_steps": [
            "Quando o Safari perguntar, toque em “Permitir”.",
            "Abra Ajustes e toque em “Perfil Baixado”, no topo",
            "Toque em “Instalar” no canto superior direito, digite seu código e toque em “Instalar” de novo"
        ],
        "done_title": "Dispositivo identificado",
        "back": "Volte ao Pallas para continuar.",
        "wait": "Aguarde",
        "install_title": "Instalar no Safari",
        "install": "Instalar “Pallas Controle do celular”",
        "install_steps": [
            "Quando perguntar se deseja instalar, toque em “Instalar”",
            "A mensagem “Não é Possível Instalar” é normal; toque em “OK”",
            "Abra Ajustes › Privacidade e Segurança, role até o fim e toque em “Modo de Desenvolvedor”"
        ],
        "profile_name": "Pallas Identificação do dispositivo",
        "profile_note": "Só lê o identificador deste dispositivo, para que o Modo de Desenvolvedor possa aparecer. Nada é instalado.",
        "app_name": "Pallas Controle do celular"
    },
    "it": {
        "identify_title": "Identifica questo dispositivo",
        "download": "Scarica “Pallas Identificazione dispositivo”",
        "identify_steps": [
            "Quando Safari lo chiede, tocca “Consenti”.",
            "Apri Impostazioni e tocca “Profilo scaricato” in cima",
            "Tocca “Installa” in alto a destra, inserisci il codice, poi tocca di nuovo “Installa”"
        ],
        "done_title": "Dispositivo identificato",
        "back": "Torna su Pallas per continuare.",
        "wait": "Attendi",
        "install_title": "Installa in Safari",
        "install": "Installa “Pallas Controllo del telefono”",
        "install_steps": [
            "Quando chiede se installare, tocca “Installa”",
            "Il messaggio “Impossibile installare” è normale; tocca “Fine”",
            "Apri Impostazioni › Privacy e sicurezza, scorri fino in fondo e tocca “Modalità sviluppatore”"
        ],
        "profile_name": "Pallas Identificazione dispositivo",
        "profile_note": "Legge solo l’identificativo di questo dispositivo, perché possa comparire la Modalità sviluppatore. Non viene installato nulla.",
        "app_name": "Pallas Controllo del telefono"
    },
    "ru": {
        "identify_title": "Определить устройство",
        "download": "Загрузить «Pallas Определение устройства»",
        "identify_steps": [
            "Когда Safari спросит, нажмите «Разрешить».",
            "Откройте Настройки и нажмите «Профиль загружен» в самом верху",
            "Нажмите «Установить» в правом верхнем углу, введите код-пароль и снова нажмите «Установить»"
        ],
        "done_title": "Устройство определено",
        "back": "Вернитесь в Pallas, чтобы продолжить.",
        "wait": "Подождите",
        "install_title": "Установить в Safari",
        "install": "Установить «Pallas Управление телефоном»",
        "install_steps": [
            "На вопрос об установке нажмите «Установить»",
            "Сообщение «Не удается установить» — это нормально, нажмите «Готово»",
            "Откройте «Настройки › Конфиденциальность и безопасность», прокрутите вниз и нажмите «Режим разработчика»"
        ],
        "profile_name": "Pallas Определение устройства",
        "profile_note": "Считывает только идентификатор устройства, чтобы появился режим разработчика. Ничего не устанавливается.",
        "app_name": "Pallas Управление телефоном"
    }
}


def pick_language(header):
    """The first of the viewer's languages PAGE_TEXT has (Accept-Language); English when none is."""
    for part in str(header or '').split(','):
        tag = part.split(';')[0].strip().lower()
        if not tag:
            continue
        if tag.startswith('zh'):
            return 'zh-Hant' if re.search(r'hant|-tw|-hk|-mo', tag) else 'zh-Hans'
        if tag.startswith('pt'):
            return 'pt-BR'
        if tag.split('-')[0] in PAGE_TEXT:
            return tag.split('-')[0]
    return 'en'


def steps_html(lines):
    return '<ol>' + ''.join(f'<li>{html.escape(line)}</li>' for line in lines) + '</ol>'


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
        # The language Safari asked in; the system's own fetches (manifest) use the same.
        self.lang = 'en'
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
                if path in ('', 'udid.mobileconfig', 'identified', 'install'):
                    site.lang = pick_language(self.headers.get('Accept-Language'))
                t = PAGE_TEXT[site.lang]
                if path == '':
                    return self.reply(200, 'text/html; charset=utf-8', page(
                        site.lang, t['identify_title'],
                        f'<p><a class=b href="udid.mobileconfig">{html.escape(t["download"])}</a></p>'
                        + steps_html(t['identify_steps'])))
                if path == 'udid.mobileconfig':
                    return self.reply(200, 'application/x-apple-aspen-config', site.profile())
                if path == 'identified':
                    return self.reply(200, 'text/html; charset=utf-8', page(
                        site.lang, t['done_title'], f'<p>{html.escape(t["back"])}</p>'))
                if path == 'install':
                    if not site.app:
                        return self.reply(200, 'text/html; charset=utf-8', page(site.lang, t['wait'], '<p>…</p>'))
                    link = 'itms-services://?action=download-manifest&url=' + quote(site.base + 'manifest.plist', safe='')
                    return self.reply(200, 'text/html; charset=utf-8', page(
                        site.lang, t['install_title'],
                        f'<p><a class=b href="{html.escape(link)}">{html.escape(t["install"])}</a></p>'
                        + steps_html(t['install_steps'])))
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
            'PayloadOrganization': 'Pallas', 'PayloadDisplayName': PAGE_TEXT[self.lang]['profile_name'],
            'PayloadDescription': PAGE_TEXT[self.lang]['profile_note'],
            'PayloadVersion': 1, 'PayloadUUID': str(uuid.uuid4()).upper(),
            'PayloadIdentifier': 'io.pallas.identify.' + self.challenge[:8], 'PayloadType': 'Profile Service'})

    def manifest(self):
        _, bundle, version = self.app
        return plistlib.dumps({'items': [{
            'assets': [{'kind': 'software-package', 'url': self.base + 'app.ipa'}],
            'metadata': {'bundle-identifier': bundle, 'bundle-version': version, 'kind': 'software',
                         'title': PAGE_TEXT[self.lang]['app_name']}}]})


def page(lang, title, body):
    return (f'<!doctype html><html lang="{lang}"><meta charset=utf-8>'
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>body{{font:17px -apple-system,system-ui;margin:32px 20px;'
            'line-height:1.5}a.b{display:block;text-align:center;padding:14px;border-radius:12px;background:#0a84ff;'
            'color:#fff;text-decoration:none;font-weight:600}ol{padding-left:22px}li{margin:6px 0}</style>'
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
