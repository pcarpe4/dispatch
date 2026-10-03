from exporter import fields as F

OBJ = {
    "metadata": {"name": "web", "labels": {"app.kubernetes.io/name": "shop"},
                 "managedFields": [{"x": 1}]},
    "spec": {"template": {"spec": {"containers": [
        {"name": "a", "image": "img-a"}, {"name": "b", "image": "img-b"}, {"name": "c"}]}}},
}


def test_plain_path():
    assert F.extract(OBJ, "metadata.name") == "web"


def test_missing_path_returns_default():
    assert F.extract(OBJ, "spec.nope.deeper") is None
    assert F.extract(OBJ, "spec.nope", default="-") == "-"


def test_wildcard_fans_out_and_skips_missing():
    assert F.extract(OBJ, "spec.template.spec.containers[*].image") == ["img-a", "img-b"]


def test_index():
    assert F.extract(OBJ, "spec.template.spec.containers[1].name") == "b"
    assert F.extract(OBJ, "spec.template.spec.containers[9].name") is None


def test_quoted_key_with_dots():
    assert F.extract(OBJ, 'metadata.labels["app.kubernetes.io/name"]') == "shop"


def test_project_with_alias():
    out = F.project(OBJ, ["metadata.name", {"path": "spec.template.spec.containers[*].name", "as": "c"}])
    assert out == {"metadata.name": "web", "c": ["a", "b", "c"]}


def test_strip():
    import copy
    o = F.strip(copy.deepcopy(OBJ), ["metadata.managedFields", "does.not.exist"])
    assert "managedFields" not in o["metadata"]
