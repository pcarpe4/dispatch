"""Generic collector: one code path for every export, driven only by config.

Export spec keys:
  name           unique id for this export (required)
  apiVersion     e.g. apps/v1, route.openshift.io/v1 (required)
  kind           e.g. Deployment, Route, ClusterVersion (required)
  namespaces     list of namespaces; omit for all (ignored for cluster-scoped kinds)
  names          only these object names
  labelSelector  e.g. "app=web,tier!=cache"
  fieldSelector  e.g. "status.phase=Running"
  fields         paths to keep; omit to export the full object
  strip          paths to drop from full objects (default: metadata.managedFields)
  sinks          sink names to send to; omit for all sinks
"""
import copy
import datetime
import logging

from . import fields as F

log = logging.getLogger(__name__)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Collector:
    def __init__(self, dyn_client, cluster_name, defaults=None):
        self.dyn = dyn_client
        self.cluster = cluster_name
        self.defaults = defaults or {}

    def _list(self, spec):
        api = self.dyn.resources.get(api_version=spec["apiVersion"], kind=spec["kind"])
        kwargs = {}
        if spec.get("labelSelector"):
            kwargs["label_selector"] = spec["labelSelector"]
        if spec.get("fieldSelector"):
            kwargs["field_selector"] = spec["fieldSelector"]

        namespaces = spec.get("namespaces") if api.namespaced else None
        if not namespaces:
            yield from api.get(**kwargs).to_dict().get("items", [])
            return
        for ns in namespaces:
            yield from api.get(namespace=ns, **kwargs).to_dict().get("items", [])

    def collect(self, spec):
        names = set(spec.get("names") or [])
        strip = spec.get("strip", self.defaults.get("strip", []))
        collected_at = _now()
        records = []
        for obj in self._list(spec):
            meta = obj.get("metadata", {})
            if names and meta.get("name") not in names:
                continue
            if spec.get("fields"):
                data = F.project(obj, spec["fields"])
            else:
                data = F.strip(copy.deepcopy(obj), strip)
            records.append({
                "cluster": self.cluster,
                "export": spec["name"],
                "apiVersion": spec["apiVersion"],
                "kind": spec["kind"],
                "namespace": meta.get("namespace"),
                "name": meta.get("name"),
                "uid": meta.get("uid"),
                "resourceVersion": meta.get("resourceVersion"),
                "collectedAt": collected_at,
                "data": data,
            })
        log.info("export=%s kind=%s records=%d", spec["name"], spec["kind"], len(records))
        return records
