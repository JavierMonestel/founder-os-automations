"""A small fictional quarter, created with --sample-data so the OS isn't empty on day one.

Rows are created in order; "refs" let later rows link to earlier ones.
"""

SAMPLE_ROWS: list[dict] = [
    {
        "db": "objectives",
        "ref": "o1",
        "values": {
            "Objective": "Land the first paid health-system pilot",
            "Business line": "Clinical",
            "Cycle": "Q4 2026",
            "Health": "At risk",
        },
    },
    {
        "db": "objectives",
        "ref": "o2",
        "values": {
            "Objective": "Grow paid athlete memberships after the beta",
            "Business line": "Performance",
            "Cycle": "Q4 2026",
            "Health": "On track",
        },
    },
    {
        "db": "objectives",
        "ref": "o3",
        "values": {
            "Objective": "Run the company on a single source of truth",
            "Business line": "Company",
            "Cycle": "Q4 2026",
            "Health": "On track",
        },
    },
    {
        "db": "key_results",
        "ref": "k1",
        "values": {"Key result": "Signed letters of intent", "Metric": "LOIs", "Start": 0, "Current": 0, "Target": 2, "Objective": ["o1"]},
    },
    {
        "db": "key_results",
        "ref": "k2",
        "values": {
            "Key result": "Qualified pilot conversations",
            "Metric": "conversations",
            "Start": 0,
            "Current": 6,
            "Target": 10,
            "Objective": ["o1"],
        },
    },
    {
        "db": "key_results",
        "ref": "k3",
        "values": {
            "Key result": "Paying members",
            "Metric": "members",
            "Start": 1500,
            "Current": 3100,
            "Target": 5000,
            "Objective": ["o2"],
        },
    },
    {
        "db": "key_results",
        "ref": "k4",
        "values": {
            "Key result": "Founder hours per week on admin",
            "Metric": "hours",
            "Start": 12,
            "Current": 7,
            "Target": 4,
            "Objective": ["o3"],
        },
    },
    {
        "db": "projects",
        "ref": "p1",
        "values": {"Project": "Health-system pilot program", "Business line": "Clinical", "Status": "In progress", "Objective": ["o1"]},
    },
    {
        "db": "meetings",
        "ref": "m1",
        "values": {
            "Meeting": "Northfield Health – pilot scoping",
            "Date": "2026-10-01",
            "Type": "Partner",
            "Business line": "Clinical",
            "External attendees": "Dr. Alan Brooks (CMIO, Northfield Health)",
            "Summary": "Agreed on a six-month pilot at two cardiology clinics with a month-three readout.",
        },
    },
    {
        "db": "decisions",
        "ref": "d1",
        "values": {
            "Decision": "Pilot pricing model for Northfield Health",
            "Status": "Pending",
            "Business line": "Clinical",
            "Deadline": "2026-10-03",
            "Options": "Flat pilot fee / Per-monitored-patient fee / Free pilot, paid conversion",
            "Meeting": ["m1"],
        },
    },
    {
        "db": "follow_ups",
        "ref": "f1",
        "values": {
            "Follow-up": "Send Northfield the pilot proposal with both pricing options",
            "Due": "2026-10-02",
            "Priority": "P0",
            "Status": "Open",
            "Source": "Meeting",
            "Business line": "Clinical",
            "Meeting": ["m1"],
        },
    },
    {
        "db": "follow_ups",
        "ref": "f2",
        "values": {
            "Follow-up": "Schedule a call with Northfield's IT security team",
            "Due": "2026-10-08",
            "Priority": "P1",
            "Status": "Open",
            "Source": "Meeting",
            "Business line": "Clinical",
            "Meeting": ["m1"],
        },
    },
]
