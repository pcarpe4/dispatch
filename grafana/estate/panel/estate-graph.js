/*
 * Estate topology - the onRender script of the "Topology" HTML Graphics panel.
 *
 * Grafana runs this every time the panel gets new data (and on resize). It receives the
 * frames of the source panel through the "-- Dashboard --" data source:
 *   nodes frame: id, type, name, ...any attributes       (one row per object)
 *   edges frame: id, source, target, relation            (one row per relationship)
 * and draws them as a layered graph: containers at the top, the things they contain below.
 *
 * Available globals (from the plugin): htmlNode (the panel's shadow root), data, theme,
 * htmlGraphics (theme2, locationService, width, height, ...), getTemplateSrv, getLocationSrv.
 * No external libraries, no template literals (so nothing here looks like a Grafana variable).
 */
(function () {
  'use strict';

  var rootEl = htmlNode.getElementById('estate');
  if (!rootEl) { return; }

  // State that must survive re-renders (zoom, selection, hidden types) lives on the shadow root.
  var S = htmlNode.__estate;
  if (!S) { S = htmlNode.__estate = { hidden: {}, selected: null, search: '', view: null, sig: '', bound: false }; }

  // ---------------------------------------------------------------- theme
  var hg = (typeof htmlGraphics !== 'undefined' && htmlGraphics) ? htmlGraphics : {};
  var t2 = hg.theme2 || null;
  var dark = t2 ? !!t2.isDark : !!(theme && theme.isDark);
  var vars = t2 ? {
    '--ink': t2.colors.text.primary, '--ink-2': t2.colors.text.secondary, '--muted': t2.colors.text.disabled,
    '--line': t2.colors.border.medium, '--grid': t2.colors.border.weak,
    '--surface': t2.colors.background.primary, '--surface-2': t2.colors.background.secondary,
    '--accent': t2.colors.primary.text
  } : (dark ? {
    '--ink': '#f0efec', '--ink-2': '#c3c2b7', '--muted': '#898781', '--line': '#383835', '--grid': '#2c2c2a',
    '--surface': '#181b1f', '--surface-2': '#22252b', '--accent': '#3987e5'
  } : {
    '--ink': '#0b0b0b', '--ink-2': '#52514e', '--muted': '#898781', '--line': '#c3c2b7', '--grid': '#e1e0d9',
    '--surface': '#ffffff', '--surface-2': '#f4f5f5', '--accent': '#2a78d6'
  });
  Object.keys(vars).forEach(function (k) { rootEl.style.setProperty(k, vars[k]); });
  rootEl.classList.toggle('dark', dark);
  rootEl.classList.toggle('narrow', (hg.width || rootEl.clientWidth || 1000) < 640);

  // Families group the many object types onto six categorical colours (fixed order, stepped per mode).
  // The type name is always printed on the node, so colour is a redundant cue, never the only one.
  var FAMILY = {
    datacenter: 'site', zone: 'site',
    subnet: 'network', firewall: 'network',
    hardware_group: 'hardware', esxi_host: 'hardware', baremetal_host: 'hardware',
    vsphere_cluster: 'virtualization', vm: 'virtualization',
    ocp_cluster: 'openshift', ocp_node: 'openshift',
    namespace: 'workload', pod: 'workload'
  };
  var FAMILY_ORDER = ['site', 'network', 'hardware', 'virtualization', 'openshift', 'workload', 'other'];
  var SLOTS = dark
    ? ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9']
    : ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6'];
  var TYPE_RANK = ['datacenter', 'zone', 'firewall', 'hardware_group', 'subnet', 'vsphere_cluster', 'esxi_host',
    'baremetal_host', 'vm', 'ocp_cluster', 'ocp_node', 'namespace', 'pod'];
  function familyOf(type) { return FAMILY[type] || 'other'; }
  function colorOf(type) { return SLOTS[FAMILY_ORDER.indexOf(familyOf(type))]; }
  function rankOf(type) { var i = TYPE_RANK.indexOf(type); return i < 0 ? TYPE_RANK.length : i; }

  // ---------------------------------------------------------------- frames -> rows
  function fieldValues(f) {
    var v = f.values;
    if (!v) { return []; }
    if (typeof v.toArray === 'function') { return v.toArray(); }
    return Array.prototype.slice.call(v);
  }
  function frameRows(frame) {
    var cols = frame.fields.map(function (f) { return { name: f.name, vals: fieldValues(f) }; });
    var n = typeof frame.length === 'number' ? frame.length : (cols[0] ? cols[0].vals.length : 0);
    var rows = [];
    for (var i = 0; i < n; i++) {
      var r = {};
      for (var c = 0; c < cols.length; c++) { r[cols[c].name] = cols[c].vals[i]; }
      rows.push(r);
    }
    return rows;
  }
  var nodeRows = [], edgeRows = [];
  ((data && data.series) || []).forEach(function (frame) {
    var names = frame.fields.map(function (f) { return f.name; });
    if (names.indexOf('source') >= 0 && names.indexOf('target') >= 0) { edgeRows = edgeRows.concat(frameRows(frame)); }
    else if (names.indexOf('id') >= 0) { nodeRows = nodeRows.concat(frameRows(frame)); }
  });

  var all = {};
  nodeRows.forEach(function (r) { if (r.id !== null && r.id !== undefined) { all[String(r.id)] = r; } });
  var allEdges = edgeRows.filter(function (e) { return all[e.source] && all[e.target]; });
  var allIds = Object.keys(all);

  var rootId = '';
  try { rootId = getTemplateSrv().replace('$root'); } catch (err) { rootId = ''; }
  if (rootId === '$root') { rootId = ''; }

  // ---------------------------------------------------------------- hidden types -> contracted graph
  function contract(edgesIn, nodes, visible) {
    var cur = edgesIn.map(function (e) { return { id: e.id, source: e.source, target: e.target, relation: e.relation, via: false }; });
    Object.keys(nodes).forEach(function (h) {
      if (visible[h]) { return; }
      var ins = [], outs = [], rest = [];
      cur.forEach(function (e) {
        if (e.target === h) { ins.push(e); }
        else if (e.source === h) { outs.push(e); }
        else { rest.push(e); }
      });
      ins.forEach(function (a) {
        outs.forEach(function (b) {
          if (a.source === b.target) { return; }
          rest.push({ id: 'via:' + a.source + '>' + h + '>' + b.target, source: a.source, target: b.target, relation: 'via ' + nodes[h].type, via: true });
        });
      });
      cur = rest;
    });
    var seen = {};
    return cur.filter(function (e) {
      var k = e.source + '>' + e.target;
      if (seen[k] || !visible[e.source] || !visible[e.target]) { return false; }
      seen[k] = true;
      return true;
    });
  }

  // ---------------------------------------------------------------- layout (layered DAG)
  var measureCtx = null;
  function textWidth(s, px, bold) {
    try {
      if (!measureCtx) { measureCtx = document.createElement('canvas').getContext('2d'); }
      measureCtx.font = (bold ? '600 ' : '') + px + 'px Inter, system-ui, sans-serif';
      return measureCtx.measureText(s).width;
    } catch (err) { return s.length * px * 0.6; }
  }
  function layout(ids, edges) {
    var out = {}, inc = {};
    ids.forEach(function (id) { out[id] = []; inc[id] = []; });
    edges.forEach(function (e) { out[e.source].push(e.target); inc[e.target].push(e.source); });

    // Depth-first search gives a topological order and finds back edges (which break cycles).
    var state = {}, order = [], back = {};
    ids.forEach(function (start) {
      if (state[start]) { return; }
      var stack = [[start, 0]];
      state[start] = 1;
      while (stack.length) {
        var top = stack[stack.length - 1], u = top[0];
        if (top[1] < out[u].length) {
          var v = out[u][top[1]++];
          if (!state[v]) { state[v] = 1; stack.push([v, 0]); }
          else if (state[v] === 1) { back[u + '>' + v] = true; }
        } else { state[u] = 2; order.push(u); stack.pop(); }
      }
    });
    order.reverse();
    var rank = {};
    ids.forEach(function (id) { rank[id] = 0; });
    order.forEach(function (u) {
      out[u].forEach(function (v) { if (!back[u + '>' + v]) { rank[v] = Math.max(rank[v], rank[u] + 1); } });
    });
    var layers = [];
    ids.forEach(function (id) { (layers[rank[id]] = layers[rank[id]] || []).push(id); });
    for (var r = 0; r < layers.length; r++) { if (!layers[r]) { layers[r] = []; } }

    // Initial order by type then name; then barycenter sweeps to reduce crossings.
    var pos = {};
    function byTypeName(a, b) {
      return rankOf(all[a].type) - rankOf(all[b].type) || String(all[a].name).localeCompare(String(all[b].name));
    }
    layers.forEach(function (L) { L.sort(byTypeName); L.forEach(function (id, i) { pos[id] = i; }); });
    for (var sweep = 0; sweep < 6; sweep++) {
      var down = sweep % 2 === 0;
      for (var li = down ? 1 : layers.length - 2; down ? li < layers.length : li >= 0; li += down ? 1 : -1) {
        var L = layers[li], bary = {};
        L.forEach(function (id) {
          var nb = (down ? inc[id] : out[id]).filter(function (x) { return rank[x] === (down ? li - 1 : li + 1); });
          var sum = 0;
          nb.forEach(function (x) { sum += pos[x]; });
          bary[id] = nb.length ? sum / nb.length : pos[id];
        });
        L.sort(function (a, b) { return bary[a] - bary[b] || byTypeName(a, b); });
        L.forEach(function (id, i) { pos[id] = i; });
      }
    }

    // Coordinates. A layer wider than MAXW is folded into interleaved sub-rows so the
    // picture stays roughly as wide as it is tall (and the fit-to-panel zoom stays readable).
    var GAP = 16, H = 46, VGAP = 50, SUBGAP = 10, MAXW = 1400, coords = {}, y = 0;
    layers.forEach(function (L) {
      var widths = L.map(function (id) {
        var n = all[id];
        return Math.max(110, Math.min(240, Math.max(textWidth(String(n.name), 12, true), textWidth(String(n.type), 10)) + 30));
      });
      var total = widths.reduce(function (s, w) { return s + w; }, 0) + GAP * Math.max(0, L.length - 1);
      var rows = Math.max(1, Math.ceil(total / MAXW)), rowX = [], k;
      for (k = 0; k < rows; k++) { rowX.push(0); }
      L.forEach(function (id, i) { rowX[i % rows] += widths[i] + GAP; });
      for (k = 0; k < rows; k++) { rowX[k] = -(rowX[k] - GAP) / 2; }
      L.forEach(function (id, i) {
        k = i % rows;
        coords[id] = { x: rowX[k] + widths[i] / 2, y: y + k * (H + SUBGAP), w: widths[i], h: H };
        rowX[k] += widths[i] + GAP;
      });
      y += rows * (H + SUBGAP) - SUBGAP + VGAP;
    });
    return coords;
  }

  // ---------------------------------------------------------------- rendering
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) { parent.appendChild(e); }
    return e;
  }
  function h(tag, cls, text, parent) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    if (parent) { parent.appendChild(e); }
    return e;
  }
  function edgePath(a, b) {
    var x1 = a.x, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y - b.h / 2;
    if (y2 > y1) {
      var my = (y2 - y1) / 2;
      return 'M' + x1 + ',' + y1 + ' C' + x1 + ',' + (y1 + my) + ' ' + x2 + ',' + (y2 - my) + ' ' + x2 + ',' + y2;
    }
    // Backward or same-row edge: loop out to the side.
    var sx = a.x + a.w / 2, tx = b.x + b.w / 2, dx = 48;
    return 'M' + sx + ',' + a.y + ' C' + (sx + dx) + ',' + a.y + ' ' + (tx + dx) + ',' + b.y + ' ' + tx + ',' + b.y;
  }
  function fmt(v) {
    if (v === null || v === undefined || v === '') { return ''; }
    if (typeof v === 'number') { return Number.isInteger(v) ? String(v) : v.toFixed(1); }
    return String(v);
  }
  function matches(n, q) {
    if (!q) { return true; }
    return String(n.name).toLowerCase().indexOf(q) >= 0 || String(n.id).toLowerCase().indexOf(q) >= 0 || String(n.type).toLowerCase().indexOf(q) >= 0;
  }

  var svg = htmlNode.getElementById('estate-svg');
  var view = htmlNode.getElementById('estate-view');
  var side = htmlNode.getElementById('estate-side');
  var legend = htmlNode.getElementById('estate-legend');
  var emptyMsg = htmlNode.getElementById('estate-empty');
  var crumb = htmlNode.getElementById('estate-root');
  var countEl = htmlNode.getElementById('estate-count');
  var searchEl = htmlNode.getElementById('estate-search');

  function applyView() {
    var v = S.view || { k: 1, tx: 0, ty: 0 };
    view.setAttribute('transform', 'translate(' + v.tx + ',' + v.ty + ') scale(' + v.k + ')');
  }
  function fit(coords) {
    var ids = Object.keys(coords);
    if (!ids.length) { S.view = { k: 1, tx: 0, ty: 0 }; applyView(); return; }
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    ids.forEach(function (id) {
      var c = coords[id];
      minX = Math.min(minX, c.x - c.w / 2); maxX = Math.max(maxX, c.x + c.w / 2);
      minY = Math.min(minY, c.y - c.h / 2); maxY = Math.max(maxY, c.y + c.h / 2);
    });
    var cw = svg.clientWidth || (hg.width || 800) - 280, ch = svg.clientHeight || (hg.height || 500) - 70, pad = 24;
    var k = Math.min((cw - pad * 2) / Math.max(1, maxX - minX), (ch - pad * 2) / Math.max(1, maxY - minY), 1.4);
    S.view = { k: k, tx: cw / 2 - k * (minX + maxX) / 2, ty: ch / 2 - k * (minY + maxY) / 2 };
    applyView();
  }

  function setRoot(id) {
    if (hg.locationService && typeof hg.locationService.partial === 'function') { hg.locationService.partial({ 'var-root': id }, false); return; }
    if (typeof getLocationSrv === 'function') { getLocationSrv().update({ query: { 'var-root': id }, partial: true }); return; }
    var u = new URL(window.location.href);
    u.searchParams.set('var-root', id);
    window.location.href = u.toString();
  }

  function renderSide() {
    while (side.firstChild) { side.removeChild(side.firstChild); }
    var n = S.selected ? all[S.selected] : null;
    rootEl.classList.toggle('has-selection', !!n);
    if (!n) {
      h('div', 'hint', 'Click a node for its details and relations. Double-click (or "make root") to re-centre the whole dashboard on it. Scroll to zoom, drag to pan, click a legend chip to hide a type.', side);
      return;
    }
    h('h3', null, n.name, side);
    var pill = h('span', 'pill', null, side);
    var dot = h('i', null, null, pill);
    dot.style.background = colorOf(n.type);
    pill.appendChild(document.createTextNode(n.type + (n.id === rootId ? ' · current root' : '')));
    var actions = h('div', 'actions', null, side);
    var mk = h('button', null, 'make root', actions);
    mk.type = 'button';
    mk.title = 'Set the $root variable to this object; every panel re-queries';
    mk.addEventListener('click', function () { setRoot(n.id); });
    var tbl = h('table', null, null, side);
    // Node-Graph alias columns (title, subtitle, mainstat, detail__*) duplicate real attributes; skip them.
    var skip = { id: 1, type: 1, name: 1, title: 1, subtitle: 1, mainstat: 1, secondarystat: 1 };
    Object.keys(n).forEach(function (k) {
      if (skip[k] || k.indexOf('detail__') === 0 || n[k] === null || n[k] === undefined || n[k] === '') { return; }
      var tr = h('tr', null, null, tbl);
      h('td', null, k, tr);
      h('td', typeof n[k] === 'number' ? 'num' : null, fmt(n[k]), tr);
    });
    var tr = h('tr', null, null, tbl);
    h('td', null, 'id', tr);
    h('td', null, n.id, tr);
    var rels = allEdges.filter(function (e) { return e.source === n.id || e.target === n.id; });
    if (rels.length) {
      h('h4', null, 'relations (' + rels.length + ')', side);
      rels.sort(function (a, b) {
        var oa = a.source === n.id ? 1 : 0, ob = b.source === n.id ? 1 : 0;
        return oa - ob || a.relation.localeCompare(b.relation) || String(all[a.source === n.id ? a.target : a.source].name).localeCompare(String(all[b.source === n.id ? b.target : b.source].name));
      });
      rels.forEach(function (e) {
        var outgoing = e.source === n.id, other = all[outgoing ? e.target : e.source];
        var row = h('div', 'rel', null, side);
        h('span', 'arrow', outgoing ? '→' : '←', row);
        h('span', 'what', e.relation, row);
        var who = h('span', 'who' + (S.hidden[other.type] ? ' hidden-type' : ''), other.name + ' [' + other.type + ']', row);
        who.title = other.id;
        row.addEventListener('click', function () {
          if (S.hidden[other.type]) { delete S.hidden[other.type]; }
          S.selected = other.id;
          S.render();
        });
      });
    }
  }

  function render() {
    var visible = {};
    allIds.forEach(function (id) { if (!S.hidden[all[id].type]) { visible[id] = all[id]; } });
    var ids = Object.keys(visible);
    var edges = contract(allEdges, all, visible);
    var coords = layout(ids, edges);

    // Header
    while (crumb.firstChild) { crumb.removeChild(crumb.firstChild); }
    var rootNode = rootId && all[rootId];
    crumb.appendChild(document.createTextNode(rootNode ? rootNode.name : (rootId || 'whole estate')));
    if (rootNode) { h('span', 'dim', ' [' + rootNode.type + ']', crumb); }
    countEl.textContent = ids.length + ' of ' + allIds.length + ' objects · ' + edges.length + ' relations';
    emptyMsg.hidden = allIds.length > 0;

    // Graph
    while (view.firstChild) { view.removeChild(view.firstChild); }
    S.els = { nodes: {}, edges: [] };
    var edgeLayer = el('g', { 'class': 'edges' }, view), nodeLayer = el('g', { 'class': 'nodes' }, view);
    edges.forEach(function (e) {
      var p = el('path', { d: edgePath(coords[e.source], coords[e.target]), 'class': 'edge' + (e.via ? ' via' : '') }, edgeLayer);
      el('title', {}, p).textContent = all[e.source].name + ' ' + e.relation + ' ' + all[e.target].name;
      S.els.edges.push({ el: p, source: e.source, target: e.target });
    });
    ids.forEach(function (id) {
      var n = visible[id], c = coords[id];
      var g = el('g', { 'class': 'node' + (id === rootId ? ' root' : ''), transform: 'translate(' + (c.x - c.w / 2) + ',' + (c.y - c.h / 2) + ')', 'data-id': id }, nodeLayer);
      var color = colorOf(n.type);
      var box = el('rect', { 'class': 'box', width: c.w, height: c.h, rx: 6 }, g);
      el('rect', { 'class': 'bar', x: 0, y: 0, width: 5, height: c.h, rx: 2, fill: color }, g);
      var label = String(n.name), maxW = c.w - 20;
      while (label.length > 3 && textWidth(label, 12, true) > maxW) { label = label.slice(0, -2) + '…'; }
      el('text', { x: 12, y: 19 }, g).textContent = label;
      el('text', { 'class': 'type', x: 12, y: 33 }, g).textContent = n.type + (n.status ? ' · ' + n.status : '');
      var pct = n.cpu_used_pct;
      if (typeof pct === 'number' && !isNaN(pct)) {
        el('rect', { 'class': 'meter-track', x: 12, y: c.h - 7, width: c.w - 20, height: 3, rx: 1.5 }, g);
        el('rect', { 'class': 'meter', x: 12, y: c.h - 7, width: Math.max(0, Math.min(1, pct / 100)) * (c.w - 20), height: 3, rx: 1.5 }, g);
      }
      var tip = n.name + ' [' + n.type + ']';
      ['os', 'version', 'status', 'ip', 'cidr', 'cpu_cores', 'mem_gb', 'cpu_used_pct', 'mem_used_pct', 'node_count', 'pod_count', 'vm_count'].forEach(function (k) {
        if (n[k] !== null && n[k] !== undefined && n[k] !== '') { tip += '\n' + k + ': ' + fmt(n[k]); }
      });
      el('title', {}, g).textContent = tip;
      S.els.nodes[id] = { el: g, box: box, color: color, node: n };
    });

    // Legend: one chip per type present, with its count; click to hide/show the type.
    while (legend.firstChild) { legend.removeChild(legend.firstChild); }
    var counts = {};
    allIds.forEach(function (id) { counts[all[id].type] = (counts[all[id].type] || 0) + 1; });
    Object.keys(counts).sort(function (a, b) { return rankOf(a) - rankOf(b) || a.localeCompare(b); }).forEach(function (type) {
      var chip = h('span', 'chip' + (S.hidden[type] ? ' off' : ''), null, legend);
      var sw = h('i', null, null, chip);
      sw.style.background = colorOf(type);
      chip.appendChild(document.createTextNode(type + ' '));
      h('b', null, counts[type], chip);
      chip.title = (S.hidden[type] ? 'show ' : 'hide ') + type;
      chip.addEventListener('click', function () {
        if (S.hidden[type]) { delete S.hidden[type]; } else { S.hidden[type] = true; }
        S.render();
      });
    });

    applyState();

    var sig = ids.join('|');
    if (!S.view || sig !== S.sig) { S.sig = sig; fit(coords); } else { applyView(); }
    S.coords = coords;
  }
  // Selection, neighbour highlighting and search are class toggles on the existing elements.
  // Rebuilding the SVG on every click would swap the element under the pointer and break double-click.
  function applyState() {
    var q = (S.search || '').trim().toLowerCase();
    var els = S.els || { nodes: {}, edges: [] };
    var sel = S.selected && els.nodes[S.selected] ? S.selected : null;
    var neighbours = {};
    if (sel) {
      neighbours[sel] = true;
      els.edges.forEach(function (e) { if (e.source === sel) { neighbours[e.target] = true; } if (e.target === sel) { neighbours[e.source] = true; } });
    }
    els.edges.forEach(function (e) {
      var touches = !!sel && (e.source === sel || e.target === sel);
      e.el.classList.toggle('hl', touches);
      e.el.classList.toggle('dim', !!sel && !touches);
    });
    Object.keys(els.nodes).forEach(function (id) {
      var x = els.nodes[id], isSel = id === sel, hit = !!q && matches(x.node, q);
      x.el.classList.toggle('selected', isSel);
      x.el.classList.toggle('dim', !!sel && !isSel && !neighbours[id]);
      x.el.classList.toggle('hit', hit);
      x.el.classList.toggle('hidden-by-search', !!q && !hit);
      x.box.style.stroke = (isSel || id === rootId) ? x.color : '';
    });
    renderSide();
  }
  S.render = render;
  S.applyState = applyState;

  // ---------------------------------------------------------------- interactions (bound once per shadow root)
  if (!S.bound) {
    S.bound = true;
    var drag = null;
    svg.addEventListener('wheel', function (ev) {
      ev.preventDefault();
      var v = S.view || { k: 1, tx: 0, ty: 0 }, rect = svg.getBoundingClientRect();
      var px = ev.clientX - rect.left, py = ev.clientY - rect.top;
      var factor = Math.exp(-ev.deltaY * 0.0015), k = Math.max(0.15, Math.min(4, v.k * factor));
      S.view = { k: k, tx: px - (px - v.tx) * (k / v.k), ty: py - (py - v.ty) * (k / v.k) };
      applyView();
    }, { passive: false });
    svg.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) { return; }
      var v = S.view || { k: 1, tx: 0, ty: 0 };
      drag = { x: ev.clientX, y: ev.clientY, tx: v.tx, ty: v.ty, moved: false, target: ev.target };
      svg.setPointerCapture(ev.pointerId);
      svg.classList.add('panning');
    });
    svg.addEventListener('pointermove', function (ev) {
      if (!drag) { return; }
      var dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; }
      if (drag.moved) { S.view = { k: (S.view || { k: 1 }).k, tx: drag.tx + dx, ty: drag.ty + dy }; applyView(); }
    });
    svg.addEventListener('pointerup', function (ev) {
      if (!drag) { return; }
      svg.classList.remove('panning');
      var moved = drag.moved, target = drag.target;
      drag = null;
      if (moved) { return; }
      var g = target && target.closest ? target.closest('.node') : null;
      var id = g ? g.getAttribute('data-id') : null, now = Date.now();
      // Double-click is detected here rather than with the native event: pointer capture during the
      // drag retargets the native dblclick to the svg element, so it never sees the node.
      if (id && S.lastClick && S.lastClick.id === id && now - S.lastClick.t < 450) {
        S.lastClick = null;
        setRoot(id);
        return;
      }
      S.lastClick = { id: id, t: now };
      S.selected = id;
      S.applyState();
    });
    htmlNode.getElementById('estate-fit').addEventListener('click', function () { fit(S.coords || {}); });
    htmlNode.getElementById('estate-clear').addEventListener('click', function () {
      S.selected = null; S.search = ''; searchEl.value = ''; S.applyState();
    });
    searchEl.addEventListener('input', function () { S.search = searchEl.value; S.applyState(); });
    htmlNode.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { S.selected = null; S.applyState(); } });
  }

  render();
})();
