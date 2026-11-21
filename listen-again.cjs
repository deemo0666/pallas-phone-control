// iOS takes a suspended app's listening sockets: the server still reports it is listening, but
// connections are refused (2026-11-21: setup lost its page and job after pairing in Settings, and
// again right after the Developer Mode restart, when iOS launched Pallas in the background).
const net = require('node:net');

/** Has `server` listen again on 127.0.0.1, on `port` when it is free; resolves to the bound port. */
function listenAgain(server, port) {
  return new Promise((resolve, reject) => {
    const attempt = (wanted, fallback) => {
      const onError = error => {
        server.off('listening', onListening);
        if (fallback && error.code === 'EADDRINUSE') attempt(0, false);
        else reject(error);
      };
      const onListening = () => {
        server.off('error', onError);
        resolve(server.address().port);
      };
      server.once('error', onError);
      server.once('listening', onListening);
      server.listen(wanted, '127.0.0.1');
    };
    // Open connections stay; only the listening handle is replaced.
    if (server.listening) server.close();
    attempt(port, true);
  });
}

/** True when nothing accepts on 127.0.0.1:`port` any more. */
function refused(port, ms = 1000) {
  return new Promise(resolve => {
    const socket = net.connect({host:'127.0.0.1', port});
    const done = result => { clearTimeout(timer); socket.destroy(); resolve(result); };
    const timer = setTimeout(() => done(false), ms);
    socket.once('connect', () => done(false));
    socket.once('error', e => done(e.code === 'ECONNREFUSED'));
  });
}

/**
 * Checks `server` every `ms` and, once it refuses, calls `heal(port)`. Timers stop while the app
 * is suspended, so the first check after a resume runs at once. Returns a stop function.
 */
function watch(server, heal, ms = 2000) {
  // A taken socket can fail even getsockname (EBADF), so remember the port from when it listened.
  let busy = false, port = server.listening ? server.address().port : 0;
  const listening = () => { try { port = server.address().port; } catch {} };
  server.on('listening', listening);
  const timer = setInterval(async () => {
    if (busy || !port || !server.listening) return;
    busy = true;
    try { if (await refused(port)) await heal(port); }
    catch {}
    finally { busy = false; }
  }, ms);
  timer.unref?.();
  return () => { clearInterval(timer); server.off('listening', listening); };
}

module.exports = {listenAgain, refused, watch};
