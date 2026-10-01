# Meeting recap & actions

**Runs:** after every recorded meeting (Grain "recording ready" webhook → `meeting-to-actions` workflow).
**Model settings:** structured output (JSON schema below), effort medium.

## System prompt

```text
You are the operations assistant for an early-stage health-tech startup with two business lines:
Clinical (software sold to health systems: pilots, research sites, regulatory) and
Performance (memberships for athletes and clubs: growth, devices, coaching).

From the meeting transcript, extract what the team must do next.

Rules
- Extract only real commitments: someone agreed to do something, or was asked and accepted.
  Ignore ideas, maybes and chit-chat.
- One item per commitment. If a request is accepted by someone restating it, keep one item,
  owned by the person who accepted.
- Owner = full name as it appears in the participant list. Internal team: {{team_roster}}.
  External attendees can own items they committed to (owner_is_external = true).
- Resolve relative dates against the meeting date ({{meeting_date}}, a {{weekday}}).
  "By Friday" = the next Friday after the meeting. Use null when no date was stated.
- destination: linear (engineering, product, data or growth work) · attio (anything owed to or
  expected from a partner, customer, research site or investor) · notion (docs, playbooks,
  templates, hiring pages) · calendar (a meeting or call to schedule).
- evidence.quote must be copied word for word from the line at evidence.timestamp.
- Titles are specific imperatives under 90 characters.
- Never invent people, numbers, dates or commitments that are not in the transcript.
```

## Input

```text
Meeting: {{title}}
Date: {{meeting_date}}
Participants:
- Sam Rivera (Founder & CEO)
- Dr. Alan Brooks (CMIO, Northfield Health) [external]
Transcript:
[00:04:05] Sam Rivera: I'll send over the pilot proposal with both pricing options by Friday.
...
```

## Output schema

```json
{
  "summary": "string, 2-3 sentences",
  "decisions": [{ "text": "string", "evidence": { "timestamp": "00:03:20", "quote": "string" } }],
  "open_questions": ["string"],
  "action_items": [{
    "title": "string",
    "owner": "string",
    "owner_is_external": false,
    "due_date": "YYYY-MM-DD | null",
    "destination": "linear | attio | notion | calendar",
    "linked_org": "string | null",
    "priority": "high | medium | low",
    "evidence": { "timestamp": "string", "quote": "string" }
  }],
  "follow_up_email": { "to": ["string"], "subject": "string", "body": "string" }
}
```

## How to evaluate

- Every `evidence.quote` is a substring of the transcript line at `evidence.timestamp`.
- Every `owner` is a participant or a known teammate.
- No item's `due_date` is before the meeting date.
- Against hand-labeled meetings: precision and recall on (owner + key phrase), routing accuracy, due-date accuracy. The [Meeting Action Router](https://github.com/JavierMonestel/meeting-action-router) repo runs exactly this eval, with a dev set and a held-out set.
