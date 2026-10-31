"""Tests for the estate mock API and the sample data it serves.

    python3 -m unittest discover -s grafana/estate/mock -v
"""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mock_api import Estate, EstateError, make_server  # noqa: E402

SAMPLE = os.path.join(HERE, "estate-sample.json")


class EstateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.estate = Estate.from_file(SAMPLE)

    def test_sample_is_consistent(self):
        # Estate() already rejects duplicate ids and dangling edges; check the shape beyond that.
        for n in self.estate.nodes.values():
            self.assertIn("datacenter", n, n["id"])
        self.assertGreater(len(self.estate.nodes), 50)
        self.assertGreater(len(self.estate.edges), len(self.estate.nodes))
        types = {t["type"] for t in self.estate.types()}
        for expected in ("datacenter", "subnet", "esxi_host", "baremetal_host", "vm", "ocp_cluster", "ocp_node", "namespace", "pod"):
            self.assertIn(expected, types)

    def test_down_from_datacenter_returns_exactly_that_datacenter(self):
        result = self.estate.traverse("dc-east", None, "down")
        ids = {n["id"] for n in result["nodes"]}
        expected = {n["id"] for n in self.estate.nodes.values() if n["datacenter"] == "dc-east"}
        self.assertEqual(ids, expected)
        self.assertEqual(next(n for n in result["nodes"] if n["id"] == "dc-east")["depth"], 0)
        for e in result["edges"]:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)
        self.assertEqual(result["node_count"], len(ids))

    def test_depth_limits_hops(self):
        result = self.estate.traverse("dc-east", 1, "down")
        self.assertTrue(all(n["depth"] <= 1 for n in result["nodes"]))
        direct = {e["target"] for e in self.estate.out["dc-east"]}
        self.assertEqual({n["id"] for n in result["nodes"] if n["depth"] == 1}, direct)

    def test_up_from_pod_reaches_the_datacenter(self):
        pod = next(n for n in self.estate.nodes.values() if n["type"] == "pod")
        result = self.estate.traverse(pod["id"], None, "up")
        reached = {n["type"] for n in result["nodes"]}
        for t in ("pod", "namespace", "ocp_cluster", "ocp_node", "subnet", "zone", "datacenter"):
            self.assertIn(t, reached)
        self.assertTrue(reached & {"vm", "baremetal_host"})

    def test_clusters_on_a_subnet(self):
        # "How many OpenShift clusters are on this subnet?" A down traversal reaches the
        # hosts, VMs and OpenShift nodes the subnet serves; the nodes' `cluster` attribute
        # names the clusters. (The dashboard counts distinct values of that column.)
        result = self.estate.traverse("subnet-east-prod-compute", None, "down")
        clusters = {n["cluster"] for n in result["nodes"] if n["type"] == "ocp_node"}
        self.assertEqual(clusters, {"ocp-vs-east"})
        self.assertFalse(any(n["type"] == "ocp_cluster" for n in result["nodes"]))

    def test_both_direction_fans_out_through_hubs(self):
        # Undirected walks reach the zone in one hop and everything the zone contains in two,
        # so `both` answers "what is near X", not "what depends on X".
        result = self.estate.traverse("subnet-east-prod-compute", 2, "both")
        clusters = {n["id"] for n in result["nodes"] if n["type"] == "ocp_cluster"}
        self.assertEqual(clusters, {"ocp-vs-east", "ocp-bm-east"})
        self.assertTrue(all(n["depth"] <= 2 for n in result["nodes"]))

    def test_whole_estate_when_no_root(self):
        result = self.estate.traverse(None)
        self.assertEqual(result["node_count"], len(self.estate.nodes))
        self.assertEqual(result["edge_count"], len(self.estate.edges))

    def test_list_nodes_filters(self):
        rows = self.estate.list_nodes(["datacenter", "zone"])
        self.assertEqual({r["type"] for r in rows}, {"datacenter", "zone"})
        self.assertEqual(rows[0]["type"], "datacenter")  # type order, then name
        self.assertTrue(all("label" in r for r in rows))
        self.assertEqual([r["id"] for r in self.estate.list_nodes(None, "sql-east")], ["vm-sql-east-01"])

    def test_node_includes_its_edges(self):
        n = self.estate.node("esx-e01")
        relations = {e["relation"] for e in n["edges"]}
        self.assertEqual(relations, {"member", "houses", "serves", "runs"})

    def test_errors(self):
        with self.assertRaises(KeyError):
            self.estate.traverse("does-not-exist")
        with self.assertRaises(EstateError):
            self.estate.traverse("dc-east", None, "sideways")
        with self.assertRaises(EstateError):
            Estate([{"id": "a", "type": "t", "name": "a"}], [{"id": "e", "source": "a", "target": "b", "relation": "r"}])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(Estate.from_file(SAMPLE), "127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # ignore proxy env vars

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        try:
            with self.opener.open(f"http://127.0.0.1:{self.port}{path}", timeout=10) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as err:
            return err.code, json.load(err)

    def test_health(self):
        status, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_traverse(self):
        status, body = self.get("/traverse?root=ocp-vs-east&depth=all&direction=down")
        self.assertEqual(status, 200)
        types = {n["type"] for n in body["nodes"]}
        self.assertEqual(types, {"ocp_cluster", "ocp_node", "namespace", "pod"})
        self.assertTrue(all(set(e) >= {"id", "source", "target", "relation"} for e in body["edges"]))

    def test_unknown_root_is_404(self):
        status, body = self.get("/traverse?root=nope")
        self.assertEqual(status, 404)
        self.assertIn("nope", body["error"])

    def test_bad_depth_is_400(self):
        status, _ = self.get("/traverse?root=dc-east&depth=lots")
        self.assertEqual(status, 400)

    def test_nodes_and_types(self):
        status, rows = self.get("/nodes?type=ocp_cluster")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(r["id"] for r in rows), ["ocp-bm-east", "ocp-vs-east", "ocp-vs-west"])
        status, types = self.get("/types")
        self.assertEqual(status, 200)
        self.assertEqual(types[0]["type"], "datacenter")


if __name__ == "__main__":
    unittest.main()
