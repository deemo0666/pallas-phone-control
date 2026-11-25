// The engine can be suspended by iPadOS. Check again when it next runs.
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const HOUR = 3600000;
const DIR = `pallasboot-runner-${require('./package.json').version}`;

function create(workspace, run, windowMs = 48 * HOUR) {
  const file = path.join(path.dirname(workspace), '.pallasboot-renewal.json');
  // From before the PallasBoot rename (plugin 0.6.x).
  try { const before = path.join(path.dirname(workspace), '.pallas-siboot-renewal.json'); if (!fs.existsSync(file)) fs.renameSync(before, file); } catch {}
  let busy = false, timer, mounting;
  function read() {
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
    catch (e) { if (e.code === 'ENOENT') return {enabled:false}; throw e; }
  }
  function save(state) {
    const tmp = file + '.' + randomUUID();
    fs.writeFileSync(tmp, JSON.stringify(state), {mode:0o600,flag:'wx'});
    try { fs.renameSync(tmp, file); } finally { fs.rmSync(tmp, {force:true}); }
  }
  function action(op, args = {}) {
    const state = read();
    switch (op) {
      case 'installed':
        if (!Number.isSafeInteger(args.expires) || args.expires < 1 ||
            !Number.isInteger(args.port) || args.port < 1 || args.port > 65535) throw Error('Invalid renewal receipt');
        save({...state, enabled:state.expires ? state.enabled : true, expires:args.expires,
              port:args.port, lastAttempt:0, lastError:null});
        break;
      case 'enable':
      case 'disable':
        if (!state.expires) throw Error('请先完成一次签装');
        save({...state, enabled:op === 'enable'});
        break;
      case 'reset':
        // Starting over (setup.sh reset): no plan left to renew.
        if (busy) throw Error('自动续期正在进行，请稍后再试');
        fs.rmSync(file, {force:true});
        break;
      case 'status': break;
      default: throw Error('Unknown renewal operation');
    }
    return read();
  }
  async function check() {
    if (busy) return false;
    const state = read();
    if (!state.enabled || !Number.isInteger(state.port) || state.port < 1 || state.port > 65535 ||
        !Number.isSafeInteger(state.expires) || state.expires * 1000 - Date.now() > windowMs ||
        Date.now() - state.lastAttempt < HOUR) return false;
    busy = true;
    try {
      save({...state, lastAttempt:Date.now()});
      const result = await run('renew', state.port);
      if (result.exitCode !== 0) throw Error(result.output?.split('\n').find(s => s.startsWith('Stopped:')) || '续期未完成，请检查 VPN 和本机登录状态');
      return true;
    } catch (err) {
      save({...read(), lastError:String(err.message).slice(0,180)});
      return false;
    } finally { busy = false; }
  }
  // A restart unmounts the developer image the runner needs. One attempt per engine start, after an
  // install; also on request (setup.sh ddi) when the runner would not launch.
  function ddi() {
    if (busy) return Promise.resolve({ok:false, detail:'自动续期正在进行，请稍后再试。'});
    const state = read();
    if (!Number.isInteger(state.port) || state.port < 1 || state.port > 65535) {
      return Promise.resolve({ok:false, detail:'请先完成一次签装。'});
    }
    mounting ??= run('ddi', state.port).then(({exitCode, output}) => {
      const detail = output?.split('\n').filter(s => s.startsWith('OK Developer image') || s.startsWith('Stopped:')).pop();
      return {ok:exitCode === 0, detail:detail || (exitCode === 0 ? '' : '开发者运行环境没有挂上')};
    }).finally(() => { mounting = undefined; });
    return mounting;
  }
  return {
    action, check, ddi,
    start() {
      const tick = () => check().catch(e => { console.error('pallasboot renewal:', e.message); return false; });
      // Serialize check() and ddi() so they never race on install.sh's non-blocking flock;
      // a successful renewal already mounts the developer image.
      tick().then(renewed => {
        if (!renewed) return ddi().catch(e => console.error('pallasboot developer image:', e.message));
      });
      timer = setInterval(tick, 15 * 60000);
      timer.unref?.();
    },
    stop() { clearInterval(timer); }
  };
}

module.exports = {create, DIR};
