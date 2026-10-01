"""Tiny builder for n8n workflow JSON.

Workflows are defined in Python (see workflows.py) so they stay consistent and can be
validated in CI, then exported as plain n8n JSON that imports with
`n8n import:workflow` or the editor's "Import from file".
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

NAMESPACE = uuid.UUID("6f1b6a8e-6d55-4a52-9d0f-5f2a3c1e7b10")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-5-5"


def stable_id(*parts: str) -> str:
    """Deterministic UUIDs so regenerated files produce clean diffs."""
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


@dataclass
class Node:
    name: str
    type: str
    type_version: float
    parameters: dict[str, Any]
    credentials: dict[str, dict[str, str]] | None = None
    webhook: bool = False
    notes: str | None = None


@dataclass
class Workflow:
    slug: str
    name: str
    description: str
    trigger: str
    tools: list[str]
    minutes_saved_per_run: int
    runs_per_month: int
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    timezone: str = "America/New_York"

    def add(self, node: Node, after: str | list[str] | None = None) -> Node:
        self.nodes.append(node)
        for parent in [after] if isinstance(after, str) else after or []:
            self.edges.append((parent, node.name))
        return node

    # ---- export

    def layout(self) -> dict[str, list[int]]:
        """Left-to-right layout by depth; siblings stacked vertically."""
        depth: dict[str, int] = {}
        parents = {n.name: [a for a, b in self.edges if b == n.name] for n in self.nodes}
        for n in self.nodes:  # nodes are added in topological order
            depth[n.name] = 1 + max((depth[p] for p in parents[n.name]), default=-1)
        rows: dict[int, int] = {}
        pos: dict[str, list[int]] = {}
        for n in self.nodes:
            d = depth[n.name]
            pos[n.name] = [d * 260, rows.get(d, 0) * 180]
            rows[d] = rows.get(d, 0) + 1
        return pos

    def to_n8n(self) -> dict[str, Any]:
        pos = self.layout()
        nodes = []
        for n in self.nodes:
            node: dict[str, Any] = {
                "parameters": n.parameters,
                "id": stable_id(self.slug, n.name),
                "name": n.name,
                "type": n.type,
                "typeVersion": n.type_version,
                "position": pos[n.name],
            }
            if n.webhook:
                node["webhookId"] = stable_id(self.slug, n.name, "webhook")
            if n.credentials:
                node["credentials"] = n.credentials
            if n.notes:
                node["notes"] = n.notes
                node["notesInFlow"] = True
            nodes.append(node)
        connections: dict[str, Any] = {}
        for a, b in self.edges:
            connections.setdefault(a, {"main": [[]]})["main"][0].append({"node": b, "type": "main", "index": 0})
        return {
            "name": self.name,
            "nodes": nodes,
            "connections": connections,
            "active": False,
            "settings": {"executionOrder": "v1", "timezone": self.timezone, "saveManualExecutions": True},
            "pinData": {},
            "meta": {"templateCredsSetupCompleted": False},
            "tags": [],
        }

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "tools": self.tools,
            "minutes_saved_per_run": self.minutes_saved_per_run,
            "runs_per_month": self.runs_per_month,
            "hours_saved_per_month": round(self.minutes_saved_per_run * self.runs_per_month / 60, 1),
            "nodes": [{"name": n.name, "type": n.type.split(".")[-1], "notes": n.notes} for n in self.nodes],
            "edges": [list(e) for e in self.edges],
            "file": f"n8n/workflows/{self.slug}.json",
        }


# ---------------------------------------------------------------- node helpers


def webhook(name: str, path: str, respond_with_node: bool = False) -> Node:
    return Node(
        name,
        "n8n-nodes-base.webhook",
        2,
        {"httpMethod": "POST", "path": path, "responseMode": "responseNode" if respond_with_node else "onReceived", "options": {}},
        webhook=True,
    )


def schedule(name: str, cron: str) -> Node:
    return Node(name, "n8n-nodes-base.scheduleTrigger", 1.2, {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}})


def code(name: str, js: str, notes: str | None = None) -> Node:
    return Node(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip() + "\n"}, notes=notes)


def http(
    name: str,
    method: str,
    url: str,
    *,
    credential: str | None = None,
    headers: dict[str, str] | None = None,
    json_body: str | None = None,
    notes: str | None = None,
) -> Node:
    params: dict[str, Any] = {"method": method, "url": url}
    creds = None
    if credential:
        params.update({"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"})
        creds = {"httpHeaderAuth": {"id": "", "name": credential}}
    if headers:
        params["sendHeaders"] = True
        params["headerParameters"] = {"parameters": [{"name": k, "value": v} for k, v in headers.items()]}
    if json_body is not None:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": json_body})
    params["options"] = {}
    return Node(name, "n8n-nodes-base.httpRequest", 4.2, params, credentials=creds, notes=notes)


def respond(name: str, body_expression: str) -> Node:
    return Node(name, "n8n-nodes-base.respondToWebhook", 1.1, {"respondWith": "json", "responseBody": body_expression, "options": {}})


def claude(name: str, system: str, user_expression: str, schema: dict[str, Any] | None = None, effort: str = "medium") -> Node:
    """HTTP call to the Anthropic Messages API. The body is an n8n expression so the
    system prompt stays readable in the editor and the user content comes from the previous node."""
    body: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": 16000,
        "system": system,
        "output_config": {"effort": effort},
        "messages": [{"role": "user", "content": "__USER__"}],
    }
    if schema:
        body["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    raw = json.dumps(body, ensure_ascii=False).replace('"__USER__"', f"JSON.stringify({user_expression})")
    # n8n delimits expressions with {{ }}; keep nested braces apart so "}}" never ends it early.
    while "}}" in raw or "{{" in raw:
        raw = raw.replace("}}", "} }").replace("{{", "{ {")
    # n8n evaluates "={{ ... }}" as a JavaScript expression that returns the body object.
    return http(
        name,
        "POST",
        ANTHROPIC_URL,
        credential="Anthropic API key (x-api-key)",
        headers={"anthropic-version": "2023-06-01"},
        json_body="={{ " + raw + " }}",
        notes=f"Claude ({MODEL}). Credential: Header Auth with name x-api-key.",
    )


CLAUDE_TEXT_JS = """
// Claude returns content blocks (thinking + text). Keep only the text.
const res = $input.first().json;
if (res.stop_reason === 'refusal') throw new Error('Model declined the request');
const text = (res.content || []).filter(b => b.type === 'text').map(b => b.text).join('\\n').trim();
"""
