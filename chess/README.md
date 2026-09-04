# P2P Chess

A lightweight browser-based peer-to-peer chess app with chat and spectators.
One HTML file, one JS file, one CSS file — no build step, no framework, no
accounts, no database. Fully self-hosted: the bundled server serves the static
files **and** runs your own signaling server, so no third-party service is
involved.

## Run

```
cd chess
npm install   # first time only — installs the PeerServer signaling package
node server.js
```

Then open http://localhost:3000. That one command runs:

- the static site on port **3000**
- your own PeerJS signaling server (PeerServer) on port **9000**

The app signals through whatever host served the page (`location.hostname`),
so it works unchanged on your LAN — share `http://<your-ip>:3000?join=CODE`.

## How it works

- **Rules**: [chess.js](https://github.com/jhlywa/chess.js) via CDN. Every peer
  re-validates every move before applying it.
- **Networking**: [PeerJS](https://peerjs.com) WebRTC data channels in a star
  topology — everyone connects to the host player, who relays messages to all
  peers. The signaling server only introduces peers to each other; no game or
  chat data ever passes through it.
- **Rooms**: host clicks *New game*, gets a 6-character code and a shareable
  `?join=CODE` link. First two arrivals are the players (host = White, second =
  Black); everyone after is a spectator. Spectators can chat and can spin up a
  new room, announced as a clickable link in chat.
- If the host disconnects, everyone is notified and the board freezes; a
  *Reconnect* button rejoins the same code once the host is back. Players who
  drop can reclaim their seat by rejoining with the same name.

## Signaling config

Everything lives in the single `SIGNALING` constant at the top of `app.js`.
The default points at the self-hosted PeerServer above. Notes:

- `config: { iceServers: [] }` means **no STUN/TURN at all** — pure P2P with
  zero third-party servers. This works on a LAN or between machines that can
  reach each other directly. To play across the internet through NATs, add
  your own STUN/TURN server, e.g.
  `config: { iceServers: [{ urls: 'stun:stun.example.com:3478' }] }`
  (self-hostable with [coturn](https://github.com/coturn/coturn)).
- To use the public PeerJS cloud instead, set `const SIGNALING = {};`.
- For fully offline use, also vendor the two CDN scripts in `index.html`
  (chess.js and peerjs) as local files.

## Security note

The signaling server only brokers connections — no game or chat data passes
through it. All traffic between peers travels over WebRTC data channels, which
are always DTLS-encrypted end to end.
