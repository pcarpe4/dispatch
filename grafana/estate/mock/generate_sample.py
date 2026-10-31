#!/usr/bin/env python3
"""
Generate estate-sample.json: a small, self-consistent mock of an enterprise
estate (datacenters, zones, subnets, firewalls, racks, ESXi, bare metal, VMs,
OpenShift clusters, nodes, namespaces, pods).

The output has the shape the dashboard expects from the real relationship API:

    {
      "nodes": [ {"id": "...", "type": "...", "name": "...", ...attributes}, ... ],
      "edges": [ {"id": "...", "source": "...", "target": "...", "relation": "..."}, ... ]
    }

Edges point from the container/provider to the thing it contains/provides
(datacenter -> zone, esxi_host -> vm, ocp_cluster -> ocp_node, ...), so a
"down" traversal from a datacenter reaches everything inside it and an "up"
traversal from a pod reaches everything it depends on.

Usage:
    python3 generate_sample.py > estate-sample.json
    python3 generate_sample.py --seed 7 --indent 1 -o estate-sample.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys

# Display order for types, top of the hierarchy first.
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


class Estate:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self._ids: set[str] = set()

    def node(self, id: str, type: str, name: str | None = None, **attrs) -> str:
        if id in self._ids:
            raise ValueError(f"duplicate node id {id!r}")
        self._ids.add(id)
        self.nodes.append({"id": id, "type": type, "name": name or id, **attrs})
        return id

    def edge(self, source: str, target: str, relation: str) -> None:
        for ref in (source, target):
            if ref not in self._ids:
                raise ValueError(f"edge references unknown node {ref!r}")
        self.edges.append(
            {"id": f"{relation}:{source}>{target}", "source": source, "target": target, "relation": relation}
        )

    def pct(self, lo: int, hi: int) -> int:
        return self.rng.randint(lo, hi)

    def get(self, id: str) -> dict:
        return next(n for n in self.nodes if n["id"] == id)


def build(rng: random.Random) -> Estate:
    e = Estate(rng)

    # ------------------------------------------------------------------ east
    e.node("dc-east", "datacenter", "East DC", region="us-east", site_code="EAST1", datacenter="dc-east")
    e.node("zone-east-prod", "zone", "east-prod", security_tier="internal", datacenter="dc-east")
    e.node("zone-east-dmz", "zone", "east-dmz", security_tier="dmz", datacenter="dc-east")
    e.edge("dc-east", "zone-east-prod", "contains")
    e.edge("dc-east", "zone-east-dmz", "contains")

    e.node("subnet-east-prod-compute", "subnet", "east-prod-compute", cidr="10.10.1.0/24", vlan=101, datacenter="dc-east")
    e.node("subnet-east-prod-bm", "subnet", "east-prod-baremetal", cidr="10.10.2.0/24", vlan=102, datacenter="dc-east")
    e.node("subnet-east-dmz", "subnet", "east-dmz", cidr="10.10.50.0/24", vlan=150, datacenter="dc-east")
    e.edge("zone-east-prod", "subnet-east-prod-compute", "contains")
    e.edge("zone-east-prod", "subnet-east-prod-bm", "contains")
    e.edge("zone-east-dmz", "subnet-east-dmz", "contains")

    e.node("fw-east-core", "firewall", "fw-east-core", vendor="Palo Alto", model="PA-5450", version="11.1.4", status="active", datacenter="dc-east")
    e.edge("dc-east", "fw-east-core", "contains")
    for s in ("subnet-east-prod-compute", "subnet-east-prod-bm", "subnet-east-dmz"):
        e.edge("fw-east-core", s, "protects")

    e.node("rack-e01", "hardware_group", "rack-E01", location="row 3, position 1", power_kw=12.5, datacenter="dc-east")
    e.node("rack-e02", "hardware_group", "rack-E02", location="row 3, position 2", power_kw=14.0, datacenter="dc-east")
    e.edge("dc-east", "rack-e01", "contains")
    e.edge("dc-east", "rack-e02", "contains")

    e.node("vsan-east-prod", "vsphere_cluster", "vsan-east-prod", vcenter="vc-east.example.com", version="8.0.3", datacenter="dc-east")
    e.edge("dc-east", "vsan-east-prod", "contains")

    for i in (1, 2, 3):
        hid = f"esx-e0{i}"
        e.node(hid, "esxi_host", hid, vendor="Dell", model="PowerEdge R760", os="VMware ESXi 8.0 U3",
               ip=f"10.10.1.{10 + i}", cpu_cores=64, mem_gb=1024,
               cpu_used_pct=e.pct(35, 75), mem_used_pct=e.pct(45, 85), status="connected", datacenter="dc-east")
        e.edge("vsan-east-prod", hid, "member")
        e.edge("rack-e01", hid, "houses")
        e.edge("subnet-east-prod-compute", hid, "serves")

    for i in (1, 2, 3):
        hid = f"bm-e0{i}"
        e.node(hid, "baremetal_host", hid, vendor="HPE", model="ProLiant DL380 Gen11", os="RHCOS 4.15",
               ip=f"10.10.2.{20 + i}", cpu_cores=96, mem_gb=768,
               cpu_used_pct=e.pct(30, 70), mem_used_pct=e.pct(40, 80), status="powered_on", datacenter="dc-east")
        e.edge("rack-e02", hid, "houses")
        e.edge("subnet-east-prod-bm", hid, "serves")

    # OpenShift on vSphere (east)
    e.node("ocp-vs-east", "ocp_cluster", "ocp-vs-east", platform="vsphere", version="4.16.12", env="prod",
           status="healthy", datacenter="dc-east")
    e.edge("zone-east-prod", "ocp-vs-east", "contains")
    vs_east_nodes = []
    placement = {"master-0": "esx-e01", "worker-0": "esx-e01", "master-1": "esx-e02", "worker-1": "esx-e02", "master-2": "esx-e03"}
    for idx, (nname, host) in enumerate(placement.items()):
        role = nname.split("-")[0]
        vmid = f"vm-ocp-vs-east-k7x2p-{nname}"
        nid = f"node-ocp-vs-east-{nname}"
        cores, mem = (4, 16) if role == "master" else (16, 64)
        e.node(vmid, "vm", f"ocp-vs-east-k7x2p-{nname}", os="RHCOS 4.16", role="ocp-node", status="poweredOn",
               ip=f"10.10.1.{30 + idx}", cpu_cores=cores, mem_gb=mem,
               cpu_used_pct=e.pct(20, 70), mem_used_pct=e.pct(30, 80), datacenter="dc-east", cluster="ocp-vs-east")
        e.edge(host, vmid, "runs")
        e.edge("subnet-east-prod-compute", vmid, "serves")
        e.node(nid, "ocp_node", nname, role=role, os="RHCOS 4.16", version="v1.29.8", status="Ready",
               cpu_cores=cores, mem_gb=mem, cpu_used_pct=e.pct(20, 70), mem_used_pct=e.pct(30, 80),
               datacenter="dc-east", cluster="ocp-vs-east")
        e.edge(vmid, nid, "backs")
        e.edge("ocp-vs-east", nid, "member")
        vs_east_nodes.append(nid)

    # Standalone VMs (east)
    e.node("vm-sql-east-01", "vm", "sql-east-01", os="Windows Server 2022", role="standalone", status="poweredOn",
           ip="10.10.1.40", cpu_cores=8, mem_gb=64, cpu_used_pct=e.pct(20, 60), mem_used_pct=e.pct(50, 90),
           app="erp-db", owner_team="dba", datacenter="dc-east")
    e.node("vm-files-east-01", "vm", "files-east-01", os="Windows Server 2019", role="standalone", status="poweredOn",
           ip="10.10.1.41", cpu_cores=4, mem_gb=16, cpu_used_pct=e.pct(5, 30), mem_used_pct=e.pct(30, 60),
           app="file-services", owner_team="platform", datacenter="dc-east")
    e.node("vm-jump-east-01", "vm", "jump-east-01", os="RHEL 9.4", role="standalone", status="poweredOn",
           ip="10.10.50.5", cpu_cores=2, mem_gb=8, cpu_used_pct=e.pct(2, 15), mem_used_pct=e.pct(20, 40),
           app="bastion", owner_team="security", datacenter="dc-east")
    for vm in ("vm-sql-east-01", "vm-files-east-01", "vm-jump-east-01"):
        e.edge("esx-e03", vm, "runs")
    e.edge("subnet-east-prod-compute", "vm-sql-east-01", "serves")
    e.edge("subnet-east-prod-compute", "vm-files-east-01", "serves")
    e.edge("subnet-east-dmz", "vm-jump-east-01", "serves")

    # OpenShift bare metal (east, compact 3-node)
    e.node("ocp-bm-east", "ocp_cluster", "ocp-bm-east", platform="baremetal", version="4.15.30", env="prod",
           status="healthy", datacenter="dc-east")
    e.edge("zone-east-prod", "ocp-bm-east", "contains")
    bm_east_nodes = []
    for i in (1, 2, 3):
        nid = f"node-ocp-bm-east-master-{i - 1}"
        e.node(nid, "ocp_node", f"master-{i - 1}", role="master", os="RHCOS 4.15", version="v1.28.13", status="Ready",
               cpu_cores=96, mem_gb=768, cpu_used_pct=e.pct(30, 70), mem_used_pct=e.pct(40, 80),
               datacenter="dc-east", cluster="ocp-bm-east")
        e.edge(f"bm-e0{i}", nid, "backs")
        e.edge("ocp-bm-east", nid, "member")
        bm_east_nodes.append(nid)

    # ------------------------------------------------------------------ west
    e.node("dc-west", "datacenter", "West DC", region="us-west", site_code="WEST1", datacenter="dc-west")
    e.node("zone-west-prod", "zone", "west-prod", security_tier="internal", datacenter="dc-west")
    e.edge("dc-west", "zone-west-prod", "contains")
    e.node("subnet-west-prod-compute", "subnet", "west-prod-compute", cidr="10.20.1.0/24", vlan=201, datacenter="dc-west")
    e.edge("zone-west-prod", "subnet-west-prod-compute", "contains")
    e.node("fw-west-core", "firewall", "fw-west-core", vendor="Fortinet", model="FortiGate 3000D", version="7.4.3",
           status="active", datacenter="dc-west")
    e.edge("dc-west", "fw-west-core", "contains")
    e.edge("fw-west-core", "subnet-west-prod-compute", "protects")
    e.node("rack-w01", "hardware_group", "rack-W01", location="row 1, position 4", power_kw=9.0, datacenter="dc-west")
    e.edge("dc-west", "rack-w01", "contains")
    e.node("vsan-west-prod", "vsphere_cluster", "vsan-west-prod", vcenter="vc-west.example.com", version="8.0.2", datacenter="dc-west")
    e.edge("dc-west", "vsan-west-prod", "contains")
    for i in (1, 2):
        hid = f"esx-w0{i}"
        e.node(hid, "esxi_host", hid, vendor="Cisco", model="UCS C240 M7", os="VMware ESXi 8.0 U2",
               ip=f"10.20.1.{10 + i}", cpu_cores=56, mem_gb=768,
               cpu_used_pct=e.pct(25, 65), mem_used_pct=e.pct(35, 75), status="connected", datacenter="dc-west")
        e.edge("vsan-west-prod", hid, "member")
        e.edge("rack-w01", hid, "houses")
        e.edge("subnet-west-prod-compute", hid, "serves")

    e.node("ocp-vs-west", "ocp_cluster", "ocp-vs-west", platform="vsphere", version="4.16.12", env="prod",
           status="degraded", datacenter="dc-west")
    e.edge("zone-west-prod", "ocp-vs-west", "contains")
    vs_west_nodes = []
    placement = {"master-0": "esx-w01", "master-1": "esx-w01", "worker-0": "esx-w01", "master-2": "esx-w02"}
    for idx, (nname, host) in enumerate(placement.items()):
        role = nname.split("-")[0]
        vmid = f"vm-ocp-vs-west-q9m4r-{nname}"
        nid = f"node-ocp-vs-west-{nname}"
        cores, mem = (4, 16) if role == "master" else (16, 64)
        e.node(vmid, "vm", f"ocp-vs-west-q9m4r-{nname}", os="RHCOS 4.16", role="ocp-node", status="poweredOn",
               ip=f"10.20.1.{30 + idx}", cpu_cores=cores, mem_gb=mem,
               cpu_used_pct=e.pct(20, 70), mem_used_pct=e.pct(30, 80), datacenter="dc-west", cluster="ocp-vs-west")
        e.edge(host, vmid, "runs")
        e.edge("subnet-west-prod-compute", vmid, "serves")
        status = "NotReady" if nname == "master-2" else "Ready"
        e.node(nid, "ocp_node", nname, role=role, os="RHCOS 4.16", version="v1.29.8", status=status,
               cpu_cores=cores, mem_gb=mem, cpu_used_pct=e.pct(20, 70), mem_used_pct=e.pct(30, 80),
               datacenter="dc-west", cluster="ocp-vs-west")
        e.edge(vmid, nid, "backs")
        e.edge("ocp-vs-west", nid, "member")
        vs_west_nodes.append(nid)

    e.node("vm-sql-west-01", "vm", "sql-west-01", os="Windows Server 2022", role="standalone", status="poweredOn",
           ip="10.20.1.40", cpu_cores=8, mem_gb=64, cpu_used_pct=e.pct(20, 60), mem_used_pct=e.pct(50, 90),
           app="erp-db", owner_team="dba", datacenter="dc-west")
    e.edge("esx-w02", "vm-sql-west-01", "runs")
    e.edge("subnet-west-prod-compute", "vm-sql-west-01", "serves")

    # ------------------------------------------------------------ workloads
    def namespace(cluster: str, ns: str, app: str, team: str, pods: list[tuple[str, str]]) -> None:
        dc = e.get(cluster)["datacenter"]
        nsid = f"ns-{cluster}-{ns}"
        e.node(nsid, "namespace", ns, app=app, owner_team=team, env="prod", datacenter=dc, cluster=cluster)
        e.edge(cluster, nsid, "hosts")
        for pod_name, node_id in pods:
            pid = f"pod-{cluster}-{ns}-{pod_name}"
            e.node(pid, "pod", pod_name, app=app, status="Running",
                   cpu_request_m=e.rng.choice([250, 500, 1000, 2000]), mem_request_mb=e.rng.choice([256, 512, 1024, 4096]),
                   datacenter=dc, cluster=cluster, namespace=ns)
            e.edge(nsid, pid, "contains")
            e.edge(node_id, pid, "schedules")

    namespace("ocp-vs-east", "payments", "payments-api", "payments", [
        ("payments-api-7d9f8b-abc12", "node-ocp-vs-east-worker-0"),
        ("payments-api-7d9f8b-def34", "node-ocp-vs-east-worker-1"),
        ("payments-worker-5c8b7d-ghi56", "node-ocp-vs-east-worker-0"),
    ])
    namespace("ocp-vs-east", "inventory", "inventory-api", "supply-chain", [
        ("inventory-api-66d4c9-jkl78", "node-ocp-vs-east-worker-1"),
        ("inventory-api-66d4c9-mno90", "node-ocp-vs-east-worker-0"),
        ("inventory-db-0", "node-ocp-vs-east-worker-1"),
    ])
    namespace("ocp-bm-east", "payments", "payments-api", "payments", [
        ("payments-api-7d9f8b-pqr12", "node-ocp-bm-east-master-0"),
        ("payments-api-7d9f8b-stu34", "node-ocp-bm-east-master-1"),
    ])
    namespace("ocp-bm-east", "ml-platform", "ml-platform", "data-science", [
        ("notebook-controller-5f6d7e-vwx56", "node-ocp-bm-east-master-2"),
        ("model-serving-fraud-v3-0", "node-ocp-bm-east-master-0"),
        ("model-serving-fraud-v3-1", "node-ocp-bm-east-master-1"),
    ])
    namespace("ocp-vs-west", "payments", "payments-api", "payments", [
        ("payments-api-7d9f8b-yza78", "node-ocp-vs-west-worker-0"),
        ("payments-api-7d9f8b-bcd90", "node-ocp-vs-west-worker-0"),
    ])

    rollups(e)
    return e


def rollups(e: Estate) -> None:
    """Pre-computed counts the real database would expose (node/pod/vm counts, cluster capacity)."""
    by_id = {n["id"]: n for n in e.nodes}
    out: dict[str, list[dict]] = {}
    for edge in e.edges:
        out.setdefault(edge["source"], []).append(edge)

    def children(id: str, relation: str, type: str) -> list[dict]:
        return [by_id[x["target"]] for x in out.get(id, []) if x["relation"] == relation and by_id[x["target"]]["type"] == type]

    for n in e.nodes:
        t = n["type"]
        if t == "ocp_cluster":
            nodes = children(n["id"], "member", "ocp_node")
            namespaces = children(n["id"], "hosts", "namespace")
            pods = [p for ns in namespaces for p in children(ns["id"], "contains", "pod")]
            n["node_count"] = len(nodes)
            n["pod_count"] = len(pods)
            n["cpu_cores"] = sum(x["cpu_cores"] for x in nodes)
            n["mem_gb"] = sum(x["mem_gb"] for x in nodes)
            n["cpu_used_pct"] = round(sum(x["cpu_used_pct"] for x in nodes) / max(len(nodes), 1))
            n["mem_used_pct"] = round(sum(x["mem_used_pct"] for x in nodes) / max(len(nodes), 1))
        elif t == "namespace":
            n["pod_count"] = len(children(n["id"], "contains", "pod"))
        elif t == "esxi_host":
            n["vm_count"] = len(children(n["id"], "runs", "vm"))
        elif t == "hardware_group":
            n["host_count"] = len(children(n["id"], "houses", "esxi_host")) + len(children(n["id"], "houses", "baremetal_host"))
        elif t == "subnet":
            n["host_count"] = sum(len(children(n["id"], "serves", x)) for x in ("esxi_host", "baremetal_host", "vm"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    ap.add_argument("--seed", type=int, default=42, help="seed for the utilisation numbers (default 42)")
    ap.add_argument("--indent", type=int, default=1)
    args = ap.parse_args()

    estate = build(random.Random(args.seed))
    order = {t: i for i, t in enumerate(TYPE_ORDER)}
    nodes = sorted(estate.nodes, key=lambda n: (order.get(n["type"], 99), n["name"]))
    payload = {"nodes": nodes, "edges": estate.edges}
    text = json.dumps(payload, indent=args.indent) + "\n"
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(text)
        print(f"wrote {args.output}: {len(nodes)} nodes, {len(estate.edges)} edges", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
