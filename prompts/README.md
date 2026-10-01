# Prompt library

Production prompts behind the automations in this repo. Each one is written as a **contract**: what goes in, what must come out, what the model must never do, and how to check the result. They are model-agnostic but tuned for Claude (system prompt + structured output).

| Prompt | Used by | Output |
|---|---|---|
| [Meeting recap & actions](meeting-recap-and-actions.md) | `meeting-to-actions` workflow | JSON: summary, decisions, action items with evidence |
| [Founder daily brief](founder-daily-brief.md) | `founder-daily-brief` workflow | Markdown brief for Slack |
| [Follow-up nudge](follow-up-nudge.md) | `follow-up-radar` workflow | Short Slack nudge per owner |
| [Investor update draft](investor-update-draft.md) | `investor-update-draft` workflow | Markdown draft for review |
| [Travel planner](travel-planner.md) | `travel-request` workflow | JSON: itinerary options, holds to place, checklist |
| [Inbox triage](inbox-triage.md) | Manual / Gmail add-on | JSON: action per thread + draft replies |

## Principles used in every prompt

1. **Ground everything.** Every fact must come from the input; quotes are copied verbatim. If something is missing, the model says so instead of guessing.
2. **Structured where software reads it.** When another system consumes the output, the output is JSON validated against a schema.
3. **Humans approve outward actions.** Prompts draft messages and plans; sending, booking and paying stay human clicks.
4. **Short beats complete.** A founder reads a brief in 60 seconds. Every prompt has an explicit length budget.
5. **Each prompt ships with checks.** The "How to evaluate" section lists the assertions used to test it on sample inputs.
