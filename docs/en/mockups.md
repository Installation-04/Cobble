# Mockup variants

Before the plan is generated, the assistant can draw **2 or 3 different mockups** of your main
screen, for a few cents. You pick one; the plan then follows it. Changing a mockup costs far
less than changing code.

## Using it

1. In the project, open the **Plan** tab once the spec is approved.
2. Tick **Compare mockups before planning** (off by default).
3. Click **Propose mockups**. Two or three cards appear side by side, each with a title, a short
   description and a text wireframe.
4. Click **Choose this one** on the one you prefer. You can ask for **other mockups** as often
   as you like (a new batch replaces the old one and the choice).
5. Generate the plan. While the option is on, the plan cannot be generated until a mockup is
   chosen; untick the option to skip the step.

The wireframes are plain text drawings. They are never run or interpreted as a web page, so
nothing a model writes can execute.

## API

| Request | Effect |
|---|---|
| `PATCH /api/v1/projects/{id}` `{"mockups_enabled": true}` | Turn the option on or off. |
| `GET /api/v1/projects/{id}/mockups` | The variants (`id`, `position`, `title`, `summary`, `wireframe`, `chosen`). |
| `POST /api/v1/projects/{id}/mockups/generate` `{"count": 3, "feedback": "…"}` | Queue the job (`202`). `count` is 2 or 3. Needs the option on and an approved spec (`409 mockups_disabled` / `wrong_phase`). |
| `POST /api/v1/projects/{id}/mockups/{variant_id}/choose` | Mark exactly one variant as chosen. |

Progress arrives on the project stream: `job.started` / `job.failed` (kind `mockups`) and
`mockups.updated`. The call goes through the cost router (role `planner`) and is counted in the
project costs. Design notes: `docs/decisions/0018-mockup-variants.md`.
