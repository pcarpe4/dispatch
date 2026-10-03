# config-exporter

Config-driven exporter for OpenShift. One generic collector reads whatever the
config lists and fans the results out to pluggable sinks (API, DB, file, stdout).

```
 ConfigMap (exporter.yaml)
   exports: [...]  ──►  Collector (one code path for every kind)
                            │  list → filter (ns / names / labels) → full object OR selected fields
                            ▼
                        records ──► sinks: http | postgres | file | stdout
```

## Add something to export (no code change)

Edit `deploy/exporter.yaml` and add an entry under `exports`:

| Want                              | Spec                                                     |
|-----------------------------------|----------------------------------------------------------|
| Full YAML of every instance       | `apiVersion` + `kind`                                    |
| Only certain fields               | add `fields: [spec.host, ...]`                           |
| One specific instance             | add `names: [default]` (+ `namespaces:` if namespaced)   |
| Narrow scope                      | `namespaces`, `labelSelector`, `fieldSelector`           |
| Route to specific destinations    | `sinks: [db]`                                            |

Field paths: `a.b.c`, `list[*].x` (all items), `list[0].x`, `labels["app.kubernetes.io/name"]`.
Alias with `{path: ..., as: name}`.

Every record looks like:
```json
{"cluster":"prod-east","export":"routes","apiVersion":"route.openshift.io/v1","kind":"Route",
 "namespace":"shop","name":"web","uid":"...","resourceVersion":"...","collectedAt":"...","data":{...}}
```

## Sinks

- `http` – POSTs JSON arrays in batches (`url`, `headers`, `batchSize`, `verify`).
- `postgres` – upserts into a `jsonb` table keyed by cluster/export/kind/namespace/name; `prune: true` deletes objects that disappeared.
- `file` / `stdout` – for debugging or log shipping.

Secrets: write `${VAR}` in the config; values come from the `config-exporter-secrets` Secret via env.

**New destination type?** Add one file in `exporter/sinks/` with a class that has
`send(records)`, decorate it with `@register("kafka")`, and import it in `sinks/__init__.py`.

## Deploy

```bash
oc new-project config-exporter
oc new-build --name config-exporter --binary --strategy docker
oc start-build config-exporter --from-dir . --follow
cp deploy/secret.example.yaml deploy/secret.yaml   # fill in, don't commit
oc apply -f deploy/secret.yaml
oc apply -k deploy/
oc create job --from=cronjob/config-exporter manual-run   # run now
```

The ServiceAccount gets the built-in read-only `cluster-reader` role. For CRDs it
doesn't cover, add rules to `config-exporter-extra` in `deploy/rbac.yaml`.

## Local run / tests

```bash
pip install -r requirements.txt pytest
python -m exporter.main -c deploy/exporter.yaml   # uses your current oc login
python -m pytest tests
```
