import json
import logging

from . import register

log = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    cluster          text        NOT NULL,
    export           text        NOT NULL,
    api_version      text        NOT NULL,
    kind             text        NOT NULL,
    namespace        text        NOT NULL DEFAULT '',
    name             text        NOT NULL,
    uid              text,
    resource_version text,
    collected_at     timestamptz NOT NULL,
    data             jsonb       NOT NULL,
    PRIMARY KEY (cluster, export, kind, namespace, name)
)
"""

UPSERT = """
INSERT INTO {table} (cluster, export, api_version, kind, namespace, name,
                     uid, resource_version, collected_at, data)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (cluster, export, kind, namespace, name) DO UPDATE SET
    api_version = EXCLUDED.api_version,
    uid = EXCLUDED.uid,
    resource_version = EXCLUDED.resource_version,
    collected_at = EXCLUDED.collected_at,
    data = EXCLUDED.data
"""


@register("postgres")
class PostgresSink:
    """Upserts latest state into a jsonb table (one row per object per export).

    cfg:
      dsn:    postgresql://user:${PGPASSWORD}@host:5432/db
      table:  ocp_config (default)
      prune:  true -> delete rows for objects that no longer exist
    """

    def __init__(self, cfg):
        import psycopg  # imported lazily so the image works without it if unused
        self.psycopg = psycopg
        self.dsn = cfg["dsn"]
        self.table = cfg.get("table", "ocp_config")
        self.prune = bool(cfg.get("prune", False))
        if not self.table.replace("_", "").replace(".", "").isalnum():
            raise ValueError(f"invalid table name {self.table!r}")

    def send(self, records):
        rows = [(
            r["cluster"], r["export"], r["apiVersion"], r["kind"], r["namespace"] or "",
            r["name"], r["uid"], r["resourceVersion"], r["collectedAt"],
            json.dumps(r["data"], default=str),
        ) for r in records]
        with self.psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(DDL.format(table=self.table))
            cur.executemany(UPSERT.format(table=self.table), rows)
            if self.prune:
                self._prune(cur, records)
        log.info("postgres sink: upserted %d rows into %s", len(rows), self.table)

    def _prune(self, cur, records):
        # Within each export collected this run, delete rows not seen this run.
        runs = {}
        for r in records:
            runs.setdefault((r["cluster"], r["export"]), r["collectedAt"])
        for (cluster, export), ts in runs.items():
            cur.execute(
                f"DELETE FROM {self.table} WHERE cluster=%s AND export=%s AND collected_at < %s",
                (cluster, export, ts),
            )
