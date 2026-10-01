// Runs the JavaScript inside each n8n Code node against mocked inputs, the same way
// n8n does ($input, $('Node'), $now), so the workflow logic is tested, not just imported.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DateTime } from "luxon";

const load = (slug) => JSON.parse(readFileSync(new URL(`../n8n/workflows/${slug}.json`, import.meta.url), "utf8"));
const node = (wf, name) => {
  const n = wf.nodes.find((x) => x.name === name);
  assert.ok(n, `node ${name} exists`);
  return n;
};
const items = (...jsons) => jsons.map((json) => ({ json }));

function runCode(wf, name, { input = [], nodes = {}, now = DateTime.fromISO("2026-10-01T16:00:00", { zone: "America/New_York" }) } = {}) {
  const js = node(wf, name).parameters.jsCode;
  const $input = { all: () => input, first: () => input[0] };
  const $ = (ref) => {
    assert.ok(nodes[ref], `test provides output of node ${ref}`);
    return { all: () => nodes[ref], first: () => nodes[ref][0] };
  };
  return new Function("$input", "$", "$now", js)($input, $, now);
}

const claudeResponse = (obj, extra = {}) => ({
  stop_reason: "end_turn",
  content: [{ type: "thinking", thinking: "" }, { type: "text", text: JSON.stringify(obj) }],
  ...extra,
});

test("meeting-to-actions: transcript is built from the recorder payload", () => {
  const wf = load("meeting-to-actions");
  const config = runCode(wf, "Config");
  const out = runCode(wf, "Build transcript", {
    nodes: {
      Config: config,
      "Recording ready": items({
        body: {
          title: "Pilot call",
          date: "2026-10-01",
          participants: [{ name: "Sam Rivera" }, { name: "Dr. Alan Brooks", organization: "Northfield Health" }],
          transcript: [{ start: "00:04:05", speaker: "Sam Rivera", text: "I'll send the proposal by Friday." }],
        },
      }),
    },
  });
  assert.match(out[0].json.prompt, /\[00:04:05\] Sam Rivera: I'll send the proposal by Friday\./);
  assert.match(out[0].json.prompt, /Dr\. Alan Brooks \[external, Northfield Health\]/);
});

test("meeting-to-actions: ungrounded items are dropped and thinking blocks ignored", () => {
  const wf = load("meeting-to-actions");
  const prompt = "[00:04:05] Sam Rivera: I'll send the proposal by Friday.";
  const out = runCode(wf, "Parse & validate", {
    input: items(
      claudeResponse({
        summary: "s",
        decisions: ["Six-month pilot"],
        open_questions: [],
        action_items: [
          { title: "Send proposal", owner: "Sam Rivera", due_date: "2026-10-02", destination: "attio", quote: "I'll send the proposal by Friday." },
          { title: "Invented task", owner: "Sam Rivera", due_date: null, destination: "linear", quote: "This was never said." },
        ],
      }),
    ),
    nodes: { "Build transcript": items({ title: "Pilot call", date: "2026-10-01", prompt, recording_url: null }) },
  });
  assert.equal(out.length, 1);
  assert.equal(out[0].json.title, "Send proposal");
  assert.equal(out[0].json._dropped, 1);
});

test("meeting-to-actions: a refusal stops the workflow instead of creating junk", () => {
  const wf = load("meeting-to-actions");
  assert.throws(
    () => runCode(wf, "Parse & validate", { input: items({ stop_reason: "refusal", content: [] }), nodes: { "Build transcript": items({ prompt: "" }) } }),
    /declined/,
  );
});

test("meeting-to-actions: items are split by destination", () => {
  const wf = load("meeting-to-actions");
  const parsed = items({ destination: "linear" }, { destination: "attio" }, { destination: "calendar" }, { destination: "notion" });
  assert.equal(runCode(wf, "Only Linear items", { input: parsed }).length, 1);
  assert.equal(runCode(wf, "Only Attio items", { input: parsed }).length, 1);
  assert.equal(runCode(wf, "Only Notion items", { input: parsed }).length, 2);
});

test("follow-up-radar: one nudge per owner, most overdue first", () => {
  const wf = load("follow-up-radar");
  const page = (title, owner, due) => ({
    url: `https://notion.so/${title.replaceAll(" ", "-")}`,
    properties: { "Follow-up": { title: [{ plain_text: title }] }, Due: { date: { start: due } }, Owner: { people: [{ name: owner }] } },
  });
  const out = runCode(wf, "Group by owner", {
    input: items({
      results: [
        page("Send proposal", "Sam Rivera", "2026-10-01"),
        page("Chase DUA redlines", "Priya Natarajan", "2026-09-29"),
        page("Approve invoice", "Sam Rivera", "2026-09-28"),
        page("Book consultant", "Sam Rivera", "2026-10-02"),
      ],
    }),
  });
  assert.equal(out.length, 2);
  const sam = out.find((o) => o.json.owner === "Sam Rivera").json.text;
  assert.match(sam, /^Hi Sam,/);
  const order = ["Approve invoice", "Send proposal", "Book consultant"].map((t) => sam.indexOf(t));
  assert.deepEqual([...order].sort((a, b) => a - b), order, "most overdue first");
  assert.match(sam, /Approve invoice — 3 days overdue/);
  assert.match(sam, /Send proposal — due today/);
  assert.match(sam, /Book consultant — due tomorrow/);
});

test("goals-to-linear: Notion objectives become planner goals", () => {
  const wf = load("goals-to-linear");
  const obj = (title, line) => ({ properties: { Objective: { title: [{ plain_text: title }] }, "Business line": { select: { name: line } } } });
  const out = runCode(wf, "Goals + team", { input: items({ results: [obj("Sign 2 pilot LOIs", "Clinical"), obj("Grow members", "Performance")] }) });
  assert.equal(out[0].json.month, "2026-10");
  assert.deepEqual(out[0].json.goals.map((g) => [g.id, g.line]), [["g1", "clinical"], ["g2", "performance"]]);
  assert.equal(out[0].json.team.length, 5);
});

test("goals-to-linear: capacity summary flags overloaded people", () => {
  const wf = load("goals-to-linear");
  const team = [{ id: "dev", name: "Dev Patel", capacity: 5 }, { id: "sam", name: "Sam Rivera", capacity: 8 }];
  const plan = {
    month: "2026-10",
    cycles: [{ number: 1 }, { number: 2 }],
    projects: [{}],
    issues: [
      { assigneeId: "dev", cycle: 1, estimate: 5 },
      { assigneeId: "dev", cycle: 1, estimate: 3 },
      { assigneeId: "sam", cycle: 2, estimate: 2 },
    ],
  };
  const out = runCode(wf, "Capacity summary", { input: items(plan), nodes: { "Goals + team": items({ team }) } });
  assert.match(out[0].json.text, /1 project · 3 issues · 10 pts/);
  assert.match(out[0].json.text, /Dev: 8\/5 pts in cycle 1/);
  assert.doesNotMatch(out[0].json.text, /Sam:/);
});

test("investor-update-draft: only continues on the last weekday of the month", () => {
  const wf = load("investor-update-draft");
  const run = (iso) => runCode(wf, "Last business day?", { input: items({}), now: DateTime.fromISO(iso, { zone: "America/New_York" }) }).length;
  assert.equal(run("2026-10-30T14:00:00"), 1); // Friday Oct 30 is the last weekday of October 2026
  assert.equal(run("2026-10-29T14:00:00"), 0);
  assert.equal(run("2026-11-30T14:00:00"), 1); // Monday Nov 30
  assert.equal(run("2026-11-27T14:00:00"), 0);
});

test("investor-update-draft: long drafts are split into Notion-sized blocks", () => {
  const wf = load("investor-update-draft");
  const text = "Para one.\n\n" + "x".repeat(2500);
  const out = runCode(wf, "To Notion blocks", {
    input: items({ stop_reason: "end_turn", content: [{ type: "text", text }] }),
    nodes: { "Assemble inputs": items({ month: "October 2026" }) },
  });
  assert.equal(out[0].json.title, "Investor update — October 2026 (draft)");
  assert.equal(out[0].json.blocks.length, 2);
  assert.ok(out[0].json.blocks.every((b) => b.paragraph.rich_text[0].text.content.length <= 2000));
});

test("travel-request: plan becomes a Notion trip page with to-dos", () => {
  const wf = load("travel-request");
  const plan = {
    options: [{ label: "A", outbound: "Oct 13 PM", return: "Oct 15 PM", hotel_area: "Downtown", rationale: "Shortest trip" }],
    holds: [{ title: "Travel", start: "2026-10-13T15:00", end: "2026-10-13T19:00" }],
    checklist: ["Demo device"],
    need_from_founder: ["Seat preference"],
  };
  const out = runCode(wf, "Trip page", {
    input: items(claudeResponse(plan)),
    nodes: { "Trip request": items({ body: { destination: "Boston", purpose: "Sports science conference" } }) },
  });
  assert.equal(out[0].json.title, "Trip: Boston — Sports science conference");
  assert.equal(out[0].json.blocks.filter((b) => b.type === "to_do").length, 2);
});
