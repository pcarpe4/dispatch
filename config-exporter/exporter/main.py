"""Entry point: load config -> collect every export -> fan out to sinks."""
import argparse
import logging
import os
import sys

from . import config as cfgmod
from . import sinks as sinkmod
from .collector import Collector

log = logging.getLogger("exporter")


def _dynamic_client():
    from kubernetes import client, config as kcfg
    from kubernetes.dynamic import DynamicClient
    try:
        kcfg.load_incluster_config()
    except kcfg.ConfigException:
        kcfg.load_kube_config()
    return DynamicClient(client.ApiClient())


def run(cfg, dyn):
    cluster = cfg.get("cluster") or os.environ.get("CLUSTER_NAME", "unknown")
    collector = Collector(dyn, cluster, cfg["defaults"])
    sinks = {s["name"]: sinkmod.build(s) for s in cfg["sinks"]}

    outbox = {name: [] for name in sinks}
    failures = 0
    for spec in cfg["exports"]:
        if spec.get("enabled", True) is False:
            continue
        try:
            records = collector.collect(spec)
        except Exception as e:  # one bad export shouldn't sink the run
            failures += 1
            log.error("export=%s failed: %s", spec["name"], e)
            continue
        for name in spec.get("sinks") or sinks:
            outbox[name].extend(records)

    for name, records in outbox.items():
        try:
            sinks[name].send(records)
        except Exception as e:
            failures += 1
            log.error("sink=%s failed: %s", name, e)
    return failures


def main(argv=None):
    p = argparse.ArgumentParser(description="Export OpenShift config to APIs/DBs")
    p.add_argument("-c", "--config", default=os.environ.get("EXPORTER_CONFIG", "/config/exporter.yaml"))
    args = p.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stderr)
    failures = run(cfgmod.load(args.config), _dynamic_client())
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
