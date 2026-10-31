#!/usr/bin/env python3
"""
Push Grafana dashboard JSON files to a Grafana instance via its HTTP API.

Layout (one Grafana folder per directory):

    grafana/dashboards/
      <folder>/
        folder.json          (optional) {"title": "...", "uid": "..."}
        <dashboard>.json
        ...

Dashboards at the top level of grafana/dashboards/ go to the General folder.

Authentication uses a Grafana service account token (Bearer). Exported
dashboards that contain `__inputs` (e.g. ${DS_PROMETHEUS}) are resolved via
the /api/dashboards/import endpoint, with datasource inputs supplied from
environment variables:

    GRAFANA_INPUT_<INPUT_NAME>   e.g. GRAFANA_INPUT_DS_PROMETHEUS=prometheus-uid
    GRAFANA_DATASOURCE_UID       fallback for any datasource input not set above

Required environment:
    GRAFANA_URL        e.g. https://grafana.example.com
    GRAFANA_SA_TOKEN   service account token

Optional:
    GRAFANA_ORG_ID     organisation id (X-Grafana-Org-Id header)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


class GrafanaError(RuntimeError):
    pass


class Grafana:
    def __init__(self, url: str, token: str, org_id: str | None = None, dry_run: bool = False):
        self.url = url.rstrip("/")
        self.token = token
        self.org_id = org_id
        self.dry_run = dry_run

    def _request(self, method: str, path: str, body: dict | None = None):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.org_id:
            headers["X-Grafana-Org-Id"] = self.org_id
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            return e.code, raw

    def check_auth(self) -> None:
        status, body = self._request("GET", "/api/org")
        if status != 200:
            raise GrafanaError(f"auth check failed ({status}): {body}")
        print(f"Authenticated against {self.url} (org: {body.get('name')})")

    def ensure_folder(self, uid: str, title: str) -> str:
        status, body = self._request("GET", f"/api/folders/{uid}")
        if status == 200:
            if body.get("title") != title:
                print(f"  folder '{uid}': renaming '{body.get('title')}' -> '{title}'")
                if not self.dry_run:
                    s, b = self._request("PUT", f"/api/folders/{uid}", {"title": title, "overwrite": True})
                    if s != 200:
                        raise GrafanaError(f"folder update failed ({s}): {b}")
            else:
                print(f"  folder '{title}' ({uid}) exists")
            return uid
        if status != 404:
            raise GrafanaError(f"folder lookup failed ({status}): {body}")
        print(f"  folder '{title}' ({uid}) missing -> creating")
        if self.dry_run:
            return uid
        status, body = self._request("POST", "/api/folders", {"uid": uid, "title": title})
        if status != 200:
            raise GrafanaError(f"folder create failed ({status}): {body}")
        return body["uid"]

    def import_dashboard(self, dashboard: dict, folder_uid: str | None, inputs: list[dict]) -> None:
        dashboard = dict(dashboard)
        dashboard.pop("id", None)  # ids are instance-specific; match on uid instead
        payload = {
            "dashboard": dashboard,
            "overwrite": True,
            "inputs": inputs,
            "folderUid": folder_uid or "",
        }
        if self.dry_run:
            return
        status, body = self._request("POST", "/api/dashboards/import", payload)
        if status != 200:
            raise GrafanaError(f"import failed ({status}): {body}")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()
    return slug[:40] or "folder"


def resolve_inputs(dashboard: dict, env: dict[str, str]) -> list[dict]:
    """Build the `inputs` array for the import API from the dashboard's __inputs."""
    resolved = []
    for inp in dashboard.get("__inputs", []):
        name = inp["name"]
        value = env.get(f"GRAFANA_INPUT_{name}") or None  # unset CI variables arrive as ""
        if value is None and inp.get("type") == "datasource":
            value = env.get("GRAFANA_DATASOURCE_UID") or None
        if value is None:
            raise GrafanaError(
                f"no value for input '{name}': set GRAFANA_INPUT_{name}"
                + (" or GRAFANA_DATASOURCE_UID" if inp.get("type") == "datasource" else "")
            )
        resolved.append({
            "name": name,
            "type": inp.get("type", "datasource"),
            "pluginId": inp.get("pluginId", ""),
            "value": value,
        })
    return resolved


def load_folder_meta(directory: Path) -> tuple[str, str]:
    meta_file = directory / "folder.json"
    title, uid = directory.name, slugify(directory.name)
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        title = meta.get("title", title)
        uid = meta.get("uid", uid)
    return uid, title


def collect(root: Path) -> list[tuple[Path | None, list[Path]]]:
    """Return [(folder_dir or None for General, [dashboard files])]."""
    groups: list[tuple[Path | None, list[Path]]] = []
    top = sorted(p for p in root.glob("*.json") if p.name != "folder.json")
    if top:
        groups.append((None, top))
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(p for p in d.glob("*.json") if p.name != "folder.json")
        if files:
            groups.append((d, files))
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="grafana/dashboards", help="dashboards root directory")
    ap.add_argument("--dry-run", action="store_true", help="validate and show plan, but do not write to Grafana")
    ap.add_argument("--offline", action="store_true", help="validate JSON only; no network calls")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    env = dict(os.environ)
    groups = collect(root)
    if not groups:
        print(f"No dashboards found under {root}")
        return 0

    # Validate all files first so a bad file fails fast before anything is pushed.
    seen_uids: dict[str, Path] = {}
    parsed: list[tuple[Path | None, Path, dict]] = []
    errors = 0
    for folder_dir, files in groups:
        for f in files:
            try:
                dash = json.loads(f.read_text())
            except json.JSONDecodeError as e:
                print(f"error: {f}: invalid JSON: {e}", file=sys.stderr)
                errors += 1
                continue
            uid, title = dash.get("uid"), dash.get("title")
            if not uid or not title:
                print(f"error: {f}: dashboard must have 'uid' and 'title'", file=sys.stderr)
                errors += 1
                continue
            if uid in seen_uids:
                print(f"error: {f}: duplicate uid '{uid}' (also in {seen_uids[uid]})", file=sys.stderr)
                errors += 1
                continue
            seen_uids[uid] = f
            parsed.append((folder_dir, f, dash))
    if errors:
        return 1
    print(f"Validated {len(parsed)} dashboard(s)")
    if args.offline:
        return 0

    url, token = env.get("GRAFANA_URL"), env.get("GRAFANA_SA_TOKEN")
    if not url or not token:
        print("error: GRAFANA_URL and GRAFANA_SA_TOKEN must be set", file=sys.stderr)
        return 2

    gf = Grafana(url, token, env.get("GRAFANA_ORG_ID"), dry_run=args.dry_run)
    try:
        gf.check_auth()
        folder_uids: dict[Path | None, str | None] = {None: None}
        for folder_dir, _ in groups:
            if folder_dir is not None:
                uid, title = load_folder_meta(folder_dir)
                folder_uids[folder_dir] = gf.ensure_folder(uid, title)
        for folder_dir, f, dash in parsed:
            inputs = resolve_inputs(dash, env)
            where = load_folder_meta(folder_dir)[1] if folder_dir else "General"
            print(f"  {'[dry-run] ' if args.dry_run else ''}{f} -> '{dash['title']}' in '{where}'")
            gf.import_dashboard(dash, folder_uids[folder_dir], inputs)
    except GrafanaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
