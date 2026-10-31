# dispatch

| Path | What it is |
|---|---|
| [`grafana/dashboards/`](grafana/dashboards) | Grafana dashboards (OpenShift, GPU/KServe), auto-pushed by Actions — see [`grafana/README.md`](grafana/README.md) |
| [`grafana/alloy/`](grafana/alloy) | Grafana Alloy scrape configs |
| [`grafana/estate/`](grafana/estate) | Estate Explorer: interactive infrastructure topology dashboard (Infinity + HTML graphics), mock relationship API, local dev stack — see [`grafana/estate/README.md`](grafana/estate/README.md) |
| [`scripts/`](scripts) | Standalone shell tools: `find-non-olm-operators.sh`, `healthz/`, `multi-oc/`, `vrops-openshift-esxi-mapping.sh` |
| [`config-exporter/`](config-exporter) | Config-driven OpenShift config exporter (Python, with k8s manifests) |
| [`compliance-agent/`](compliance-agent) | Weekly compliance agent + RAG chatbot skeleton (Python, Helm chart) |
| [`chess/`](chess) | P2P chess app with chat and spectators |
| [`docs/`](docs) | Write-ups, briefs and how-tos |

## GitHub Actions

| Workflow | Runs on | Does |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | every push / PR | shellcheck, Python tests, YAML/JSON/Helm/kustomize checks, JS syntax |
| [`grafana-dashboards.yml`](.github/workflows/grafana-dashboards.yml) | changes under `grafana/` | validates dashboards; on `main`, pushes them to Grafana |
