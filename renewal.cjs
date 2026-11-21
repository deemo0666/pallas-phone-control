// The engine can be suspended by iPadOS. Check again when it next runs.
const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const HOUR = 3600000;
const DIR = `siboot-runner-${require('./package.json').version}`;

function create(workspace, run = runOnDevice, windowMs = 48 * HOUR, mountRun = mountOnDevice) {
  const file = path.join(path.dirname(workspace), '.pallas-siboot-renewal.json');
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
      case 'status': break;
      default: throw Error('Unknown renewal operation');
    }
    return read();
  }
  async function check() {
    if (busy) return;
    const state = read();
    if (!state.enabled || !Number.isInteger(state.port) || state.port < 1 || state.port > 65535 ||
        !Number.isSafeInteger(state.expires) || state.expires * 1000 - Date.now() > windowMs ||
        Date.now() - state.lastAttempt < HOUR) return;
    busy = true;
    try {
      save({...state, lastAttempt:Date.now()});
      await run(state.port);
    } catch (err) {
      save({...read(), lastError:String(err.message).slice(0,180)});
    } finally { busy = false; }
  }
  // A restart unmounts the developer image the runner needs. One attempt per engine start, after an
  // install; also on request (setup.sh ddi) when the runner would not launch.
  function ddi() {
    const state = read();
    if (!Number.isInteger(state.port) || state.port < 1 || state.port > 65535) {
      return Promise.resolve({ok:false, detail:'请先完成一次签装。'});
    }
    mounting ??= mountRun(state.port).finally(() => { mounting = undefined; });
    return mounting;
  }
  return {
    action, check, ddi,
    start() {
      const tick = () => check().catch(e => console.error('siboot renewal:', e.message));
      tick();
      ddi().catch(e => console.error('siboot developer image:', e.message));
      timer = setInterval(tick, 15 * 60000);
      timer.unref?.();
    },
    stop() { clearInterval(timer); }
  };
}

// The signer links the runner to the Pallas whose data container holds this workspace
// (…/Application/<UUID>/Documents/workspace), so a test build pairs with itself.
function hostEnv(workspace = process.cwd()) {
  const container = path.dirname(path.dirname(workspace));
  if (!/\/Containers\/Data\/Application\/[0-9A-Fa-f-]{36}$/.test(container)) return '';
  return 'PALLAS_HOST_CONTAINER=' + container + ' ';
}

async function runOnDevice(port) {
  const shell = await import(process.env.DSH_IOS_SHELL_MODULE);
  const job = shell.execute({command:hostEnv() + 'PALLAS_SIBOOT_AUTOMATIC=1 sh ./' + DIR + '/renew.sh now ' + port, workdir:'/root/workspace',
    timeoutMs:600000,stdoutMaxBytes:2048,stderrMaxBytes:1024,
    sandboxPolicy:{mode:'danger-full-access',workspaceRoot:'/root/workspace'}});
  const result = await job.result();
  if (result.exitCode !== 0) {
    const output = [result.stdout?.text, result.stderr?.text].filter(Boolean).join('\n');
    const detail = output.split('\n').find(s => s.startsWith('Stopped:'));
    throw Error(detail || '续期未完成，请检查 VPN 和本机登录状态');
  }
}
async function mountOnDevice(port) {
  const shell = await import(process.env.DSH_IOS_SHELL_MODULE);
  const job = shell.execute({command:hostEnv() + 'PALLAS_SIBOOT_AUTOMATIC=1 sh ./' + DIR + '/renew.sh ddi ' + port, workdir:'/root/workspace',
    timeoutMs:600000,stdoutMaxBytes:2048,stderrMaxBytes:1024,
    sandboxPolicy:{mode:'danger-full-access',workspaceRoot:'/root/workspace'}});
  const result = await job.result();
  const output = [result.stdout?.text, result.stderr?.text].filter(Boolean).join('\n');
  const detail = output.split('\n').filter(s => s.startsWith('OK Developer image') || s.startsWith('Stopped:')).pop();
  return {ok:result.exitCode === 0, detail:detail || (result.exitCode === 0 ? '' : '开发者运行环境没有挂上')};
}
module.exports = {create, DIR, hostEnv};
