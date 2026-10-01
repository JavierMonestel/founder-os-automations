import copy
import json
from pathlib import Path

import pytest

from n8n.build import main as build_main
from n8n.validate import validate_workflow
from n8n.workflows import ALL

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = {make().slug: make().to_n8n() for make in ALL}


@pytest.mark.parametrize("slug", WORKFLOWS)
def test_generated_workflows_pass_validation(slug):
    assert validate_workflow(WORKFLOWS[slug]) == []


def test_committed_files_match_the_generator(monkeypatch):
    monkeypatch.setattr("sys.argv", ["build", "--check"])
    assert build_main() == 0


def test_every_workflow_has_a_single_trigger_and_config():
    for slug, wf in WORKFLOWS.items():
        types = [n["type"] for n in wf["nodes"]]
        assert sum(t.endswith(("webhook", "scheduleTrigger")) for t in types) == 1, slug


def test_claude_calls_use_the_messages_api_with_header_auth():
    claude_nodes = [n for wf in WORKFLOWS.values() for n in wf["nodes"] if n["name"].startswith("Claude")]
    assert len(claude_nodes) == 4  # goals-to-linear delegates to the planner API
    for n in claude_nodes:
        p = n["parameters"]
        assert p["url"] == "https://api.anthropic.com/v1/messages"
        assert p["genericAuthType"] == "httpHeaderAuth"
        assert {"name": "anthropic-version", "value": "2023-06-01"} in p["headerParameters"]["parameters"]
        assert '"model": "claude-opus-5-5"' in p["jsonBody"]


def test_validator_catches_common_mistakes():
    wf = copy.deepcopy(WORKFLOWS["follow-up-radar"])
    wf["nodes"].append(dict(wf["nodes"][-1], id="x", name="Orphan"))
    wf["nodes"][2]["parameters"]["jsonBody"] = "={{ { a: { b: 1 }} }}"
    wf["nodes"][1]["credentials"] = {"httpHeaderAuth": {"id": "123", "name": "real"}}
    wf["nodes"][3]["parameters"]["jsCode"] = "const k = 'xoxb-1234567890-abcdefghij'; return $('Nope').all();"
    problems = "\n".join(validate_workflow(wf))
    assert "Orphan: not connected" in problems
    assert "inside expression" in problems
    assert "credential id must be empty" in problems
    assert "missing node 'Nope'" in problems
    assert "possible secret" in problems


def test_catalog_totals_add_up():
    catalog = json.loads((ROOT / "site" / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["workflows"]) == len(ALL)
    assert catalog["total_hours_saved_per_month"] == round(sum(w["hours_saved_per_month"] for w in catalog["workflows"]), 1)
