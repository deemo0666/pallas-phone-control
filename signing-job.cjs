// Keys live for one host-started job. Only the package installed in the engine profile supplies code.
const fs = require('node:fs');
const path = require('node:path');
const { createHash, createHmac, randomBytes } = require('node:crypto');

const files = ['install.sh', 'renew.sh', 'reveal.sh', 'probe.py', 'runner-ui.py', 'vault.py',
  'ddi.py', 'reveal.py', 'pallasboot-runner-aarch64', 'runner.sha256', 'ScreenRunner.ipa'];

function create(workspace, endpoint) {
  const active = new Map();
  let manifest;
  function asset(name) {
    return files.includes(name) ? path.join(__dirname, name) : undefined;
  }
  function proof(id, nonce) {
    const signing = active.get(id);
    if (signing && /^[a-f0-9]{64}$/.test(nonce)) {
      return createHmac('sha256', signing.key).update(nonce + ':' + endpoint().port).digest('hex');
    }
  }
  function authenticated(bearer) {
    for (const job of active.values()) if (bearer === 'Bearer ' + job.key) return job;
  }
  async function run(kind, port, newLogin, perform = onDevice) {
    const id = randomBytes(16).toString('hex');
    const job = { ...endpoint(), id, key: randomBytes(32).toString('hex') };
    active.set(id, job);
    try {
      manifest ??= Object.fromEntries(files.map(name => [name,
        createHash('sha256').update(fs.readFileSync(asset(name))).digest('hex')]));
      const container = path.dirname(path.dirname(workspace));
      return await perform({ kind, devicePort: port, newLogin, bridge: job, files: manifest,
        container: /\/Containers\/Data\/Application\/[0-9a-f-]{36}$/i.test(container) ? container : null });
    } finally { active.delete(id); }
  }
  return { asset, authenticated, proof, run, busy: () => active.size > 0, stop: () => active.clear() };
}

async function onDevice(request) {
  const shell = await import(process.env.DSH_IOS_SHELL_MODULE);
  return shell.signingJob(request);
}

module.exports = { create };
