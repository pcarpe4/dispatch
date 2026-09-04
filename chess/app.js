'use strict';

/* ============================== CONFIG =====================================
 * SIGNALING is the only thing to change when self-hosting a PeerServer.
 * Empty object = PeerJS public cloud. For a self-hosted server use e.g.:
 *   const SIGNALING = { host: 'peers.example.com', port: 443, path: '/', secure: true };
 * Signaling only brokers the connection; game/chat data flows peer-to-peer
 * over WebRTC data channels, which are always DTLS-encrypted.
 * ========================================================================== */
const SIGNALING = {};
const ID_PREFIX = 'p2pchs-'; // namespaces our room codes on the public server

/* ------------------------------ State ------------------------------------ */
let peer = null;        // our PeerJS peer
let hostConn = null;    // guest: data connection to the host
let conns = [];         // host: open connections to all guests
let isHost = false;
let myName = '';
let myRole = 'spectator';        // 'white' | 'black' | 'spectator'
let roomCode = '';
let game = new Chess();
let moveHistory = [];            // verbose chess.js move objects
let roster = [];                 // [{id, name, role, connected}]
let gameOver = null;             // result string once the game ends
let frozen = false;              // true when the host is gone
let lastMove = null;             // {from, to}
let selected = null, legalTargets = [];
let drawOfferedBy = null;        // 'white' | 'black'
let rematchVotes = {};           // {white: true, black: true}
let pendingPromo = null;         // {from, to} awaiting promotion choice

const GLYPH = { p: '♟', n: '♞', b: '♝', r: '♜', q: '♛', k: '♚' };
const $ = id => document.getElementById(id);
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const genCode = () => Array.from({ length: 6 }, () =>
  'abcdefghjkmnpqrstuvwxyz23456789'[Math.floor(Math.random() * 31)]).join('');

/* ============================ PEERJS NETWORKING ============================
 * Topology: star. The host's peer ID is ID_PREFIX + roomCode, so anyone with
 * the code can reach it. Guests get a random ID and open one reliable data
 * channel to the host. The host is the hub: every message a guest sends goes
 * to the host, which validates it and relays it to every OTHER peer. The
 * sender applies its own message locally, so everyone converges.
 * ========================================================================== */
function makePeer(id) {
  return new Peer(id, Object.assign({ debug: 1 }, SIGNALING));
}

function startHost(code, fixedCode) {
  roomCode = code;
  isHost = true;
  myRole = 'white';
  peer = makePeer(ID_PREFIX + roomCode);
  peer.on('open', () => {
    roster = [{ id: peer.id, name: myName, role: 'white', connected: true }];
    enterRoom();
  });
  peer.on('connection', conn => {
    conn.on('data', msg => hostOnData(conn, msg));
    conn.on('close', () => hostOnClose(conn));
    conns.push(conn);
  });
  peer.on('error', err => {
    if (err.type === 'unavailable-id' && !fixedCode) {
      peer.destroy();
      startHost(genCode(), false); // rare collision: just roll a new code
    } else {
      setupError(err.type === 'unavailable-id'
        ? 'That room code is already in use.' : 'Connection error: ' + err.type);
    }
  });
  peer.on('disconnected', () => peer.reconnect()); // keep signaling alive for late joiners
}

function joinRoom(code) {
  roomCode = code;
  isHost = false;
  peer = makePeer(null);
  peer.on('open', () => {
    hostConn = peer.connect(ID_PREFIX + code, { reliable: true });
    hostConn.on('open', () => hostConn.send({ type: 'hello', name: myName }));
    hostConn.on('data', msg => handleFromHost(msg));
    hostConn.on('close', hostGone);
  });
  peer.on('error', err => {
    if (err.type === 'peer-unavailable') setupError('Room not found. Check the code.');
    else if (!frozen) setupError('Connection error: ' + err.type);
  });
  peer.on('disconnected', () => peer.reconnect());
}

/* Send a message out: host broadcasts to everyone, guest sends to the host
 * (who relays it onward). Callers apply the message locally themselves. */
function netSend(msg) {
  if (isHost) broadcast(msg, null);
  else if (hostConn && hostConn.open) hostConn.send(msg);
}

function broadcast(msg, exceptConn) {
  conns.forEach(c => { if (c.open && c !== exceptConn) c.send(msg); });
}

/* ========================== MESSAGE PROTOCOL ===============================
 * hello      {name}                          guest -> host, once, on connect
 * welcome    {code, role, roster, moves,     host -> new guest: full state
 *             gameOver, drawOfferedBy, rematchVotes}
 * roster     {roster}                        host -> all: participant list
 * sys        {text}                          host -> all: system chat line
 * move       {from, to, promotion}           player move; every receiver
 *                                            RE-VALIDATES with chess.js
 * chat       {name, text, ts}                chat line
 * resign     {role, name}
 * drawOffer  {role} / drawAccept {role}
 * rematch    {role}                          when both players vote, everyone
 *                                            deterministically resets + swaps
 * newRoom    {code, name}                    spectator opened a new room
 * ========================================================================== */

/* Host: validate incoming guest messages, apply locally, relay to the rest. */
function hostOnData(conn, msg) {
  const entry = roster.find(p => p.id === conn.peer);
  const role = entry ? entry.role : null;
  switch (msg.type) {
    case 'hello':
      return hostAddPeer(conn, String(msg.name || 'Anonymous').slice(0, 24));
    case 'move':
      // only the player whose turn it is may move, and the move must be legal
      if (role !== (game.turn() === 'w' ? 'white' : 'black') || gameOver) return;
      if (!applyMove(msg)) return;
      break;
    case 'chat':
      if (!entry) return;
      applyChat({ type: 'chat', name: entry.name, text: String(msg.text).slice(0, 500), ts: msg.ts });
      break;
    case 'resign':
      if (role !== 'white' && role !== 'black') return;
      applyResign(role, entry.name);
      msg = { type: 'resign', role, name: entry.name };
      break;
    case 'drawOffer':
      if (role !== 'white' && role !== 'black') return;
      applyDrawOffer(role); msg = { type: 'drawOffer', role };
      break;
    case 'drawAccept':
      if (!drawOfferedBy || role === drawOfferedBy || (role !== 'white' && role !== 'black')) return;
      applyDrawAccept(); msg = { type: 'drawAccept', role };
      break;
    case 'rematch':
      if (role !== 'white' && role !== 'black') return;
      applyRematchVote(role); msg = { type: 'rematch', role };
      break;
    case 'newRoom':
      if (!entry) return;
      applyNewRoom({ code: String(msg.code).slice(0, 8), name: entry.name });
      break;
    default:
      return;
  }
  broadcast(msg, conn);
  renderAll();
}

/* Host: seat assignment. First joiner becomes Black, everyone after is a
 * spectator. A player who dropped can reclaim their seat by rejoining with
 * the same name; an abandoned seat is eventually given to a fresh joiner. */
function hostAddPeer(conn, name) {
  let role = 'spectator';
  const old = roster.find(p => !p.connected && p.name === name && p.role !== 'spectator');
  const black = roster.find(p => p.role === 'black');
  if (old) { role = old.role; roster.splice(roster.indexOf(old), 1); }
  else if (black && !black.connected) { role = 'black'; roster.splice(roster.indexOf(black), 1); }
  else if (!black) { role = 'black'; }
  roster.push({ id: conn.peer, name, role, connected: true });
  conn.send({
    type: 'welcome', code: roomCode, role, roster,
    moves: moveHistory.map(m => ({ type: 'move', from: m.from, to: m.to, promotion: m.promotion })),
    gameOver, drawOfferedBy, rematchVotes
  });
  broadcast({ type: 'roster', roster }, conn);
  const text = name + ' joined as ' + cap(role);
  applySys(text);
  broadcast({ type: 'sys', text }, conn);
  renderAll();
}

function hostOnClose(conn) {
  conns = conns.filter(c => c !== conn);
  const entry = roster.find(p => p.id === conn.peer);
  if (!entry) return;
  entry.connected = false;
  const text = entry.name + ' (' + cap(entry.role) + ') disconnected';
  applySys(text);
  broadcast({ type: 'sys', text }, null);
  broadcast({ type: 'roster', roster }, null);
  renderAll();
}

/* Guest: everything arrives pre-vetted from the host, but moves are still
 * re-validated locally by chess.js inside applyMove(). */
function handleFromHost(msg) {
  switch (msg.type) {
    case 'welcome':
      frozen = false;
      myRole = msg.role; roster = msg.roster;
      game = new Chess(); moveHistory = []; lastMove = null;
      msg.moves.forEach(applyMove);
      gameOver = msg.gameOver; drawOfferedBy = msg.drawOfferedBy;
      rematchVotes = msg.rematchVotes || {};
      enterRoom();
      return;
    case 'roster': {
      roster = msg.roster;
      const me = roster.find(p => p.id === peer.id);
      if (me) myRole = me.role; // host may have (re)assigned our seat
      break;
    }
    case 'sys': applySys(msg.text); break;
    case 'move': applyMove(msg); break;
    case 'chat': applyChat(msg); break;
    case 'resign': applyResign(msg.role, msg.name); break;
    case 'drawOffer': applyDrawOffer(msg.role); break;
    case 'drawAccept': applyDrawAccept(); break;
    case 'rematch': applyRematchVote(msg.role); break;
    case 'newRoom': applyNewRoom(msg); break;
  }
  renderAll();
}

function hostGone() {
  frozen = true;
  clearSel();
  applySys('Host disconnected — board frozen');
  renderAll();
}

/* --------------------------- Apply functions ------------------------------
 * Shared by host and guests so every peer converges on the same state. */
function applyMove(msg) {
  const m = game.move({ from: msg.from, to: msg.to, promotion: msg.promotion || 'q' });
  if (!m) return false; // illegal: reject (re-validation on every receiver)
  moveHistory.push(m);
  lastMove = { from: m.from, to: m.to };
  drawOfferedBy = null;
  if (game.in_checkmate()) gameOver = (game.turn() === 'w' ? 'Black' : 'White') + ' wins by checkmate';
  else if (game.in_stalemate()) gameOver = 'Draw by stalemate';
  else if (game.in_draw()) gameOver = 'Draw (repetition, 50-move rule, or insufficient material)';
  return true;
}

function applyResign(role, name) {
  gameOver = name + ' (' + cap(role) + ') resigned — ' + (role === 'white' ? 'Black' : 'White') + ' wins';
  applySys(gameOver);
}

function applyDrawOffer(role) {
  drawOfferedBy = role;
  applySys(cap(role) + ' offers a draw');
}

function applyDrawAccept() {
  gameOver = 'Draw by agreement';
  applySys(gameOver);
}

function applyRematchVote(role) {
  rematchVotes[role] = true;
  applySys(cap(role) + ' wants a rematch (colors will swap)');
  if (rematchVotes.white && rematchVotes.black) {
    game = new Chess();
    moveHistory = []; gameOver = null; drawOfferedBy = null;
    rematchVotes = {}; lastMove = null; clearSel();
    roster.forEach(p => {
      if (p.role === 'white') p.role = 'black';
      else if (p.role === 'black') p.role = 'white';
    });
    if (myRole === 'white') myRole = 'black';
    else if (myRole === 'black') myRole = 'white';
    buildBoard();
    applySys('Rematch! New game started — colors swapped');
  }
}

function applyNewRoom(msg) {
  const div = document.createElement('div');
  div.className = 'msg sys';
  div.textContent = msg.name + ' started a new room: ';
  const a = document.createElement('a');
  a.href = location.pathname + '?join=' + encodeURIComponent(msg.code);
  a.target = '_blank';
  a.textContent = 'join ' + msg.code;
  div.appendChild(a);
  appendChat(div);
}

function applyChat(msg) {
  const div = document.createElement('div');
  div.className = 'msg';
  const meta = document.createElement('span');
  meta.className = 'meta';
  meta.textContent = msg.name + ' · ' + new Date(msg.ts || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const body = document.createElement('span');
  body.textContent = msg.text;
  div.append(meta, body);
  appendChat(div);
}

function applySys(text) {
  const div = document.createElement('div');
  div.className = 'msg sys';
  div.textContent = text;
  appendChat(div);
}

function appendChat(div) {
  const log = $('chatLog');
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

/* ------------------------------ Board UI --------------------------------- */
function buildBoard() {
  const el = $('board');
  el.innerHTML = '';
  const files = 'abcdefgh';
  const flip = myRole === 'black';
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const sq = document.createElement('div');
      sq.className = 'square ' + ((r + c) % 2 ? 'dark' : 'light');
      sq.dataset.square = files[flip ? 7 - c : c] + (flip ? r + 1 : 8 - r);
      sq.addEventListener('click', onSquareClick);
      sq.addEventListener('dragover', e => e.preventDefault());
      sq.addEventListener('drop', onDrop);
      el.appendChild(sq);
    }
  }
}

function renderBoard() {
  let checkSq = null;
  if (game.in_check()) {
    game.board().forEach((row, r) => row.forEach((p, c) => {
      if (p && p.type === 'k' && p.color === game.turn())
        checkSq = 'abcdefgh'[c] + (8 - r);
    }));
  }
  document.querySelectorAll('#board .square').forEach(sq => {
    const name = sq.dataset.square;
    sq.innerHTML = '';
    sq.classList.toggle('sel', name === selected);
    sq.classList.toggle('last', !!lastMove && (name === lastMove.from || name === lastMove.to));
    sq.classList.toggle('check', name === checkSq);
    const p = game.get(name);
    if (p) {
      const span = document.createElement('span');
      span.className = 'piece ' + p.color;
      span.textContent = GLYPH[p.type];
      if (canMovePiece(p)) {
        span.draggable = true;
        span.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', name);
          selectSquare(name);
        });
      }
      sq.appendChild(span);
    }
    if (legalTargets.includes(name)) {
      const dot = document.createElement('span');
      dot.className = p ? 'ring' : 'dot';
      sq.appendChild(dot);
    }
  });
}

function canMovePiece(p) {
  return !frozen && !gameOver && (myRole === 'white' || myRole === 'black') &&
    p.color === (myRole === 'white' ? 'w' : 'b') && game.turn() === p.color;
}

function selectSquare(name) {
  selected = name;
  legalTargets = game.moves({ square: name, verbose: true }).map(m => m.to);
}

function clearSel() { selected = null; legalTargets = []; }

function onSquareClick(e) {
  const name = e.currentTarget.dataset.square;
  if (selected && legalTargets.includes(name)) { tryMove(selected, name); return; }
  const p = game.get(name);
  if (p && canMovePiece(p) && name !== selected) selectSquare(name);
  else clearSel();
  renderBoard();
}

function onDrop(e) {
  e.preventDefault();
  const from = e.dataTransfer.getData('text/plain');
  const to = e.currentTarget.dataset.square;
  if (from && legalTargets.includes(to)) tryMove(from, to);
  else { clearSel(); renderBoard(); }
}

function tryMove(from, to) {
  clearSel();
  renderBoard();
  const p = game.get(from);
  if (p && p.type === 'p' && (to[1] === '8' || to[1] === '1')) {
    pendingPromo = { from, to };
    $('promo').hidden = false;
    return;
  }
  doMove(from, to, undefined);
}

function doMove(from, to, promotion) {
  const msg = { type: 'move', from, to, promotion };
  if (!applyMove(msg)) { renderBoard(); return; }
  netSend(msg);
  renderAll();
}

/* ------------------------------ Side panels ------------------------------ */
function renderAll() {
  renderBoard();
  renderStatus();
  renderCaptured();
  renderRoster();
  renderMoves();
  renderButtons();
}

function renderStatus() {
  let text;
  if (frozen) text = '⚠ Host disconnected — game frozen';
  else if (gameOver) text = '🏁 ' + gameOver;
  else {
    text = (game.turn() === 'w' ? 'White' : 'Black') + ' to move';
    if (game.in_check()) text += ' — check!';
    if (myRole !== 'spectator') {
      text += (game.turn() === (myRole === 'white' ? 'w' : 'b')) ? ' (your turn)' : '';
    }
  }
  $('statusBar').textContent = text;
  const b = $('banner');
  b.hidden = !frozen;
  if (frozen) {
    $('bannerText').textContent = 'The host has disconnected. The board is frozen.';
    $('btnReconnect').hidden = false;
  }
}

function renderCaptured() {
  const byWhite = [], byBlack = [];
  moveHistory.forEach(m => {
    if (m.captured) (m.color === 'w' ? byWhite : byBlack).push(GLYPH[m.captured]);
  });
  const flip = myRole === 'black';
  // opponent's captures on top, mine at the bottom
  $('capturedTop').textContent = (flip ? byWhite : byBlack).join(' ');
  $('capturedBottom').textContent = (flip ? byBlack : byWhite).join(' ');
}

function renderRoster() {
  const ul = $('participants');
  ul.innerHTML = '';
  const order = { white: 0, black: 1, spectator: 2 };
  [...roster].sort((a, b) => order[a.role] - order[b.role]).forEach(p => {
    const li = document.createElement('li');
    const dot = document.createElement('span');
    dot.className = 'dot-conn ' + (p.connected ? 'on' : 'off');
    dot.title = p.connected ? 'Connected' : 'Disconnected';
    const name = document.createElement('span');
    name.textContent = p.name + (peer && p.id === peer.id ? ' (you)' : '');
    const chip = document.createElement('span');
    chip.className = 'chip ' + p.role;
    chip.textContent = cap(p.role);
    li.append(dot, name, chip);
    ul.appendChild(li);
  });
}

function renderMoves() {
  const el = $('moveList');
  el.innerHTML = '';
  for (let i = 0; i < moveHistory.length; i += 2) {
    const row = document.createElement('div');
    row.textContent = (i / 2 + 1) + '. ' + moveHistory[i].san +
      (moveHistory[i + 1] ? '  ' + moveHistory[i + 1].san : '');
    el.appendChild(row);
  }
  el.scrollTop = el.scrollHeight;
}

function renderButtons() {
  const player = myRole === 'white' || myRole === 'black';
  $('btnResign').hidden = !player || !!gameOver || frozen;
  $('btnDraw').hidden = !player || !!gameOver || frozen;
  $('btnDraw').textContent =
    (drawOfferedBy && drawOfferedBy !== myRole) ? 'Accept draw' : 'Offer draw';
  $('btnRematch').hidden = !player || !gameOver || frozen;
  $('btnRematch').disabled = !!rematchVotes[myRole];
  $('btnNewRoom').hidden = myRole !== 'spectator';
}

/* ------------------------------ Setup flow ------------------------------- */
function setupError(text) {
  if (!$('app').hidden) { // already in a room (e.g. failed reconnect)
    $('bannerText').textContent = text;
    $('banner').hidden = false;
    return;
  }
  const el = $('setupError');
  el.textContent = text;
  el.hidden = false;
  $('setup').style.display = '';
}

function enterRoom() {
  $('setup').style.display = 'none';
  $('app').hidden = false;
  $('roomLabel').textContent = roomCode;
  buildBoard();
  if (isHost) applySys('Room ' + roomCode + ' created. Share the link to invite players.');
  renderAll();
}

function begin(mode, code) {
  myName = $('nameInput').value.trim().slice(0, 24);
  if (!myName) { setupError('Please enter a name.'); return; }
  try { localStorage.setItem('p2pchess-name', myName); } catch (e) { /* ignore */ }
  $('setupError').hidden = true;
  if (mode === 'host') startHost(code || genCode(), !!code);
  else joinRoom(code);
}

function init() {
  const params = new URLSearchParams(location.search);
  const join = (params.get('join') || '').toLowerCase();
  const host = (params.get('host') || '').toLowerCase();
  try { $('nameInput').value = localStorage.getItem('p2pchess-name') || ''; } catch (e) { /* ignore */ }
  try {
    const t = localStorage.getItem('p2pchess-theme');
    if (t) document.documentElement.dataset.theme = t;
  } catch (e) { /* ignore */ }

  if (join) { $('hostRow').hidden = true; $('codeInput').value = join; }
  if (host) { $('joinRow').hidden = true; }

  $('btnNew').onclick = () => begin('host', host || null);
  $('btnJoin').onclick = () => {
    const code = $('codeInput').value.trim().toLowerCase();
    if (!code) { setupError('Please enter a room code.'); return; }
    begin('join', code);
  };
  $('nameInput').onkeydown = e => {
    if (e.key !== 'Enter') return;
    const joining = !$('joinRow').hidden && $('codeInput').value.trim();
    (joining ? $('btnJoin') : $('btnNew')).click();
  };

  $('btnCopy').onclick = () => {
    const url = location.origin + location.pathname + '?join=' + roomCode;
    navigator.clipboard.writeText(url).then(() => applySys('Invite link copied: ' + url));
  };
  $('btnTheme').onclick = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('p2pchess-theme', next); } catch (e) { /* ignore */ }
  };

  $('btnResign').onclick = () => {
    if (!confirm('Resign the game?')) return;
    applyResign(myRole, myName);
    netSend({ type: 'resign', role: myRole, name: myName });
    renderAll();
  };
  $('btnDraw').onclick = () => {
    if (drawOfferedBy && drawOfferedBy !== myRole) {
      applyDrawAccept();
      netSend({ type: 'drawAccept', role: myRole });
    } else if (drawOfferedBy !== myRole) {
      applyDrawOffer(myRole);
      netSend({ type: 'drawOffer', role: myRole });
    }
    renderAll();
  };
  $('btnRematch').onclick = () => {
    applyRematchVote(myRole);
    netSend({ type: 'rematch', role: myRole });
    renderAll();
  };
  $('btnNewRoom').onclick = () => {
    // Spectator spins up a second room: announce a clickable link in chat,
    // then open a new tab where they become the host of that room.
    const code = genCode();
    const msg = { type: 'newRoom', code, name: myName };
    applyNewRoom(msg);
    netSend(msg);
    window.open(location.pathname + '?host=' + code, '_blank');
  };
  $('btnReconnect').onclick = () => {
    // Rejoin the same room code (works once the host is back).
    if (peer) peer.destroy();
    conns = []; hostConn = null;
    $('bannerText').textContent = 'Reconnecting…';
    joinRoom(roomCode);
  };

  const sendChat = () => {
    const text = $('chatInput').value.trim();
    if (!text) return;
    $('chatInput').value = '';
    const msg = { type: 'chat', name: myName, text, ts: Date.now() };
    applyChat(msg);
    netSend(msg);
  };
  $('chatSend').onclick = sendChat;
  $('chatInput').onkeydown = e => { if (e.key === 'Enter') sendChat(); };

  document.querySelectorAll('#promo button').forEach(b => b.onclick = () => {
    $('promo').hidden = true;
    if (pendingPromo) doMove(pendingPromo.from, pendingPromo.to, b.dataset.p);
    pendingPromo = null;
  });

  window.addEventListener('beforeunload', () => { if (peer) peer.destroy(); });
}

init();
