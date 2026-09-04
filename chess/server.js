// One command runs everything: `npm install && node server.js`
// - static site  -> http://localhost:3000
// - signaling    -> ws://localhost:9000 (self-hosted PeerServer)
const http = require('http'), fs = require('fs'), path = require('path');
const { PeerServer } = require('peer');
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };
http.createServer((req, res) => {
  const file = path.join(__dirname, req.url.split('?')[0] === '/' ? 'index.html' : req.url.split('?')[0]);
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); return res.end('Not found'); }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(3000, () => console.log('P2P Chess at http://localhost:3000'));
PeerServer({ host: '0.0.0.0', port: 9000, path: '/' }, () => console.log('Signaling (PeerServer) on port 9000'));
