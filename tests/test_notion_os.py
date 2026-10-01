import copy

import pytest

from notion_os import bootstrap, schema
from notion_os.bootstrap import Client, build
from notion_os.samples import SAMPLE_ROWS


def dry_run(sample_data=False):
    client = Client(token=None, dry_run=True)
    ids = build(client, "parent-page", sample_data=sample_data)
    return client, ids


def test_schema_is_valid():
    assert schema.validate() == []


def test_creates_every_database_under_the_parent_with_one_title():
    client, ids = dry_run()
    creates = [c for c in client.log if c.path == "/databases"]
    assert [c.note for c in creates] == [db.title for db in schema.DATABASES]
    for call in creates:
        assert call.body["parent"] == {"type": "page_id", "page_id": "parent-page"}
        props = call.body["initial_data_source"]["properties"]
        assert sum(p["type"] == "title" for p in props.values()) == 1
    assert set(ids) == {db.key for db in schema.DATABASES}


def test_relations_point_at_already_created_data_sources():
    client, ids = dry_run()
    created_so_far: set[str] = set()
    for call in [c for c in client.log if c.path == "/databases"]:
        for prop in call.body["initial_data_source"]["properties"].values():
            if prop["type"] == "relation":
                assert prop["relation"]["data_source_id"] in created_so_far
                assert prop["relation"]["type"] == "dual_property"
        key = next(db.key for db in schema.DATABASES if db.title == call.note)
        created_so_far.add(ids[key])


def test_formulas_are_added_before_rollups_that_use_them():
    client, ids = dry_run()
    patches = [c for c in client.log if c.method == "PATCH"]
    kr_formula = next(i for i, c in enumerate(patches) if c.path.endswith(ids["key_results"]) and "Progress" in c.body["properties"])
    objective_rollup = next(i for i, c in enumerate(patches) if c.path.endswith(ids["objectives"]) and "Progress" in c.body["properties"])
    assert kr_formula < objective_rollup
    rollup = patches[objective_rollup].body["properties"]["Progress"]["rollup"]
    assert rollup == {"relation_property_name": "Key Results", "rollup_property_name": "Progress", "function": "average"}


def test_sample_rows_link_to_earlier_rows():
    client, _ = dry_run(sample_data=True)
    pages = [c for c in client.log if c.path == "/pages"]
    assert len(pages) == len(SAMPLE_ROWS)
    kr = next(c for c in pages if c.note == "sample k1")
    assert kr.body["properties"]["Objective"]["relation"][0]["id"].startswith("dry-run-")
    assert kr.body["properties"]["Start"] == {"number": 0}


def test_schema_validation_catches_mistakes(monkeypatch):
    broken = copy.deepcopy(schema.DATABASES)
    broken[1].formulas[0].expression = 'prop("Nope") + 1'
    broken[0].rollups[0].target_property = "Missing"
    monkeypatch.setattr(schema, "DATABASES", broken)
    problems = schema.validate()
    assert any("Nope" in p for p in problems)
    assert any("Missing" in p for p in problems)


def test_cli_requires_a_token_unless_dry_run(monkeypatch, capsys):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    assert bootstrap.main(["--parent", "p"]) == 2
    assert bootstrap.main(["--parent", "p", "--dry-run"]) == 0
    assert "Planned 6 databases" in capsys.readouterr().out


@pytest.mark.parametrize("db", schema.DATABASES, ids=lambda d: d.key)
def test_every_database_is_documented(db):
    assert db.description and db.icon
