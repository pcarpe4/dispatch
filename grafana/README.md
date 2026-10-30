# Grafana dashboards as code

Dashboards in `dashboards/` are pushed to Grafana by the
[`grafana-dashboards`](../.github/workflows/grafana-dashboards.yml) workflow on
every push to `main` that touches this directory (and on manual dispatch).
Pull requests only validate the JSON.

## Layout

```
grafana/
  dashboards/
    <folder>/             -> one Grafana folder per directory
      folder.json         (optional) {"uid": "...", "title": "..."}; defaults to dir name
      <dashboard>.json    exported dashboard JSON; must contain "uid" and "title"
  scripts/
    push_dashboards.py    sync script (Python 3, stdlib only)
```

Dashboards placed directly under `dashboards/` go to the **General** folder.
Dashboards are matched by `uid`, so renaming a file is safe; changing a `uid`
creates a new dashboard.

## Grafana setup

1. **Administration → Service accounts → Add service account** with the
   *Editor* role (Admin if the SA must create folders in a locked-down org).
2. **Add service account token**, copy it.
3. In GitHub, create an environment named `production` (or change the
   workflow default) and add:

   | Kind     | Name                     | Value                                      |
   |----------|--------------------------|--------------------------------------------|
   | secret   | `GRAFANA_URL`            | `https://grafana.example.com`              |
   | secret   | `GRAFANA_SA_TOKEN`       | the token from step 2                      |
   | variable | `GRAFANA_DATASOURCE_UID` | uid of the Prometheus datasource           |
   | variable | `GRAFANA_ORG_ID`         | (optional) org id if not the default org   |

### Datasource inputs

Exported dashboards reference datasources as `${DS_PROMETHEUS}` via an
`__inputs` block. The script resolves each input from
`GRAFANA_INPUT_<NAME>` (e.g. `GRAFANA_INPUT_DS_PROMETHEUS`), falling back to
`GRAFANA_DATASOURCE_UID` for datasource inputs. Add further `GRAFANA_INPUT_*`
variables to the workflow `env` block if a dashboard needs more than one.

## Running locally

```bash
export GRAFANA_URL=https://grafana.example.com
export GRAFANA_SA_TOKEN=glsa_...
export GRAFANA_DATASOURCE_UID=prometheus

python3 grafana/scripts/push_dashboards.py --offline   # JSON validation only
python3 grafana/scripts/push_dashboards.py --dry-run   # auth + plan, no writes
python3 grafana/scripts/push_dashboards.py             # push
```
