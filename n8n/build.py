"""Regenerate n8n/workflows/*.json and site/catalog.json from workflows.py.

python -m n8n.build          # write files
python -m n8n.build --check  # fail if files are out of date (used in CI)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .validate import validate_workflow
from .workflows import ALL

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "n8n" / "workflows"
SITE = ROOT / "site"
CATALOG = SITE / "catalog.json"


def render() -> dict[Path, str]:
    files: dict[Path, str] = {}
    catalog = []
    for make in ALL:
        wf = make()
        data = wf.to_n8n()
        problems = validate_workflow(data)
        if problems:
            raise SystemExit(f"{wf.slug}:\n- " + "\n- ".join(problems))
        files[OUT / f"{wf.slug}.json"] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        files[SITE / "workflows" / f"{wf.slug}.json"] = files[OUT / f"{wf.slug}.json"]  # downloadable copy
        catalog.append(wf.catalog_entry())
    total = round(sum(c["hours_saved_per_month"] for c in catalog), 1)
    files[CATALOG] = json.dumps({"total_hours_saved_per_month": total, "workflows": catalog}, indent=2, ensure_ascii=False) + "\n"
    files[SITE / "notion-schema.json"] = json.dumps(notion_schema(), indent=2, ensure_ascii=False) + "\n"
    return files


def notion_schema() -> dict:
    from notion_os.schema import DATABASES

    return {
        "databases": [
            {
                "key": db.key,
                "title": db.title,
                "icon": db.icon,
                "description": db.description,
                "properties": [{"name": n, "type": p["type"]} for n, p in db.properties.items()]
                + [{"name": f.name, "type": "formula"} for f in db.formulas]
                + [{"name": r.name, "type": "rollup"} for r in db.rollups],
                "relations": [{"name": r.name, "target": r.target, "back_name": r.back_name} for r in db.relations],
            }
            for db in DATABASES
        ]
    }


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, content in render().items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print("wrote", path.relative_to(ROOT))
    if stale:
        print("Out of date (run python -m n8n.build):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
