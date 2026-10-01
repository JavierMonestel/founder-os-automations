"""The automation library. Run `python -m n8n.build` to regenerate n8n/workflows/*.json."""

from __future__ import annotations

from .lib import CLAUDE_TEXT_JS, Workflow, claude, code, http, respond, schedule, webhook

NOTION = "https://api.notion.com/v1"
NOTION_HEADERS = {"Notion-Version": "2026-03-11"}
LINEAR = "https://api.linear.app/graphql"
SLACK_POST = "https://slack.com/api/chat.postMessage"

CONFIG_JS = """
// Edit these once after importing. IDs come from your own workspace.
return [{ json: {
  slackChannel: 'C0123456789',          // e.g. #founder-ops
  founderSlackId: 'U0123456789',        // DM target for the brief
  linearTeamId: 'YOUR-LINEAR-TEAM-ID',
  notion: {
    followUps: 'FOLLOW-UPS-DATA-SOURCE-ID',
    meetings: 'MEETINGS-DATA-SOURCE-ID',
    keyResults: 'KEY-RESULTS-DATA-SOURCE-ID',
    decisions: 'DECISIONS-DATA-SOURCE-ID',
    objectives: 'OBJECTIVES-DATA-SOURCE-ID',
    tripsParentPage: 'TRAVEL-PAGE-ID',
    investorUpdatesPage: 'INVESTOR-UPDATES-PAGE-ID',
  },
  team: ['Sam Rivera (Founder & CEO)', 'Dev Patel (CTO)', 'Priya Natarajan (Clinical Lead)',
         'Marcus Hale (Performance Lead)', 'Javier Monestel (Executive Assistant)'],
  timezone: 'America/New_York',
} }];
"""

ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "decisions", "open_questions", "action_items"],
    "properties": {
        "summary": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "owner", "due_date", "destination", "quote"],
                "properties": {
                    "title": {"type": "string"},
                    "owner": {"type": "string"},
                    "due_date": {"type": ["string", "null"]},
                    "destination": {"type": "string", "enum": ["linear", "attio", "notion", "calendar"]},
                    "quote": {"type": "string"},
                },
            },
        },
    },
}

MEETING_SYSTEM = (
    "You extract follow-ups from a meeting transcript for a two-line health-tech startup (Clinical and Performance). "
    "Only real commitments; one item per commitment; owner = full participant name; resolve relative dates against the meeting date; "
    "destination: linear = engineering/product/growth work, attio = anything owed to a partner, customer, site or investor, "
    "notion = docs/playbooks/templates, calendar = a meeting to schedule. quote must be copied verbatim. Never invent anything."
)


def meeting_to_actions() -> Workflow:
    wf = Workflow(
        slug="meeting-to-actions",
        name="Meeting → owned follow-ups (Grain → Claude → Linear · Attio · Notion · Slack)",
        description="When a meeting recording is ready, Claude extracts decisions and commitments with verbatim evidence, "
        "creates Linear issues, Attio tasks and Notion follow-ups, and posts a recap with every owner to Slack.",
        trigger="Webhook: meeting recorder 'recording ready'",
        tools=["Grain", "Claude", "Linear", "Attio", "Notion", "Slack"],
        minutes_saved_per_run=25,
        runs_per_month=40,
    )
    wf.add(webhook("Recording ready", "meeting-recording"))
    wf.add(code("Config", CONFIG_JS), after="Recording ready")
    wf.add(
        code(
            "Build transcript",
            """
const body = $('Recording ready').first().json.body || {};
const lines = (body.transcript || []).map(u => `[${u.start}] ${u.speaker}: ${u.text}`).join('\\n');
const people = (body.participants || []).map(p => `${p.name}${p.organization ? ' [external, ' + p.organization + ']' : ''}`).join(', ');
return [{ json: {
  title: body.title || 'Untitled meeting',
  date: body.date || new Date().toISOString().slice(0, 10),
  recording_url: body.url || null,
  prompt: `Meeting: ${body.title}\\nDate: ${body.date}\\nParticipants: ${people}\\nTeam: ${$('Config').first().json.team.join('; ')}\\n\\n${lines}`,
} }];
""",
        ),
        after="Config",
    )
    wf.add(claude("Claude: extract actions", MEETING_SYSTEM, "$json.prompt", schema=ACTION_SCHEMA), after="Build transcript")
    wf.add(
        code(
            "Parse & validate",
            CLAUDE_TEXT_JS
            + """
const result = JSON.parse(text);
const meeting = $('Build transcript').first().json;
const transcript = meeting.prompt;
// Grounding check: drop any item whose quote is not verbatim in the transcript.
const grounded = result.action_items.filter(i => transcript.includes(i.quote));
const dropped = result.action_items.length - grounded.length;
return grounded.map(item => ({ json: { ...item, meeting: meeting.title, meeting_date: meeting.date, recording_url: meeting.recording_url, _summary: result.summary, _decisions: result.decisions, _dropped: dropped } }));
""",
            notes="Drops any item whose quote isn't found verbatim in the transcript.",
        ),
        after="Claude: extract actions",
    )
    wf.add(code("Only Linear items", "return $input.all().filter(i => i.json.destination === 'linear');"), after="Parse & validate")
    wf.add(code("Only Attio items", "return $input.all().filter(i => i.json.destination === 'attio');"), after="Parse & validate")
    wf.add(
        code("Only Notion items", "return $input.all().filter(i => ['notion', 'calendar'].includes(i.json.destination));"),
        after="Parse & validate",
    )
    wf.add(
        http(
            "Linear: create issue",
            "POST",
            LINEAR,
            credential="Linear API key (Authorization)",
            json_body="={{ { query: 'mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { identifier url } } }', "
            "variables: { input: { teamId: $('Config').first().json.linearTeamId, title: $json.title, "
            "description: '> ' + $json.quote + '\\n\\nFrom: ' + $json.meeting + ' · Owner: ' + $json.owner, "
            "dueDate: $json.due_date || undefined } } } }}",
        ),
        after="Only Linear items",
    )
    wf.add(
        http(
            "Attio: create task",
            "POST",
            "https://api.attio.com/v2/tasks",
            credential="Attio API key (Authorization: Bearer)",
            json_body="={{ { data: { content: $json.title + ' (owner: ' + $json.owner + ', from ' + $json.meeting + ')', format: 'plaintext', "
            "deadline_at: $json.due_date ? $json.due_date + 'T17:00:00.000Z' : null, is_completed: false, linked_records: [], assignees: [] } } }}",
            notes="Link to the partner's company record by adding linked_records once the record id is known.",
        ),
        after="Only Attio items",
    )
    wf.add(
        http(
            "Notion: add follow-up",
            "POST",
            f"{NOTION}/pages",
            credential="Notion integration token (Authorization: Bearer)",
            headers=NOTION_HEADERS,
            json_body="={{ { parent: { data_source_id: $('Config').first().json.notion.followUps }, properties: { "
            "'Follow-up': { title: [ { text: { content: $json.title } } ] }, "
            "Status: { status: { name: 'Open' } }, Source: { select: { name: 'Meeting' } }, "
            "Due: $json.due_date ? { date: { start: $json.due_date } } : { date: null } } } }}",
        ),
        after="Only Notion items",
    )
    wf.add(
        code(
            "Compose recap",
            """
const items = $('Parse & validate').all().map(i => i.json);
if (!items.length) return [{ json: { text: 'No follow-ups found in this meeting.' } }];
const m = items[0];
const lines = items.map(i => `• *${i.title}* — ${i.owner}${i.due_date ? ' · due ' + i.due_date : ''} → ${i.destination}`);
const decisions = (m._decisions || []).map(d => `• ${d}`);
const text = [
  `*${m.meeting}* (${m.meeting_date})`,
  m._summary,
  decisions.length ? '\\n*Decided*\\n' + decisions.join('\\n') : '',
  '\\n*Follow-ups*\\n' + lines.join('\\n'),
  m._dropped ? `\\n_${m._dropped} item(s) dropped: quote not found in transcript._` : '',
  m.recording_url ? `\\n<${m.recording_url}|Recording>` : '',
].filter(Boolean).join('\\n');
return [{ json: { text } }];
""",
        ),
        after=["Linear: create issue", "Attio: create task", "Notion: add follow-up"],
    )
    wf.add(
        http(
            "Slack: post recap",
            "POST",
            SLACK_POST,
            credential="Slack bot token (Authorization: Bearer)",
            json_body="={{ { channel: $('Config').first().json.slackChannel, text: $json.text, unfurl_links: false } }}",
        ),
        after="Compose recap",
    )
    return wf


def founder_daily_brief() -> Workflow:
    wf = Workflow(
        slug="founder-daily-brief",
        name="Founder daily brief (Command Center + Claude → Slack DM)",
        description="Every weekday at 7:45 AM, pulls the company snapshot (OKRs, follow-ups, decisions, blockers, meetings) "
        "and has Claude write a 60-second brief that lands in the founder's Slack DMs.",
        trigger="Schedule: weekdays 7:45 AM",
        tools=["Founder Command Center", "Claude", "Slack"],
        minutes_saved_per_run=20,
        runs_per_month=21,
    )
    wf.add(schedule("Weekdays 7:45", "45 7 * * 1-5"))
    wf.add(code("Config", CONFIG_JS), after="Weekdays 7:45")
    wf.add(
        http(
            "Get company snapshot",
            "GET",
            "https://founder-command-center-jet.vercel.app/api/snapshot",
            notes="Any JSON source works here: Notion queries, Linear, a Google Sheet.",
        ),
        after="Config",
    )
    wf.add(
        claude(
            "Claude: write brief",
            "You are the chief-of-staff assistant to a startup founder with a Clinical and a Performance business line. "
            "Write today's brief in Slack Markdown from the JSON snapshot: TL;DR with counts; 'Needs you today' (decisions due within 48h with options, "
            "the founder's overdue items); one short section per line (OKR pulse vs cycle elapsed, overdue follow-ups with owners, blockers); "
            "meetings today and tomorrow with prep; delegation suggestions. Only use the snapshot. Max 250 words.",
            "$json",
        ),
        after="Get company snapshot",
    )
    wf.add(code("Extract text", CLAUDE_TEXT_JS + "\nreturn [{ json: { text } }];"), after="Claude: write brief")
    wf.add(
        http(
            "Slack: DM founder",
            "POST",
            SLACK_POST,
            credential="Slack bot token (Authorization: Bearer)",
            json_body="={{ { channel: $('Config').first().json.founderSlackId, text: $json.text } }}",
        ),
        after="Extract text",
    )
    return wf


def follow_up_radar() -> Workflow:
    wf = Workflow(
        slug="follow-up-radar",
        name="Follow-up radar (Notion → per-owner Slack nudges)",
        description="Every weekday at 4 PM, finds open follow-ups that are overdue or due tomorrow in Notion, groups them by owner, "
        "and sends each owner one short, friendly Slack nudge. Nothing falls through the cracks.",
        trigger="Schedule: weekdays 4:00 PM",
        tools=["Notion", "Slack"],
        minutes_saved_per_run=15,
        runs_per_month=21,
    )
    wf.add(schedule("Weekdays 16:00", "0 16 * * 1-5"))
    wf.add(code("Config", CONFIG_JS), after="Weekdays 16:00")
    wf.add(
        http(
            "Notion: due follow-ups",
            "POST",
            "={{ 'https://api.notion.com/v1/data_sources/' + $json.notion.followUps + '/query' }}",
            credential="Notion integration token (Authorization: Bearer)",
            headers=NOTION_HEADERS,
            json_body="={{ { filter: { and: [ { property: 'Status', status: { does_not_equal: 'Done' } }, "
            "{ property: 'Due', date: { on_or_before: $now.plus({ days: 1 }).toISODate() } } ] }, "
            "sorts: [ { property: 'Due', direction: 'ascending' } ] } }}",
        ),
        after="Config",
    )
    wf.add(
        code(
            "Group by owner",
            """
const today = $now.toISODate();
const pages = $input.first().json.results || [];
const byOwner = {};
for (const p of pages) {
  const props = p.properties;
  const title = (props['Follow-up'].title[0] || {}).plain_text || 'Untitled';
  const due = props.Due.date && props.Due.date.start;
  for (const person of props.Owner.people || [{ name: 'Unassigned', id: null }]) {
    const days = due ? Math.round((Date.parse(today) - Date.parse(due)) / 86400000) : 0;
    (byOwner[person.name] ||= []).push({ title, due, days, url: p.url });
  }
}
return Object.entries(byOwner).map(([owner, items]) => {
  items.sort((a, b) => b.days - a.days);
  const lines = items.map((i, n) => `${n + 1}. ${i.title} — ${i.days > 0 ? i.days + ' days overdue' : i.days === 0 ? 'due today' : 'due tomorrow'} · <${i.url}|open>`);
  const first = owner.split(' ')[0];
  return { json: { owner, text: `Hi ${first}, quick check on your follow-ups:\\n${lines.join('\\n')}\\nReply 'done 2' to close item 2, or 'snooze 1' to push it two days.` } };
});
""",
            notes="Deterministic on purpose: no model needed for a reminder.",
        ),
        after="Notion: due follow-ups",
    )
    wf.add(
        http(
            "Slack: nudge owner",
            "POST",
            SLACK_POST,
            credential="Slack bot token (Authorization: Bearer)",
            json_body="={{ { channel: $('Config').first().json.slackChannel, text: $json.text } }}",
            notes="Swap channel for the owner's Slack user id (users.lookupByEmail) to DM them directly.",
        ),
        after="Group by owner",
    )
    return wf


def goals_to_linear() -> Workflow:
    wf = Workflow(
        slug="goals-to-linear",
        name="Monthly goals → Linear plan (Notion → OKR planner → Slack review)",
        description="On the first Monday of the month, reads active objectives from Notion, generates a capacity-checked Linear plan, "
        "and posts the summary to Slack with a one-click approval link that pushes it to Linear.",
        trigger="Schedule: first Monday of the month, 9:00 AM",
        tools=["Notion", "OKR → Linear Planner", "Claude", "Linear", "Slack"],
        minutes_saved_per_run=180,
        runs_per_month=1,
    )
    wf.add(schedule("1st Monday 9:00", "0 9 1-7 * 1"))
    wf.add(code("Config", CONFIG_JS), after="1st Monday 9:00")
    wf.add(
        http(
            "Notion: active objectives",
            "POST",
            "={{ 'https://api.notion.com/v1/data_sources/' + $json.notion.objectives + '/query' }}",
            credential="Notion integration token (Authorization: Bearer)",
            headers=NOTION_HEADERS,
            json_body="={{ { filter: { property: 'Health', select: { is_not_empty: true } } } }}",
        ),
        after="Config",
    )
    wf.add(
        code(
            "Goals + team",
            """
const lineMap = { Clinical: 'clinical', Performance: 'performance', Company: 'company' };
const goals = ($input.first().json.results || []).map((p, i) => ({
  id: 'g' + (i + 1),
  line: lineMap[(p.properties['Business line'].select || {}).name] || 'company',
  text: (p.properties.Objective.title[0] || {}).plain_text,
})).filter(g => g.text);
const team = [
  { id: 'sam', name: 'Sam Rivera', role: 'Founder & CEO', skills: ['partnerships', 'hiring'], capacity: 6 },
  { id: 'dev', name: 'Dev Patel', role: 'CTO', skills: ['engineering', 'research', 'design'], capacity: 13 },
  { id: 'priya', name: 'Priya Natarajan', role: 'Clinical Lead', skills: ['research', 'regulatory', 'partnerships'], capacity: 10 },
  { id: 'marcus', name: 'Marcus Hale', role: 'Performance Lead', skills: ['growth', 'partnerships', 'design'], capacity: 10 },
  { id: 'javier', name: 'Javier Monestel', role: 'Executive Assistant', skills: ['ops', 'hiring', 'partnerships'], capacity: 12 },
];
return [{ json: { month: $now.toFormat('yyyy-MM'), goals, team } }];
""",
            notes="Keep the team roster here or read it from a Notion 'People' database.",
        ),
        after="Notion: active objectives",
    )
    wf.add(
        http("Plan with OKR planner", "POST", "https://okr-to-linear.vercel.app/api/plan", json_body="={{ $json }}"),
        after="Goals + team",
    )
    wf.add(
        code(
            "Capacity summary",
            """
const plan = $input.first().json;
const team = $('Goals + team').first().json.team;
const load = {};
for (const i of plan.issues) {
  const k = i.assigneeId + ':' + i.cycle;
  load[k] = (load[k] || 0) + i.estimate;
}
const over = team.flatMap(m => plan.cycles.map(c => ({ m, c, pts: load[m.id + ':' + c.number] || 0 })))
  .filter(x => x.pts > x.m.capacity)
  .map(x => `• ${x.m.name.split(' ')[0]}: ${x.pts}/${x.m.capacity} pts in cycle ${x.c.number}`);
const points = plan.issues.reduce((s, i) => s + i.estimate, 0);
const text = [
  `*${plan.month} plan ready for review:* ${plan.projects.length} project${plan.projects.length === 1 ? '' : 's'} · ${plan.issues.length} issues · ${points} pts`,
  over.length ? '*Over capacity*\\n' + over.join('\\n') : 'Everyone is within capacity ✅',
  'Approve by triggering the "Push approved plan" webhook with this plan (or review it in the planner UI).',
].join('\\n');
return [{ json: { text, plan, team } }];
""",
        ),
        after="Plan with OKR planner",
    )
    wf.add(
        http(
            "Slack: post for approval",
            "POST",
            SLACK_POST,
            credential="Slack bot token (Authorization: Bearer)",
            json_body="={{ { channel: $('Config').first().json.slackChannel, text: $json.text } }}",
        ),
        after="Capacity summary",
    )
    return wf


def investor_update_draft() -> Workflow:
    wf = Workflow(
        slug="investor-update-draft",
        name="Monthly investor update draft (Notion KRs + Linear → Claude → Notion draft)",
        description="On the last business day of the month, gathers key results from Notion and work completed in Linear, "
        "has Claude draft the investor update with every number sourced, saves it as a Notion draft and pings the founder.",
        trigger="Schedule: last weekday of the month, 2:00 PM",
        tools=["Notion", "Linear", "Claude", "Slack"],
        minutes_saved_per_run=120,
        runs_per_month=1,
    )
    wf.add(schedule("Month-end 14:00", "0 14 26-31 * 1-5"))
    wf.add(
        code(
            "Last business day?",
            """
// Cron fires on the last days of the month; continue only on the final weekday.
const today = $now;
let d = today.endOf('month');
while (d.weekday > 5) d = d.minus({ days: 1 });
return today.hasSame(d, 'day') ? $input.all() : [];
""",
        ),
        after="Month-end 14:00",
    )
    wf.add(code("Config", CONFIG_JS), after="Last business day?")
    wf.add(
        http(
            "Notion: key results",
            "POST",
            "={{ 'https://api.notion.com/v1/data_sources/' + $json.notion.keyResults + '/query' }}",
            credential="Notion integration token (Authorization: Bearer)",
            headers=NOTION_HEADERS,
            json_body="={{ { page_size: 50 } }}",
        ),
        after="Config",
    )
    wf.add(
        http(
            "Linear: completed this month",
            "POST",
            LINEAR,
            credential="Linear API key (Authorization)",
            json_body="={{ { query: 'query($after: DateTimeOrDuration!) { issues(filter: { completedAt: { gt: $after } }, first: 100) { nodes { identifier title project { name } completedAt } } }', "
            "variables: { after: $now.startOf('month').toISO() } } }}",
        ),
        after="Notion: key results",
    )
    wf.add(
        code(
            "Assemble inputs",
            """
const krs = ($('Notion: key results').first().json.results || []).map(p => ({
  key_result: (p.properties['Key result'].title[0] || {}).plain_text,
  start: p.properties.Start.number, current: p.properties.Current.number, target: p.properties.Target.number,
}));
const done = (($('Linear: completed this month').first().json.data || {}).issues || { nodes: [] }).nodes
  .map(n => `${n.identifier} ${n.title}${n.project ? ' (' + n.project.name + ')' : ''}`);
return [{ json: { month: $now.toFormat('MMMM yyyy'), key_results: krs, completed_work: done } }];
""",
        ),
        after="Linear: completed this month",
    )
    wf.add(
        claude(
            "Claude: draft update",
            "Draft the monthly investor update for a health-tech startup with Clinical and Performance lines. "
            "Format: subject line; 3-bullet TL;DR; metrics table (start → current → target, % to goal); Clinical and Performance bullets; "
            "honest lowlights if any key result is behind plan; up to 3 asks. Every number must come from the inputs. "
            "Never claim clearances, outcomes or partnerships not in the inputs. Mark uncertain items [CHECK]. 300-450 words, Markdown.",
            "$json",
        ),
        after="Assemble inputs",
    )
    wf.add(
        code(
            "To Notion blocks",
            CLAUDE_TEXT_JS
            + """
// Notion caps rich text at 2000 characters per block, so split by paragraph.
const blocks = text.split(/\\n\\n+/).map(p => ({ object: 'block', type: 'paragraph',
  paragraph: { rich_text: [{ type: 'text', text: { content: p.slice(0, 1990) } }] } }));
return [{ json: { title: `Investor update — ${$('Assemble inputs').first().json.month} (draft)`, blocks } }];
""",
        ),
        after="Claude: draft update",
    )
    wf.add(
        http(
            "Notion: save draft",
            "POST",
            f"{NOTION}/pages",
            credential="Notion integration token (Authorization: Bearer)",
            headers=NOTION_HEADERS,
            json_body="={{ { parent: { page_id: $('Config').first().json.notion.investorUpdatesPage }, "
            "properties: { title: { title: [ { text: { content: $json.title } } ] } }, children: $json.blocks } }}",
        ),
        after="To Notion blocks",
    )
    wf.add(
        http(
            "Slack: tell founder",
            "POST",
            SLACK_POST,
            credential="Slack bot token (Authorization: Bearer)",
            json_body="={{ { channel: $('Config').first().json.founderSlackId, text: 'Investor update draft is ready for your edits: ' + $json.url } }}",
        ),
        after="Notion: save draft",
    )
    return wf


TRAVEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["options", "holds", "checklist", "need_from_founder"],
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "outbound", "return", "hotel_area", "rationale"],
                "properties": {
                    "label": {"type": "string"},
                    "outbound": {"type": "string"},
                    "return": {"type": "string"},
                    "hotel_area": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        },
        "holds": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "start", "end"],
                "properties": {"title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}},
            },
        },
        "checklist": {"type": "array", "items": {"type": "string"}},
        "need_from_founder": {"type": "array", "items": {"type": "string"}},
    },
}


def travel_request() -> Workflow:
    wf = Workflow(
        slug="travel-request",
        name="Travel request → itinerary options (Webhook → Claude → Notion trip page)",
        description="The founder (or a Slack form) submits a trip request. Claude prepares two itinerary options, calendar holds, "
        "conflicts and a checklist, saved as a Notion trip page for the EA to confirm and book. Nothing is booked automatically.",
        trigger="Webhook: trip request form",
        tools=["Slack / form", "Claude", "Notion"],
        minutes_saved_per_run=45,
        runs_per_month=3,
    )
    wf.add(webhook("Trip request", "trip-request", respond_with_node=True))
    wf.add(code("Config", CONFIG_JS), after="Trip request")
    wf.add(
        claude(
            "Claude: plan trip",
            "You are an executive assistant planning a business trip for a startup founder. Produce two itinerary options "
            "(A: minimal time away, B: more buffer or lower cost) as time windows, not specific flights; calendar holds (travel, event, prep, recovery); "
            "a checklist (documents, materials such as a demo device, local transport, who to notify); and what you still need from the founder. "
            "Never present flights, prices or hotels as booked.",
            "$('Trip request').first().json.body",
            schema=TRAVEL_SCHEMA,
        ),
        after="Config",
    )
    wf.add(
        code(
            "Trip page",
            CLAUDE_TEXT_JS
            + """
const plan = JSON.parse(text);
const req = $('Trip request').first().json.body;
const para = t => ({ object: 'block', type: 'paragraph', paragraph: { rich_text: [{ type: 'text', text: { content: t.slice(0, 1990) } }] } });
const head = t => ({ object: 'block', type: 'heading_2', heading_2: { rich_text: [{ type: 'text', text: { content: t } }] } });
const todo = t => ({ object: 'block', type: 'to_do', to_do: { rich_text: [{ type: 'text', text: { content: t } }], checked: false } });
const blocks = [
  head('Options'),
  ...plan.options.map(o => para(`${o.label}: out ${o.outbound} · back ${o.return} · stay near ${o.hotel_area}. ${o.rationale}`)),
  head('Calendar holds'), ...plan.holds.map(h => para(`${h.title}: ${h.start} → ${h.end}`)),
  head('Checklist'), ...plan.checklist.map(todo),
  head('Need from the founder'), ...plan.need_from_founder.map(todo),
];
return [{ json: { title: `Trip: ${req.destination} — ${req.purpose}`, blocks, plan } }];
""",
        ),
        after="Claude: plan trip",
    )
    wf.add(
        http(
            "Notion: create trip page",
            "POST",
            f"{NOTION}/pages",
            credential="Notion integration token (Authorization: Bearer)",
            headers=NOTION_HEADERS,
            json_body="={{ { parent: { page_id: $('Config').first().json.notion.tripsParentPage }, "
            "properties: { title: { title: [ { text: { content: $json.title } } ] } }, children: $json.blocks } }}",
        ),
        after="Trip page",
    )
    wf.add(
        respond("Reply with plan", "={{ { ok: true, notion_url: $json.url, options: $('Trip page').first().json.plan.options } }}"),
        after="Notion: create trip page",
    )
    return wf


ALL = [meeting_to_actions, founder_daily_brief, follow_up_radar, goals_to_linear, investor_update_draft, travel_request]
