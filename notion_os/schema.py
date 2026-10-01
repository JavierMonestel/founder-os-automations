"""Declarative schema for the Company OS in Notion.

Six linked databases form the single source of truth for a two-line startup:

    Objectives ──< Key Results          (OKRs with computed progress)
        │
        └──< Projects                   (each links out to Linear)
    Meetings ──< Decisions              (what was decided, by whom, when)
        └────< Follow-ups               (owned, dated, never lost)

Relations are created as dual (two-way) properties so every page shows its context
from both sides. Formulas and rollups that depend on relations are added in a
second pass, after every database exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LINES = [("Clinical", "green"), ("Performance", "orange"), ("Company", "blue")]


def select(options: list[tuple[str, str]]) -> dict[str, Any]:
    return {"type": "select", "select": {"options": [{"name": n, "color": c} for n, c in options]}}


def status(todo: list[str], doing: list[str], done: list[str]) -> dict[str, Any]:
    opts = [{"name": n, "color": "default", "group": "To-do"} for n in todo]
    opts += [{"name": n, "color": "blue", "group": "In progress"} for n in doing]
    opts += [{"name": n, "color": "green", "group": "Complete"} for n in done]
    return {"type": "status", "status": {"options": opts}}


def simple(kind: str) -> dict[str, Any]:
    return {"type": kind, kind: {}}


@dataclass
class Relation:
    """A dual relation from this database to `target`, shown there as `back_name`."""

    name: str
    target: str
    back_name: str


@dataclass
class Rollup:
    name: str
    relation: str  # relation property on this database
    target_property: str  # property on the related database
    function: str  # e.g. "average", "count", "percent_checked"


@dataclass
class Formula:
    name: str
    expression: str


@dataclass
class Database:
    key: str
    title: str
    icon: str
    description: str
    properties: dict[str, dict[str, Any]]
    relations: list[Relation] = field(default_factory=list)
    formulas: list[Formula] = field(default_factory=list)
    rollups: list[Rollup] = field(default_factory=list)


KR_PROGRESS = 'if(prop("Target") == prop("Start"), 1, min(max((prop("Current") - prop("Start")) / (prop("Target") - prop("Start")), 0), 1))'

OVERDUE = 'and(not empty(prop("Due")), prop("Due") < today(), prop("Status") != "Done")'

DATABASES: list[Database] = [
    Database(
        key="objectives",
        title="Objectives",
        icon="🎯",
        description="Company and business-line objectives for the current cycle.",
        properties={
            "Objective": simple("title"),
            "Business line": select(LINES),
            "Cycle": select([("Q4 2026", "purple"), ("Q1 2027", "gray")]),
            "Owner": simple("people"),
            "Health": select([("On track", "green"), ("At risk", "yellow"), ("Off track", "red")]),
            "Why it matters": simple("rich_text"),
        },
        rollups=[Rollup(name="Progress", relation="Key Results", target_property="Progress", function="average")],
    ),
    Database(
        key="key_results",
        title="Key Results",
        icon="📈",
        description="Measurable results. Progress is computed from start, current and target.",
        properties={
            "Key result": simple("title"),
            "Metric": simple("rich_text"),
            "Start": simple("number"),
            "Current": simple("number"),
            "Target": simple("number"),
            "Owner": simple("people"),
            "Last updated": simple("last_edited_time"),
        },
        relations=[Relation(name="Objective", target="objectives", back_name="Key Results")],
        formulas=[Formula(name="Progress", expression=KR_PROGRESS)],
    ),
    Database(
        key="projects",
        title="Projects",
        icon="🗂️",
        description="Initiatives that move an objective. Execution lives in Linear; context lives here.",
        properties={
            "Project": simple("title"),
            "Business line": select(LINES),
            "Status": status(["Not started"], ["In progress", "Blocked"], ["Done"]),
            "Owner": simple("people"),
            "Target date": simple("date"),
            "Linear project": simple("url"),
        },
        relations=[Relation(name="Objective", target="objectives", back_name="Projects")],
    ),
    Database(
        key="meetings",
        title="Meetings",
        icon="🗓️",
        description="Every meeting with its recording, summary, decisions and follow-ups.",
        properties={
            "Meeting": simple("title"),
            "Date": simple("date"),
            "Type": select([("Leadership sync", "blue"), ("Partner", "green"), ("Investor", "purple"), ("1:1", "gray"), ("Board", "red")]),
            "Business line": select(LINES),
            "Attendees": simple("people"),
            "External attendees": simple("rich_text"),
            "Recording": simple("url"),
            "Summary": simple("rich_text"),
        },
    ),
    Database(
        key="decisions",
        title="Decisions",
        icon="⚖️",
        description="Decisions waiting on the founder, and the log of what was decided and why.",
        properties={
            "Decision": simple("title"),
            "Status": status(["Pending"], ["Needs info"], ["Decided"]),
            "Business line": select(LINES),
            "Requested by": simple("people"),
            "Deadline": simple("date"),
            "Options": simple("rich_text"),
            "Outcome": simple("rich_text"),
        },
        relations=[Relation(name="Meeting", target="meetings", back_name="Decisions")],
    ),
    Database(
        key="follow_ups",
        title="Follow-ups",
        icon="✅",
        description="Every commitment with an owner and a due date. The radar automation reads this.",
        properties={
            "Follow-up": simple("title"),
            "Owner": simple("people"),
            "Due": simple("date"),
            "Priority": select([("P0", "red"), ("P1", "yellow"), ("P2", "gray")]),
            "Status": status(["Open"], ["Waiting on others"], ["Done"]),
            "Source": select([("Meeting", "blue"), ("Email", "purple"), ("Slack", "pink"), ("Founder", "brown")]),
            "Business line": select(LINES),
            "External link": simple("url"),
        },
        relations=[Relation(name="Meeting", target="meetings", back_name="Follow-ups")],
        formulas=[Formula(name="Overdue", expression=OVERDUE)],
    ),
]

BY_KEY = {db.key: db for db in DATABASES}


def validate() -> list[str]:
    """Static checks run in CI: relations, rollups and formulas reference things that exist."""
    problems: list[str] = []
    titles = {db.key for db in DATABASES}
    order = [db.key for db in DATABASES]
    for db in DATABASES:
        if sum(1 for p in db.properties.values() if p["type"] == "title") != 1:
            problems.append(f"{db.title}: needs exactly one title property")
        for rel in db.relations:
            if rel.target not in titles:
                problems.append(f"{db.title}.{rel.name}: unknown target {rel.target}")
            elif order.index(rel.target) > order.index(db.key):
                problems.append(f"{db.title}.{rel.name}: target must be created first")
        for f in db.formulas:
            for ref in _prop_refs(f.expression):
                if ref not in db.properties and ref not in {r.name for r in db.relations}:
                    problems.append(f"{db.title}.{f.name}: formula references missing property {ref!r}")
        for r in db.rollups:
            back = [rel for other in DATABASES for rel in other.relations if rel.target == db.key and rel.back_name == r.relation]
            if not back:
                problems.append(f"{db.title}.{r.name}: no relation named {r.relation!r} points here")
            else:
                source = next(other for other in DATABASES if back[0] in other.relations)
                names = set(source.properties) | {f.name for f in source.formulas}
                if r.target_property not in names:
                    problems.append(f"{db.title}.{r.name}: {source.title} has no property {r.target_property!r}")
    return problems


def _prop_refs(expression: str) -> list[str]:
    import re

    return re.findall(r'prop\("([^"]+)"\)', expression)
