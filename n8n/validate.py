"""Static checks for n8n workflow JSON (no n8n install needed)."""

from __future__ import annotations

import re
from typing import Any

ALLOWED_TYPES = {
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.code",
    "n8n-nodes-base.respondToWebhook",
}
TRIGGERS = {"n8n-nodes-base.webhook", "n8n-nodes-base.scheduleTrigger"}
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic
    re.compile(r"lin_api_[A-Za-z0-9]{10,}"),  # Linear
    re.compile(r"secret_[A-Za-z0-9]{20,}|ntn_[A-Za-z0-9]{20,}"),  # Notion
    re.compile(r"xox[bpa]-[A-Za-z0-9-]{10,}"),  # Slack
]


def validate_workflow(wf: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    nodes = wf.get("nodes", [])
    names = [n["name"] for n in nodes]
    if len(names) != len(set(names)):
        problems.append("duplicate node names")
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        problems.append("duplicate node ids")
    by_name = {n["name"]: n for n in nodes}

    for n in nodes:
        if n["type"] not in ALLOWED_TYPES:
            problems.append(f"{n['name']}: unexpected node type {n['type']}")
        if n["type"] == "n8n-nodes-base.webhook" and "webhookId" not in n:
            problems.append(f"{n['name']}: webhook without webhookId")
        for cred in (n.get("credentials") or {}).values():
            if cred.get("id"):
                problems.append(f"{n['name']}: credential id must be empty in a shared template")

    triggers = [n for n in nodes if n["type"] in TRIGGERS]
    if len(triggers) != 1:
        problems.append(f"expected exactly one trigger, found {len(triggers)}")

    targets: set[str] = set()
    for source, outputs in wf.get("connections", {}).items():
        if source not in by_name:
            problems.append(f"connection from unknown node {source!r}")
        for branch in outputs.get("main", []):
            for edge in branch:
                if edge["node"] not in by_name:
                    problems.append(f"connection to unknown node {edge['node']!r}")
                targets.add(edge["node"])
    for n in nodes:
        if n["type"] not in TRIGGERS and n["name"] not in targets:
            problems.append(f"{n['name']}: not connected to anything upstream")

    # Expressions like $('Config') must reference real nodes.
    blob = str([n["parameters"] for n in nodes])
    for ref in set(re.findall(r"\$\('([^']+)'\)", blob)):
        if ref not in by_name:
            problems.append(f"expression references missing node {ref!r}")

    # n8n ends an expression at the first "}}", so nested objects must be written "} }".
    for n in nodes:
        for key, value in _strings(n["parameters"]):
            if value.startswith("={{"):
                inner = value[3:]
                if not inner.rstrip().endswith("}}"):
                    problems.append(f"{n['name']}.{key}: expression must end with }}}}")
                elif "}}" in inner.rstrip()[:-2] or "{{" in inner:
                    problems.append(f"{n['name']}.{key}: '}}}}' inside expression would end it early")

    for pattern in SECRET_PATTERNS:
        if pattern.search(str(wf)):
            problems.append(f"possible secret matching {pattern.pattern}")
    return problems


def _strings(obj: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(obj, str):
        return [(path, obj)]
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in _strings(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        return [x for i, v in enumerate(obj) for x in _strings(v, f"{path}[{i}]")]
    return []
