// The app and guest have separate loopbacks. Browsers reach an iOS loopback
// listener; authenticated connections from the guest carry bytes to pallasboot's
// own HTTP server. Its secret URL, Host/Origin checks and SSE remain intact.
const net = require('node:net');
const {listenAgain} = require('./listen-again.cjs');

exports.start = async function start(key) {
  const idle = new Set();
  const sockets = new Set();
  const track = socket => {
    sockets.add(socket);
    socket.on('error', () => socket.destroy());
    socket.on('close', () => { sockets.delete(socket); idle.delete(socket); });
  };
  const front = net.createServer({pauseOnConnect:true}, client => {
    track(client);
    const link = idle.values().next().value;
    if (!link) { client.destroy(); return; }
    idle.delete(link);
    link.write('G');
    client.pipe(link).pipe(client);
    client.on('close', () => link.destroy());
    link.on('close', () => client.destroy());
  });
  const back = net.createServer(link => {
    track(link);
    link.setTimeout(5000, () => link.destroy());
    let prefix = Buffer.alloc(0);
    const authenticate = chunk => {
      prefix = Buffer.concat([prefix, chunk]);
      if (prefix.length < key.length) return;
      if (prefix.toString('ascii') !== key || idle.size >= 12) { link.destroy(); return; }
      link.removeListener('data', authenticate);
      link.pause();
      link.setTimeout(0);
      idle.add(link);
    };
    link.on('data', authenticate);
  });
  const listen = server => new Promise((ok, fail) => {
    server.once('error',fail);
    server.listen(0,'127.0.0.1',()=>{server.off('error',fail);ok();});
  });
  try { await listen(front); await listen(back); }
  catch(e) { front.close();back.close();throw e; }
  const relay = {port:front.address().port, reverse:back.address().port,
    // Both listeners go with the plugin's own when iOS suspends Pallas (listen-again.cjs).
    async listenAgain() {
      relay.port = await listenAgain(front, relay.port);
      relay.reverse = await listenAgain(back, relay.reverse);
    },
    close() { for (const s of sockets) s.destroy(); front.close(); back.close(); }};
  return relay;
};
