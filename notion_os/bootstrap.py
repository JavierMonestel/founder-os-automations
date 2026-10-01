"""Build the Company OS in a Notion workspace with one command.

    python -m notion_os.bootstrap --parent <page-id> [--dry-run] [--sample-data]

Needs NOTION_API_KEY (an internal integration token) unless --dry-run is set, and
the parent page must be shared with that integration. --dry-run prints every
request it would send, so the structure can be reviewed before touching a workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

from .samples import SAMPLE_ROWS
from .schema import BY_KEY, DATABASES, validate

API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


@dataclass
class Call:
    method: str
    path: str
    body: dict[str, Any]
    note: str


@dataclass
class Client:
    token: str | None
    dry_run: bool
    log: list[Call] = field(default_factory=list)
    _fake_ids: int = 0

    def request(self, method: str, path: str, body: dict[str, Any], note: str) -> dict[str, Any]:
        self.log.append(Call(method, path, body, note))
        if self.dry_run:
            self._fake_ids += 1
            fake = f"dry-run-{self._fake_ids:03d}"
            # Mimic the parts of the response the next steps read.
            return {"id": fake, "data_sources": [{"id": f"{fake}-ds", "name": note}], "properties": {}}
        resp = httpx.request(
            method,
            f"{API}{path}",
            headers={"Authorization": f"Bearer {self.token}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"},
            json=body if method != "GET" else None,
            timeout=30,
        )
        if resp.status_code >= 400:
            raise SystemExit(f"Notion API error {resp.status_code} on {method} {path}: {resp.text[:500]}")
        return resp.json()


def rich(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text}}]


def build(client: Client, parent_page_id: str, sample_data: bool = False) -> dict[str, str]:
    """Create all databases, then relation-dependent formulas and rollups. Returns data source ids by key."""
    problems = validate()
    if problems:
        raise SystemExit("Schema problems:\n- " + "\n- ".join(problems))

    ds_ids: dict[str, str] = {}

    # Pass 1: databases with their own properties and relations to already-created ones.
    for db in DATABASES:
        properties = dict(db.properties)
        for rel in db.relations:
            properties[rel.name] = {
                "type": "relation",
                "relation": {"data_source_id": ds_ids[rel.target], "type": "dual_property", "dual_property": {}},
            }
        created = client.request(
            "POST",
            "/databases",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": rich(db.title),
                "description": rich(db.description),
                "icon": {"type": "emoji", "emoji": db.icon},
                "initial_data_source": {"properties": properties},
            },
            note=db.title,
        )
        ds_ids[db.key] = created["data_sources"][0]["id"]

    # Pass 2: name the two-way relations on the target side, then add formulas and rollups.
    for db in DATABASES:
        for rel in db.relations:
            target_ds = ds_ids[rel.target]
            current = client.request("GET", f"/data_sources/{target_ds}", {}, note=f"read {BY_KEY[rel.target].title}")
            synced = _find_synced_relation(current, ds_ids[db.key])
            if synced and synced != rel.back_name:
                client.request(
                    "PATCH",
                    f"/data_sources/{target_ds}",
                    {"properties": {synced: {"name": rel.back_name}}},
                    note=f"rename {BY_KEY[rel.target].title}.{synced} -> {rel.back_name}",
                )
    # Formulas before rollups: a rollup can aggregate a formula on another database
    # (Objectives.Progress averages Key Results.Progress).
    for db in DATABASES:
        if db.formulas:
            props = {f.name: {"type": "formula", "formula": {"expression": f.expression}} for f in db.formulas}
            client.request("PATCH", f"/data_sources/{ds_ids[db.key]}", {"properties": props}, note=f"{db.title}: formulas")
    for db in DATABASES:
        if db.rollups:
            props = {
                r.name: {
                    "type": "rollup",
                    "rollup": {"relation_property_name": r.relation, "rollup_property_name": r.target_property, "function": r.function},
                }
                for r in db.rollups
            }
            client.request("PATCH", f"/data_sources/{ds_ids[db.key]}", {"properties": props}, note=f"{db.title}: rollups")

    if sample_data:
        _seed(client, ds_ids)
    return ds_ids


def _find_synced_relation(data_source: dict[str, Any], source_ds_id: str) -> str | None:
    for name, prop in (data_source.get("properties") or {}).items():
        if prop.get("type") == "relation" and prop.get("relation", {}).get("data_source_id") == source_ds_id:
            return name
    return None


def _seed(client: Client, ds_ids: dict[str, str]) -> None:
    created: dict[str, str] = {}
    for row in SAMPLE_ROWS:
        props: dict[str, Any] = {}
        for name, value in row["values"].items():
            props[name] = _value(BY_KEY[row["db"]], name, value, created)
        page = client.request(
            "POST",
            "/pages",
            {"parent": {"type": "data_source_id", "data_source_id": ds_ids[row["db"]]}, "properties": props},
            note=f"sample {row['ref']}",
        )
        created[row["ref"]] = page["id"]


def _value(db, name: str, value: Any, created: dict[str, str]) -> dict[str, Any]:
    if name in {r.name for r in db.relations}:
        return {"relation": [{"id": created[v]} for v in value]}
    kind = db.properties[name]["type"]
    return {
        "title": lambda: {"title": rich(value)},
        "rich_text": lambda: {"rich_text": rich(value)},
        "number": lambda: {"number": value},
        "select": lambda: {"select": {"name": value}},
        "status": lambda: {"status": {"name": value}},
        "date": lambda: {"date": {"start": value}},
        "url": lambda: {"url": value},
    }[kind]()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parent", required=True, help="ID of the Notion page that will hold the Company OS")
    parser.add_argument("--dry-run", action="store_true", help="print the requests instead of sending them")
    parser.add_argument("--sample-data", action="store_true", help="also create a fictional example quarter")
    parser.add_argument("--json", action="store_true", help="with --dry-run, print requests as JSON")
    args = parser.parse_args(argv)

    token = os.environ.get("NOTION_API_KEY")
    if not args.dry_run and not token:
        print("Set NOTION_API_KEY (or use --dry-run).", file=sys.stderr)
        return 2

    client = Client(token=token, dry_run=args.dry_run)
    ids = build(client, args.parent, sample_data=args.sample_data)
    if args.dry_run and args.json:
        print(json.dumps([c.__dict__ for c in client.log], indent=2, ensure_ascii=False))
    else:
        for c in client.log:
            print(f"{c.method:5} {c.path:40} {c.note}")
        print(f"\n{'Planned' if args.dry_run else 'Created'} {len(DATABASES)} databases: " + ", ".join(f"{k}={v}" for k, v in ids.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
