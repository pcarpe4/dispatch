import os
import textwrap

import pytest

from exporter import config as C
from exporter import main
from exporter.collector import Collector


class FakeResult:
    def __init__(self, items):
        self.items = items

    def to_dict(self):
        return {"items": self.items}


class FakeApi:
    def __init__(self, items, namespaced=True):
        self.items, self.namespaced, self.calls = items, namespaced, []

    def get(self, namespace=None, **kw):
        self.calls.append((namespace, kw))
        return FakeResult([i for i in self.items
                           if namespace is None or i["metadata"].get("namespace") == namespace])


class FakeDyn:
    def __init__(self, apis):
        self.apis = apis
        self.resources = self

    def get(self, api_version, kind):  # mimics dyn.resources.get
        return self.apis[(api_version, kind)]


def dep(ns, name):
    return {"metadata": {"namespace": ns, "name": name, "uid": name, "managedFields": []},
            "spec": {"replicas": 2}}


@pytest.fixture
def dyn():
    return FakeDyn({
        ("apps/v1", "Deployment"): FakeApi([dep("a", "web"), dep("a", "api"), dep("b", "web")]),
        ("config.openshift.io/v1", "ClusterVersion"): FakeApi(
            [{"metadata": {"name": "version"}, "status": {"desired": {"version": "4.16.3"}}}],
            namespaced=False),
    })


def test_full_object_strips_managed_fields(dyn):
    recs = Collector(dyn, "c1", {"strip": ["metadata.managedFields"]}).collect(
        {"name": "all", "apiVersion": "apps/v1", "kind": "Deployment"})
    assert len(recs) == 3
    assert "managedFields" not in recs[0]["data"]["metadata"]
    assert recs[0]["cluster"] == "c1"


def test_fields_namespaces_and_names(dyn):
    api = dyn.apis[("apps/v1", "Deployment")]
    recs = Collector(dyn, "c1").collect({
        "name": "x", "apiVersion": "apps/v1", "kind": "Deployment",
        "namespaces": ["a"], "names": ["web"], "labelSelector": "app=web",
        "fields": ["spec.replicas"]})
    assert [(r["namespace"], r["name"], r["data"]) for r in recs] == [("a", "web", {"spec.replicas": 2})]
    assert api.calls == [("a", {"label_selector": "app=web"})]


def test_cluster_scoped_ignores_namespaces(dyn):
    recs = Collector(dyn, "c1").collect({
        "name": "cv", "apiVersion": "config.openshift.io/v1", "kind": "ClusterVersion",
        "namespaces": ["ignored"], "fields": ["status.desired.version"]})
    assert recs[0]["data"] == {"status.desired.version": "4.16.3"}


def test_config_env_expansion_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN", "s3cret")
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent("""
        exports: [{name: a, apiVersion: v1, kind: ConfigMap, sinks: [api]}]
        sinks: [{name: api, type: http, url: "http://x", headers: {Authorization: "Bearer ${TOKEN}"}}]
    """))
    cfg = C.load(str(p))
    assert cfg["sinks"][0]["headers"]["Authorization"] == "Bearer s3cret"

    p.write_text("exports: [{name: a, apiVersion: v1, kind: ConfigMap, sinks: [nope]}]")
    with pytest.raises(ValueError, match="unknown sinks"):
        C.load(str(p))


def test_run_routes_to_sinks(dyn, monkeypatch):
    sent = {}

    class Mem:
        def __init__(self, cfg):
            self.name = cfg["name"]

        def send(self, records):
            sent[self.name] = [r["export"] for r in records]

    from exporter import sinks
    monkeypatch.setitem(sinks._REGISTRY, "mem", Mem)
    cfg = {
        "cluster": "c1", "defaults": {},
        "sinks": [{"name": "s1", "type": "mem"}, {"name": "s2", "type": "mem"}],
        "exports": [
            {"name": "deps", "apiVersion": "apps/v1", "kind": "Deployment", "sinks": ["s1"]},
            {"name": "cv", "apiVersion": "config.openshift.io/v1", "kind": "ClusterVersion"},
            {"name": "broken", "apiVersion": "x/v1", "kind": "Missing"},
        ],
    }
    failures = main.run(cfg, dyn)
    assert failures == 1  # the broken export, but the rest still ran
    assert sent == {"s1": ["deps"] * 3 + ["cv"], "s2": ["cv"]}
