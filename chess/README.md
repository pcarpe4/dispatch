# P2P Chess

A lightweight browser-based peer-to-peer chess app with chat and spectators.
One HTML file, one JS file, one CSS file — no build step, no framework, no backend
(other than WebRTC signaling).

## Run

```
npx serve chess
```

(or `node chess/server.js`) — then open the printed URL.

## How it works

- **Rules**: [chess.js](https://github.com/jhlywa/chess.js) via CDN. Every peer
  re-validates every move before applying it.
- **Networking**: [PeerJS](https://peerjs.com) WebRTC data channels in a star
  topology — everyone connects to the host, who relays messages to all peers.
- **Rooms**: host clicks *New game*, gets a 6-character code and a shareable
  `?join=CODE` link. First two arrivals are the players (host = White, second =
  Black); everyone after is a spectator. Spectators can chat and can spin up a
  new room, announced as a clickable link in chat.
- If the host disconnects, everyone is notified and the board freezes; a
  *Reconnect* button rejoins the same code once the host is back. Players who
  drop can reclaim their seat by rejoining with the same name.

## Self-hosting the signaling server

By default the app uses the free public PeerJS cloud for signaling. To use your
own [PeerServer](https://github.com/peers/peerjs-server):

```
npx peer --port 9000 --path /
```

Then edit the single `SIGNALING` constant at the top of `app.js`:

```js
const SIGNALING = { host: 'your-server.example.com', port: 9000, path: '/', secure: true };
```

## Security note

The signaling server only brokers connections — no game or chat data passes
through it. All traffic between peers travels over WebRTC data channels, which
are always DTLS-encrypted end to end.
