#!/usr/bin/env python3
"""
mock_api.py - stand-in for the estate relationship API.

Serves the estate in estate-sample.json over HTTP so the Grafana dashboard
(Infinity data source) can be wired up and exercised before the real API is
reachable. Python 3 standard library only; no install step.

    python3 mock_api.py                                   # 127.0.0.1:8099, estate-sample.json next to this file
    python3 mock_api.py --bind 0.0.0.0 --port 8099 --data estate-sample.json --delay-ms 300

Endpoints (all JSON, GET):

    /health                              liveness + counts
    /types                               [{"type": "...", "count": n}]
    /nodes?type=a,b&q=text&limit=n       [{"id","type","name","label"}]   (dashboard drop-downs)
    /node/<id>                           one node with every edge touching it
    /traverse?root=<id>&depth=<n|all>&direction=<down|up|both>
                                         {"root","depth","direction","nodes":[...],"edges":[...]}

/traverse is the call the dashboard is built on: breadth-first walk of the
relationships from `root`, at most `depth` hops, following edges forwards
(down: container -> contained), backwards (up) or both. The response carries
every node reached (with its hop count in `depth`) and every edge whose two
ends were both reached, so the result is a self-contained sub-graph.
`root=all` (or no root) returns the whole estate.

Every request is logged to stderr, so you can watch exactly how many calls a
dashboard refresh makes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TYPE_ORDER = [
    "datacenter",
    "zone",
    "firewall",
    "hardware_group",
    "subnet",
    "vsphere_cluster",
    "esxi_host",
    "baremetal_host",
    "vm",
    "ocp_cluster",
    "ocp_node",
    "namespace",
    "pod",
]
DIRECTIONS = ("down", "up", "both")
DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estate-sample.json")


class EstateError(ValueError):
    """Malformed estate data or bad request parameters."""


class Estate:
    """In-memory graph: nodes by id, edges with forward/backward adjacency."""

    def __init__(self, nodes: list, edges: list):
        self.nodes: dict = {}
        for n in nodes:
            for key in ("id", "type", "name"):
                if key not in n:
                    raise EstateError(f"node is missing {key!r}: {n}")
            if n["id"] in self.nodes:
                raise EstateError(f"duplicate node id {n['id']!r}")
            self.nodes[n["id"]] = n
        self.edges: list = []
        self.out: dict = {}
        self.inc: dict = {}
        seen: set = set()
        for e in edges:
            for key in ("id", "source", "target", "relation"):
                if key not in e:
                    raise EstateError(f"edge is missing {key!r}: {e}")
            if e["id"] in seen:
                raise EstateError(f"duplicate edge id {e['id']!r}")
            for ref in (e["source"], e["target"]):
                if ref not in self.nodes:
                    raise EstateError(f"edge {e['id']!r} references unknown node {ref!r}")
            seen.add(e["id"])
            self.edges.append(e)
            self.out.setdefault(e["source"], []).append(e)
            self.inc.setdefault(e["target"], []).append(e)

    @classmethod
    def from_file(cls, path: str) -> "Estate":
        with open(path) as fh:
            data = json.load(fh)
        return cls(data.get("nodes", []), data.get("edges", []))

    @staticmethod
    def type_rank(type_name: str) -> int:
        return TYPE_ORDER.index(type_name) if type_name in TYPE_ORDER else len(TYPE_ORDER)

    def sort_key(self, n: dict):
        return (self.type_rank(n["type"]), n["name"], n["id"])

    def types(self) -> list:
        counts: dict = {}
        for n in self.nodes.values():
            counts[n["type"]] = counts.get(n["type"], 0) + 1
        return [
            {"type": t, "count": c}
            for t, c in sorted(counts.items(), key=lambda kv: (self.type_rank(kv[0]), kv[0]))
        ]

    def list_nodes(self, types=None, q: str = "", limit=None) -> list:
        q = (q or "").lower()
        rows = [
            n
            for n in self.nodes.values()
            if (not types or n["type"] in types) and (not q or q in n["name"].lower() or q in n["id"].lower())
        ]
        rows.sort(key=self.sort_key)
        if limit:
            rows = rows[:limit]
        return [
            {"id": n["id"], "type": n["type"], "name": n["name"], "label": f"{n['name']}  [{n['type']}]"}
            for n in rows
        ]

    def node(self, node_id: str) -> dict:
        n = self.nodes[node_id]  # KeyError -> 404
        edges = sorted(self.out.get(node_id, []) + self.inc.get(node_id, []), key=lambda e: e["id"])
        return {**n, "edges": edges}

    def neighbours(self, node_id: str, direction: str):
        if direction in ("down", "both"):
            for e in self.out.get(node_id, []):
                yield e["target"]
        if direction in ("up", "both"):
            for e in self.inc.get(node_id, []):
                yield e["source"]

    def traverse(self, root=None, depth=None, direction: str = "down") -> dict:
        if direction not in DIRECTIONS:
            raise EstateError(f"direction must be one of {', '.join(DIRECTIONS)}")
        if depth is not None and depth < 0:
            raise EstateError("depth must be >= 0")
        if root is None:
            found = {node_id: None for node_id in self.nodes}
        else:
            if root not in self.nodes:
                raise KeyError(root)
            found = {root: 0}
            queue = deque([root])
            while queue:
                current = queue.popleft()
                hops = found[current]
                if depth is not None and hops >= depth:
                    continue
                for nxt in self.neighbours(current, direction):
                    if nxt not in found:
                        found[nxt] = hops + 1
                        queue.append(nxt)
        nodes = [{**self.nodes[i], "depth": d} for i, d in found.items()]
        nodes.sort(key=lambda n: (n["depth"] or 0, self.sort_key(n)))
        edges = [e for e in self.edges if e["source"] in found and e["target"] in found]
        return {
            "root": root,
            "depth": depth,
            "direction": direction,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }


class Handler(BaseHTTPRequestHandler):
    estate: Estate
    delay: float = 0.0
    server_version = "estate-mock-api/1.0"

    def do_GET(self):  # noqa: N802 (http.server naming)
        url = urlparse(self.path)
        qs = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path.rstrip("/") or "/"
        if self.delay:
            time.sleep(self.delay)
        try:
            if path in ("/", "/health"):
                return self.send_json(200, {
                    "status": "ok",
                    "nodes": len(self.estate.nodes),
                    "edges": len(self.estate.edges),
                    "endpoints": ["/health", "/types", "/nodes", "/node/<id>", "/traverse"],
                })
            if path == "/types":
                return self.send_json(200, self.estate.types())
            if path == "/nodes":
                types = [t for t in qs.get("type", "").split(",") if t]
                limit = int(qs["limit"]) if qs.get("limit") else None
                return self.send_json(200, self.estate.list_nodes(types or None, qs.get("q", ""), limit))
            if path.startswith("/node/"):
                return self.send_json(200, self.estate.node(path[len("/node/"):]))
            if path == "/traverse":
                root = qs.get("root") or None
                if root in ("all", "*"):
                    root = None
                depth_raw = qs.get("depth", "all")
                depth = None if depth_raw in ("", "all", "*") else int(depth_raw)
                return self.send_json(200, self.estate.traverse(root, depth, qs.get("direction", "down")))
            return self.send_json(404, {"error": f"no such endpoint: {path}"})
        except KeyError as exc:
            return self.send_json(404, {"error": f"unknown node id: {exc.args[0]}"})
        except ValueError as exc:  # includes EstateError and int() failures
            return self.send_json(400, {"error": str(exc)})

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def send_json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), self.address_string(), fmt % args))


def make_server(estate: Estate, bind: str = "127.0.0.1", port: int = 8099, delay: float = 0.0) -> ThreadingHTTPServer:
    bound = type("BoundHandler", (Handler,), {"estate": estate, "delay": delay})
    return ThreadingHTTPServer((bind, port), bound)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DEFAULT_DATA, help="estate JSON file (default: estate-sample.json next to this script)")
    ap.add_argument("--bind", default="127.0.0.1", help="address to listen on (0.0.0.0 inside containers)")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--delay-ms", type=int, default=0, help="artificial latency per request, to make loading visible")
    args = ap.parse_args()

    try:
        estate = Estate.from_file(args.data)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load {args.data}: {exc}", file=sys.stderr)
        return 2
    server = make_server(estate, args.bind, args.port, args.delay_ms / 1000.0)
    host, port = server.server_address[:2]
    print(f"estate mock API: {len(estate.nodes)} nodes, {len(estate.edges)} edges from {args.data}", file=sys.stderr)
    print(f"listening on http://{host}:{port}  (try /health, /types, /traverse?root=dc-east)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
