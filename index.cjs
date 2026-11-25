// Optional host plugin. Only its own pairing advertisement is visible/removable.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const os = require('node:os');
const {randomBytes} = require('node:crypto');
const renewal = require('./renewal.cjs');
const listener = require('./listen-again.cjs');
const signing = require('./signing-job.cjs');
const TYPE = '_remotepairing-pairable-host._tcp';
// The native PallasBoot provider or LocalDevVPN carries this address back to the device.
const DEVICE = '10.7.0.1';
const SKILL = 'phone-control-setup';
// The stage an install job ends on when the runner is in (runner-ui.py DONE).
const INSTALLED = '手机操控已安装并已连接 Pallas';

// The signer stops with codes, not text (login.rs); the status page says them in the viewer's language.
const NOTICES = {
  multiple_teams: {
    'zh-Hans': '这个 Apple 账号属于不止一个开发团队，手机操控要用只有免费个人团队的 Apple 账号。回到 Pallas 继续。',
    'zh-Hant': '這個 Apple 帳號屬於不只一個開發團隊，手機操控要用只有免費個人團隊的 Apple 帳號。回到 Pallas 繼續。',
    en: 'This Apple Account belongs to more than one developer team. Phone Control needs an Apple Account with only a free Personal Team. Go back to Pallas to continue.',
    ja: 'このAppleアカウントは複数のデベロッパチームに属しています。スマホ操作には無料の個人チームだけを持つAppleアカウントが必要です。Pallasに戻って続けてください。',
    ko: '이 Apple 계정은 둘 이상의 개발자 팀에 속해 있습니다. 휴대폰 제어에는 무료 개인 팀만 있는 Apple 계정이 필요합니다. Pallas로 돌아가 계속하세요.',
    es: 'Esta Cuenta de Apple pertenece a más de un equipo de desarrollo. Control del teléfono necesita una Cuenta de Apple con solo un equipo personal gratuito. Vuelve a Pallas para continuar.',
    fr: 'Ce Compte Apple appartient à plusieurs équipes de développement. Contrôle du téléphone nécessite un Compte Apple avec une seule équipe personnelle gratuite. Revenez dans Pallas pour continuer.',
    de: 'Dieser Apple-Account gehört zu mehr als einem Entwicklerteam. Für die Telefonsteuerung brauchst du einen Apple-Account, der nur ein kostenloses persönliches Team hat. Kehre zu Pallas zurück, um fortzufahren.',
    'pt-BR': 'Esta Conta Apple pertence a mais de uma equipe de desenvolvedores. O Controle do celular precisa de uma Conta Apple com apenas uma equipe pessoal gratuita. Volte ao Pallas para continuar.',
    it: 'Questo Account Apple appartiene a più di un team di sviluppo. Il Controllo del telefono richiede un Account Apple con un solo team personale gratuito. Torna su Pallas per continuare.',
    ru: 'Эта учётная запись Apple состоит в нескольких командах разработчиков. Для управления телефоном нужна учётная запись Apple только с бесплатной личной командой. Вернитесь в Pallas, чтобы продолжить.',
  },
  paid_team: {
    'zh-Hans': '这个 Apple 账号是付费开发者账号，手机操控要用免费 Apple 账号。回到 Pallas 继续。',
    'zh-Hant': '這個 Apple 帳號是付費開發者帳號，手機操控要用免費 Apple 帳號。回到 Pallas 繼續。',
    en: 'This is a paid developer Apple Account. Phone Control needs a free Apple Account. Go back to Pallas to continue.',
    ja: 'このAppleアカウントは有料のデベロッパアカウントです。スマホ操作には無料のAppleアカウントが必要です。Pallasに戻って続けてください。',
    ko: '이 Apple 계정은 유료 개발자 계정입니다. 휴대폰 제어에는 무료 Apple 계정이 필요합니다. Pallas로 돌아가 계속하세요.',
    es: 'Esta Cuenta de Apple es una cuenta de desarrollador de pago. Control del teléfono necesita una Cuenta de Apple gratuita. Vuelve a Pallas para continuar.',
    fr: 'Ce Compte Apple est un compte développeur payant. Contrôle du téléphone nécessite un Compte Apple gratuit. Revenez dans Pallas pour continuer.',
    de: 'Dieser Apple-Account ist ein kostenpflichtiger Entwickler-Account. Für die Telefonsteuerung brauchst du einen kostenlosen Apple-Account. Kehre zu Pallas zurück, um fortzufahren.',
    'pt-BR': 'Esta Conta Apple é uma conta de desenvolvedor paga. O Controle do celular precisa de uma Conta Apple gratuita. Volte ao Pallas para continuar.',
    it: 'Questo Account Apple è un account sviluppatore a pagamento. Il Controllo del telefono richiede un Account Apple gratuito. Torna su Pallas per continuare.',
    ru: 'Эта учётная запись Apple — платная учётная запись разработчика. Для управления телефоном нужна бесплатная учётная запись Apple. Вернитесь в Pallas, чтобы продолжить.',
  },
};
const LANGUAGES = Object.keys(NOTICES.paid_team);

// The first of the viewer's languages we have; English when none is.
function pickLanguage(header) {
  for (const part of String(header || '').split(',')) {
    const tag = part.split(';')[0].trim().toLowerCase();
    if (!tag) continue;
    if (tag.startsWith('zh')) return /hant|-tw|-hk|-mo/.test(tag) ? 'zh-Hant' : 'zh-Hans';
    if (tag.startsWith('pt')) return 'pt-BR';
    const base = tag.split('-')[0];
    if (LANGUAGES.includes(base)) return base;
  }
  return 'en';
}

// A stage that carries a signer code, said in the viewer's language; other stages as they are.
function localStage(stage, header) {
  const code = Object.keys(NOTICES).find(c => String(stage).includes(c));
  return code ? {text: NOTICES[code][pickLanguage(header)], lang: pickLanguage(header)} : {text: stage, lang: 'zh-Hans'};
}
exports.localStage = localStage;

function knock(port, ms = 1500, host = DEVICE) {
  return new Promise(resolve => {
    const socket = net.connect({host, port});
    const done = result => { clearTimeout(timer); socket.destroy(); resolve(result); };
    const timer = setTimeout(() => done('timeout'), ms);
    socket.once('connect', () => done('open'));
    socket.once('error', e => done(e.code === 'ECONNREFUSED' ? 'refused' : (e.code || 'error')));
  });
}

// An open port is not proof: other devices on the network advertise _remotepairing._tcp too, and this
// device may have something else listening on their port (49152 on a reset iPad, 2026-11-21). Only a
// port that answers the RPPairing handshake, as pallasboot's own preflight sends it, is the pairing port.
function speaksRemotePairing(port, ms = 3000, host = DEVICE) {
  return new Promise(resolve => {
    const socket = net.connect({host, port});
    let reply = Buffer.alloc(0);
    const done = result => { clearTimeout(timer); socket.destroy(); resolve(result); };
    const timer = setTimeout(() => done(false), ms);
    socket.once('connect', () => {
      const body = Buffer.from(JSON.stringify({message:{plain:{_0:{request:{_0:{handshake:{_0:{
        hostOptions:{attemptPairVerify:true}, wireProtocolVersion:19}}}}}}}, originatedBy:'host', sequenceNumber:0}));
      const length = Buffer.alloc(2); length.writeUInt16BE(body.length);
      socket.write(Buffer.concat([Buffer.from('RPPairing'), length, body]));
    });
    socket.on('data', chunk => {
      reply = Buffer.concat([reply, chunk]);
      if (reply.length >= 9) done(reply.subarray(0, 9).toString() === 'RPPairing');
    });
    socket.once('error', () => done(false));
    socket.once('close', () => done(false));
  });
}

// The remote pairing port changes between devices and restarts. Try the saved port and every
// Bonjour record first, keeping only a port that answers as this device's pairing service on the
// VPN address. Scan as a last resort.
async function detectPort(call, saved, host = DEVICE, verify = speaksRemotePairing) {
  const out = {vpn:false, port:null, source:null, lanError:null, open:[]};
  const ports = new Map();
  if (saved) ports.set(saved, 'saved');
  let browse;
  try { browse = await call({action:'browse', type:'_remotepairing._tcp', timeout:3}); }
  catch (e) { browse = {ok:false, error:{code:'no_lan_services', message:e.message}}; }
  if (!browse.ok) out.lanError = browse.error;
  else for (const service of browse.data.services || []) {
    try {
      const reply = await call({action:'resolve', name:service.name, type:'_remotepairing._tcp', timeout:4});
      const port = reply.ok && /[.:](\d{2,5})$/.exec(String(reply.data.path?.remote || ''));
      if (port && !ports.has(+port[1])) ports.set(+port[1], 'bonjour');
    } catch {}
  }
  for (const [port, source] of ports) {
    if (await knock(port, 1500, host) !== 'open') continue;
    if (await verify(port, 3000, host)) return {...out, vpn:true, port, source};
    out.rejected = [...(out.rejected || []), port];
  }
  const probe = await knock(1, 1500, host);
  out.vpn = probe === 'refused' || probe === 'open';
  if (!out.vpn) return {...out, vpnProbe:probe};
  const deadline = Date.now() + 40000;
  let next = 49152;
  const worker = async () => {
    while (next <= 65535 && Date.now() < deadline) {
      const port = next++;
      if (port !== 62078 && await knock(port, 700, host) === 'open') out.open.push(port);
    }
  };
  await Promise.all(Array.from({length:256}, worker));
  out.open.sort((a, b) => a - b);
  out.scanComplete = next > 65535;
  for (const port of out.open) {
    if (await verify(port, 3000, host)) { out.port = port; out.source = 'scan'; break; }
  }
  return out;
}

function loadSkill() {
  return fs.readFileSync(path.join(__dirname, 'SKILL.md'), 'utf8').replaceAll('{{DIR}}', renewal.DIR);
}

// The reveal job (reveal.py) sends the person to pages it serves through a cloudflared quick tunnel.
const REVEAL_STEPS = ['identify', 'install', 'enable'];
const REVEAL_LINK = /^https:\/\/[a-z0-9-]+\.trycloudflare\.com\/[A-Za-z0-9_-]{16,64}\/(install)?$/;

// Replace a workspace entry atomically, including when the previous entry is a symlink.
function writeResult(file, value) {
  const temporary = file + '.' + randomBytes(16).toString('hex');
  fs.writeFileSync(temporary, value, {flag:'wx', mode:0o600});
  try { fs.renameSync(temporary, file); } finally { fs.rmSync(temporary, {force:true}); }
}

async function nativeApproval(kind) {
  const ask = globalThis[Symbol.for('dsh.ios.authorizePallasBoot')];
  if (!ask) throw Error('请更新 Pallas 后再签装');
  await ask(kind);
}
const hostHook = (name, old) => globalThis[Symbol.for('dsh.ios.' + name)] ?? globalThis[Symbol.for('dsh.ios.' + old)];
// Workspace files from before the PallasBoot rename (plugin 0.6.x).
const OLD_FILES = {'.siboot-trust-pending':'.pallasboot-trust-pending', '.siboot-install.log':'.pallasboot-install.log', '.siboot-listener.log':'.pallasboot-listener.log'};
const INSTALL_LOG = '.pallasboot-install.log';

exports.start = function start(workspace, call, scheduler, perform, authorize = nativeApproval) {
  const key = randomBytes(32).toString('hex');
  const statusKey = randomBytes(32).toString('hex');
  const viewKey = randomBytes(20).toString('hex');
  const origin = () => 'http://127.0.0.1:' + server.address().port;
  const jobs = signing.create(workspace, () => ({port:server.address().port}));
  const run = (kind, port, newLogin) => {
    if (resetting && kind !== 'reset') return Promise.reject(Error('正在清除签装数据'));
    return jobs.run(kind, port, newLogin, perform);
  };
  scheduler = typeof scheduler === 'function' ? scheduler(workspace, run) : scheduler ?? renewal.create(workspace, run);
  const config = path.join(workspace, '.pallasboot-probe.json');
  // Pallas 0.5.4 and older read the config under its old name.
  const oldConfig = path.join(workspace, '.siboot-probe.json');
  for (const [from, to] of Object.entries(OLD_FILES)) {
    try { if (!fs.existsSync(path.join(workspace, to))) fs.renameSync(path.join(workspace, from), path.join(workspace, to)); } catch {}
  }
  let webRelay, signerPath;
  // The relay's port can move when it listens again (listen-again.cjs).
  const signerPage = () => webRelay && signerPath ? 'http://127.0.0.1:' + webRelay.port + signerPath : undefined;
  let owned, advertising = false, closed = false, stage = 'waiting', pin = '', expires = 0;
  let installing = false, reveal, link;
  // A runner signed by a free account starts only after the person trusts its developer in Settings;
  // until they say so, setup's next step is that (setup.sh trusted clears it). A file, because iOS
  // may end Pallas while the person is in Settings.
  const trustFile = path.join(workspace, '.pallasboot-trust-pending');
  const trust = pending => { try { pending ? writeResult(trustFile, '') : fs.rmSync(trustFile, {force:true}); } catch {} };
  let resetting = false;
  const escapeHTML = s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  const server = http.createServer(async (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    if (req.method === 'GET' && req.url.startsWith('/asset/')) {
      const file = jobs.asset(req.url.slice(7));
      if (!file) return res.writeHead(404).end();
      const stream = fs.createReadStream(file);
      stream.on('error', () => res.destroy());
      res.on('close', () => stream.destroy());
      return stream.pipe(res);
    }
    if (req.method === 'GET' && req.url.startsWith('/proof/')) {
      const [, , id, nonce] = req.url.split('/');
      const proof = jobs.proof(id, nonce);
      return proof ? res.end(proof) : res.writeHead(403).end();
    }
    const privateView = req.url === '/' + viewKey;
    if (req.method === 'GET' && (privateView || req.url === '/status')) {
      if (privateView && signerPage()) { res.writeHead(303,{Location:signerPage()}).end(); return; }
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.setHeader('Referrer-Policy', 'no-referrer');
      const shown = localStage(stage, req.headers['accept-language']);
      return res.end('<html lang="' + shown.lang + '"><meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="2"><h1>' +
        escapeHTML(shown.text) + '</h1>' + (privateView && Date.now() < expires ? '<h2>' + pin + '</h2>' : ''));
    }
    const job = jobs.authenticated(req.headers.authorization);
    const reader = req.headers.authorization === 'Bearer ' + statusKey;
    if (req.method !== 'POST' || req.url !== '/' || (!job && !reader && req.headers.authorization !== 'Bearer ' + key)) {
      res.writeHead(403).end(); return;
    }
    try {
      let body = '';
      for await (const chunk of req) {
        body += chunk;
        // Only authenticated requests get here; the keychain copy (vault-save) is the largest.
        if (body.length > (1 << 21)) throw Error('oversized request');
      }
      const args = JSON.parse(body);
      if (job && jobs.authenticated(req.headers.authorization) !== job) return res.writeHead(403).end();
      const setupAction = ['state','detect','install','reset','trusted','ddi'].includes(args.action) ||
        (args.action === 'renewal' && ['status','enable','disable'].includes(args.op));
      if ((reader && args.action !== 'state') || (!job && !reader && !setupAction)) return res.writeHead(403).end();
      let reply;
      if (args.action === 'renewal') {
        reply = {ok:true,data:scheduler.action(args.op, args)};
      } else if (args.action === 'ddi') {
        reply = {ok:true,data:await scheduler.ddi()};
      } else if (args.action === 'detect') {
        const withTunnel = hostHook('withPallasBootTunnel', 'withSiBootTunnel');
        const detect = () => detectPort(call, scheduler.action('status').port);
        const data = withTunnel && args.startTunnel === true
          ? await withTunnel(detect).catch(error => ({vpn:false, tunnelError:error.message}))
          : await detect();
        reply = {ok:true, data:{...data, builtinTunnel:!!withTunnel}};
      } else if (args.action === 'vault-read' || args.action === 'vault-save') {
        // A copy of the signer's files in the keychain (vault.py packs it), for after a reinstall.
        const vault = globalThis[Symbol.for('dsh.ios.pallasBootSigningVault')];
        if (!vault) reply = {ok:true, data:{supported:false}};
        else if (args.action === 'vault-read') reply = {ok:true, data:{supported:true, value:await vault.read()}};
        else if (typeof args.value === 'string' && args.value.length <= 1 << 20) {
          await vault.save(args.value);
          reply = {ok:true, data:{supported:true}};
        } else throw Error('invalid vault copy');
      } else if (args.action === 'trusted') {
        trust(false);
        reply = {ok:true,data:{}};
      } else if (args.action === 'reset') {
        if (resetting || installing || jobs.busy()) throw Error('签装正在进行');
        resetting = true;
        try {
          await authorize('reset');
          if (closed || jobs.busy()) throw Error('签装状态已改变');
          const result = await run('reset');
          if (result.exitCode !== 0) throw Error('签装数据未能清除');
          scheduler.action('reset');
          trust(false);
          // The keychain copy would bring everything back at the next install.
          await globalThis[Symbol.for('dsh.ios.pallasBootSigningVault')]?.save('');
          webRelay?.close(); webRelay = undefined; signerPath = undefined;
          stage = 'waiting'; pin = ''; expires = 0; reveal = undefined; link = undefined;
          reply = {ok:true,data:{}};
        } finally { resetting = false; }
      } else if (args.action === 'tunnel') {
        const withTunnel = hostHook('withPallasBootTunnel', 'withSiBootTunnel');
        if (withTunnel) {
          // Keep the lease for the lifetime of the guest's HTTP connection. A killed guest
          // also closes its socket, even if its Python finally block cannot run.
          await withTunnel(() => new Promise(resolve => {
            if (res.destroyed) return resolve();
            res.once('close', resolve);
            res.writeHead(200, {'Content-Type':'application/x-ndjson'});
            res.write(JSON.stringify({ok:true}) + '\n');
          }), args.interactive === true);
          return;
        }
        reply = {ok:true};
      } else if (args.action === 'state') {
        reply = {ok:true,data:{stage, code:Date.now() < expires, signerPage:!!signerPage(), installing, reveal, link:reader || job ? link : undefined, trustPending:fs.existsSync(trustFile),
                               // The iOS kernel, for setup.py to tell the system version (Pallas 0.5.5 writes none).
                               kernel:process.env.DSH_IOS_SHELL_MODULE ? os.release() : null,
                               view:origin() + (reader || job ? '/' + viewKey : '/status')}};
      } else if (args.action === 'install' && (args.mode === 'reveal' ||
                 Number.isInteger(args.port) && args.port > 0 && args.port < 65536)) {
        if (resetting) throw Error('正在清除签装数据');
        if (!installing) {
          installing = true;
          stage = 'waiting'; pin = ''; expires = 0; reveal = undefined; link = undefined;
          const kind = args.mode === 'reveal' ? 'reveal' : 'install';
          Promise.resolve().then(() => authorize(kind)).then(() => {
            if (closed) throw Error('签装已取消');
            return run(kind, args.port, args.newLogin === true);
          }).then(({exitCode: code, output}) => {
            if (code !== 0 && stage === 'waiting') {
              stage = output?.includes('本机签装目录不可写。') ? '签装中断：本机签装目录不可写。' : '签装中断（退出码 ' + code + '）';
            }
            if (code === 0 && stage === INSTALLED) trust(true);
            writeResult(path.join(workspace, INSTALL_LOG), stage);
          })
            .catch(e => { stage = '签装中断：' + String(e.message).slice(0, 160); })
            .finally(() => {
              installing = false; reveal = undefined; link = undefined; pin = ''; expires = 0;
              webRelay?.close(); webRelay = undefined; signerPath = undefined;
              if (owned) { call({action:'stop', id:owned}).catch(() => {}); owned = undefined; }
            });
        }
        reply = {ok:true,data:{installing:true}};
      } else if (args.action === 'reveal') {
        reveal = REVEAL_STEPS.includes(args.step) ? args.step : undefined;
        link = typeof args.link === 'string' && REVEAL_LINK.test(args.link) ? args.link : undefined;
        if (typeof args.stage === 'string' && args.stage) stage = args.stage.slice(0, 180);
      } else if (args.action === 'web-relay') {
        const relayKey = randomBytes(32).toString('hex');
        const relay = await require('./web-relay.cjs').start(relayKey);
        if (jobs.authenticated(req.headers.authorization) !== job) { relay.close(); return res.writeHead(403).end(); }
        webRelay?.close(); signerPath = undefined;
        webRelay = relay;
        reply = {ok:true,data:{port:webRelay.port,reverse:webRelay.reverse,key:relayKey}};
      } else if (args.action === 'signer-page' && webRelay && /^\/[a-f0-9]{24,128}\/$/.test(args.path)) {
        signerPath = args.path;
      } else if (args.action === 'end-web') {
        webRelay?.close(); webRelay = undefined; signerPath = undefined;
        stage = typeof args.outcome === 'string' ? args.outcome.slice(0, 180) : '签装已结束';
      } else if (args.action === 'pin' && /^\d{6}$/.test(args.code)) {
        pin = args.code; expires = Date.now() + 300000; stage = '请输入配对码';
      } else if (args.action === 'stage' && ['等待系统配对','配对隧道已验证','验证未完成','正在连接'].includes(args.value)) {
        stage = args.value; pin = ''; expires = 0;
      } else if (args.action === 'advertise' && args.type === TYPE && !owned && !advertising &&
                 Number.isInteger(args.port) && /^[a-f0-9-]{36}$/i.test(args.name) &&
                 Array.isArray(args.txt) && args.txt.every(x => typeof x === 'string' && x.includes('='))) {
        advertising = true;
        try {
          reply = await call({action:'advertise', type:TYPE, name:args.name, port:args.port, txt:args.txt});
          if (reply.ok) {
            if (jobs.authenticated(req.headers.authorization) === job) owned = reply.data.id;
            else await call({action:'stop', id:reply.data.id});
          }
        } finally { advertising = false; }
      } else if (args.action === 'types') {
        reply = await call({action:'types'});
      } else if (args.action === 'list') {
        reply = await call({action:'list'});
        if (reply.ok) reply.data = {
          advertisements:reply.data.advertisements.filter(a => a.id === owned),
          app_in_background:reply.data.app_in_background
        };
      } else if (args.action === 'stop' && owned && args.id === owned) {
        reply = await call({action:'stop', id:owned});
        if (reply.ok) owned = undefined;
      } else throw Error('unsupported request');
      res.end(JSON.stringify(reply || {ok:true,data:{}}));
    } catch (err) { res.end(JSON.stringify({ok:false,error:{code:'probe_error',message:err.message}})); }
  });
  // The guest reads the port from here before every request.
  const publish = port => {
    const publicConfig = JSON.stringify({port, key, view:origin() + '/status'});
    for (const file of [oldConfig, config]) writeResult(file, publicConfig);
    globalThis[Symbol.for('dsh.ios.pallasBootStatus')]?.({port, key:statusKey});
  };
  // Pairing, Apple's two-factor code and the Developer Mode restart all take the person out of
  // Pallas; when iOS has taken the listeners meanwhile, listen again so the job and page carry on.
  const unwatch = listener.watch(server, async port => {
    const now = await listener.listenAgain(server, port);
    await webRelay?.listenAgain().catch(() => {});
    // The engine drops the plugin's stdout and stderr; this one line is for diagnosis.
    try { writeResult(path.join(workspace, '.pallasboot-listener.log'), `${new Date().toISOString()} listening again: ${port} -> ${now}\n`); } catch {}
    if (now !== port && !closed) publish(now);
  });
  server.listen(0, '127.0.0.1', () => {
    publish(server.address().port);
    scheduler.start();
  });
  return () => {
    closed = true; jobs.stop(); unwatch(); scheduler.stop(); webRelay?.close(); server.close(); server.closeAllConnections();
    if (owned) call({action:'stop', id:owned}).catch(() => {});
    for (const file of [config, oldConfig]) {
      try { if (JSON.parse(fs.readFileSync(file)).key === key) fs.unlinkSync(file); } catch {}
    }
  };
};

exports.detectPort = detectPort;
exports.speaksRemotePairing = speaksRemotePairing;
exports.name = 'pallas-phone-control';
exports.stage = workspace => {
  const dir = path.join(workspace, renewal.DIR);
  // Never replace an unrelated workspace file.
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, {mode:0o700});
  if (!fs.lstatSync(dir).isDirectory()) throw Error('Invalid pallasboot-probe folder');
  for (const file of ['setup.sh', 'setup.py', 'renew.sh']) {
    const src = fs.readFileSync(path.join(__dirname, file));
    const dest = path.join(dir, file);
    try { fs.writeFileSync(dest, src, {mode:0o600, flag:'wx'}); }
    catch (e) {
      if (e.code !== 'EEXIST' || !fs.lstatSync(dest).isFile() || !src.equals(fs.readFileSync(dest))) throw e;
    }
  }
};
exports.inject = ['tools', 'skills'];
exports.skill = () => ({
  name:SKILL, source:'plugin',
  description:'开通、修复或检查手机操控（让你操作这台设备上的其他 App）。用户说「开通手机操控」「设置手机操控」「手机操控用不了」「续期状态」，或想让你操作其他 App 而你没有 iphone_screen 工具时，先加载它。Set up, repair or check phone control from this chat.',
  content:loadSkill(),
});
exports.apply = ctx => {
  const workspace = process.cwd();
  exports.stage(workspace);
  ctx.skills.register(exports.skill());
  let nativeLan;
  ctx.effect(() => exports.start(workspace, async args => {
    // The pairing server also runs between conversations. The native LAN bridge
    // can be installed even when the FS tool is registered only on an agent.
    let tool = ctx.tools.get('lan_services') || nativeLan;
    if (!tool) {
      const register = globalThis[Symbol.for('dsh.ios.lanTool')];
      register?.({
        systemPrompt: {section() {}, getSectionOrder() { return 0; }},
        tools: {register(definition) {
          if (definition.name === 'lan_services') nativeLan = definition;
        }},
      }, definition => definition);
      tool = nativeLan;
    }
    if (!tool) throw Error('This Pallas build has no lan_services');
    return JSON.parse(await tool.execute(args, {}));
  }));
};
