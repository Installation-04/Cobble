"""Write the cassettes of the scripted to-do reference flow (`todo-*.json`).

A cassette is keyed by the hash of the exact prompt, so the keys come from the REAL prompt
builders of the backend. After changing a prompt in `backend/cobble/orchestrator/prompts.py`
(or the plan schema), regenerate everything with one command:

    cd providers/fake-llm && uv run python scripts/make_todo_cassettes.py

`--check` only verifies that the files on disk are up to date (exit status 1 otherwise).

The scripted flow, once per user language (`en`, `fr`):
  1. interview turn 1 (user message USER_MESSAGES[lang][0]) -> assistant question,
  2. interview turn 2 (user message USER_MESSAGES[lang][1]) -> assistant summary,
  3. spec generation (no feedback) -> Markdown spec,
  4. plan generation from that spec -> a valid plan (3 milestones, 11 tasks),
and two plan-retry scenarios on dedicated specs (the spec text is part of the key):
  - "retry": an invalid plan (a task without acceptance criteria, a task of size L) followed
    by a valid one, after the retry prompt that lists the validation errors,
  - "exhausted": three invalid plans in a row (the planner gives up: plan_invalid).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASSETTES = HERE.parent / "cassettes"
sys.path.insert(0, str(HERE.parents[2] / "backend"))
sys.path.insert(0, str(HERE.parent))  # fake_llm, also when run outside its virtualenv

from fake_llm.cassettes import Cassette, Response, request_key  # noqa: E402

from cobble.orchestrator import prompts  # noqa: E402
from cobble.orchestrator.plan_schema import PlanInvalid, parse_plan_reply  # noqa: E402

MODEL = "fake"
PREFIX = "todo-"
LANGS = ("en", "fr")

USER_MESSAGES = {
    "en": (
        "I want a simple to-do list app",
        "Just for me, on my phone. I want to add tasks, tick them off and delete them. "
        "No account needed.",
    ),
    "fr": (
        "Je veux une application simple de liste de tâches",
        "Juste pour moi, sur mon téléphone. Je veux ajouter des tâches, les cocher et les "
        "supprimer. Pas de compte.",
    ),
}

ASSISTANT_REPLIES = {
    "en": (
        "Nice idea! Three quick questions. Will only you use it, or several people? Which "
        "device: phone, computer, or both? Does a task need more than a title and a done "
        "checkbox (due date, category)? I suggest a simple stack: a FastAPI backend with a "
        "light web page.",
        "Perfect. Summary: a personal to-do list for your phone, to add, tick off and delete "
        "tasks, with no account. Stack: FastAPI plus a simple web page. You can now generate "
        "the specification.",
    ),
    "fr": (
        "Belle idée! Trois questions rapides. Sera-t-elle utilisée par vous seul ou par "
        "plusieurs personnes? Sur quel appareil: téléphone, ordinateur ou les deux? Une tâche "
        "a-t-elle besoin de plus qu'un titre et d'une case à cocher (date d'échéance, "
        "catégorie)? Je propose une pile simple: un serveur FastAPI avec une page web légère.",
        "Parfait. Résumé: une liste de tâches personnelle pour votre téléphone, pour ajouter, "
        "cocher et supprimer des tâches, sans compte. Pile: FastAPI et une page web simple. "
        "Vous pouvez maintenant générer la spécification.",
    ),
}

SPECS = {
    "en": """# Simple to-do list

A personal to-do list used from a phone. One user, no account.

## Features
- Add a task with a title.
- List all tasks, oldest first.
- Tick a task as done, or untick it.
- Delete a task.

## Screens
- A single page: a form to add a task, then the list.
- Each task has a checkbox and a delete button.

## Data model
- Todo: id (integer), title (text, 1 to 200 characters), done (boolean, false by default).

## Constraints
- FastAPI backend with a simple web page; data survives a restart.
- Usable on a phone screen (375 px wide).

## Out of scope
- Accounts, sharing, due dates, categories, notifications.
""",
    "fr": """# Liste de tâches simple

Une liste de tâches personnelle utilisée depuis un téléphone. Un seul utilisateur, sans compte.

## Fonctionnalités
- Ajouter une tâche avec un titre.
- Lister toutes les tâches, de la plus ancienne à la plus récente.
- Cocher une tâche comme faite, ou la décocher.
- Supprimer une tâche.

## Écrans
- Une seule page: un formulaire d'ajout, puis la liste.
- Chaque tâche a une case à cocher et un bouton de suppression.

## Modèle de données
- Tâche: id (entier), titre (texte, 1 à 200 caractères), faite (booléen, faux par défaut).

## Contraintes
- Serveur FastAPI avec une page web simple; les données survivent à un redémarrage.
- Utilisable sur un écran de téléphone (375 px de large).

## Hors périmètre
- Comptes, partage, échéances, catégories, notifications.
""",
}

# (id, milestone, depends_on, files, tests, size, role, acceptance); titles are per language.
# The files match reference-projects/todo/solution (see scripts/make_agent_cassettes.py): tasks
# that share a file are ordered by depends_on, because a cassette answer is the whole file.
_TASKS: list[tuple[Any, ...]] = [
    (
        "T-001",
        "M1",
        [],
        ["app/main.py", "tests/test_health.py"],
        "tests/test_health.py",
        "S",
        "backend",
        ['GET /api/health returns 200 with {"status": "ok"}'],
    ),
    (
        "T-002",
        "M1",
        ["T-001"],
        ["app/models.py", "app/db.py", "tests/test_models.py"],
        "tests/test_models.py",
        "S",
        "backend",
        [
            "A todo has an id, a title and a done flag that is false by default",
            "A stored todo can be read back with the same values",
        ],
    ),
    (
        "T-003",
        "M1",
        ["T-002"],
        ["app/api/todos.py", "tests/test_todos_create_list.py"],
        "tests/test_todos_create_list.py",
        "M",
        "backend",
        [
            "POST /api/todos with a title returns 201 and the created todo",
            "POST /api/todos with an empty title returns 422",
            "GET /api/todos returns all todos, oldest first",
        ],
    ),
    (
        "T-004",
        "M1",
        ["T-002"],
        ["app/api/todo_item.py", "tests/test_todo_item.py"],
        "tests/test_todo_item.py",
        "S",
        "backend",
        [
            "PATCH /api/todos/{id} with done=true returns 200 and the todo marked done",
            "DELETE /api/todos/{id} returns 204 and the todo is no longer listed",
            "PATCH or DELETE on an unknown id returns 404",
        ],
    ),
    (
        "T-005",
        "M2",
        ["T-001"],
        [
            "app/api/web.py",
            "frontend/index.html",
            "frontend/vite.config.ts",
            "frontend/src/App.tsx",
            "frontend/src/App.test.tsx",
            "tests/test_web_served.py",
        ],
        "tests/test_web_served.py",
        "S",
        "frontend",
        [
            "GET / returns 200 with the HTML page",
            "The page contains the application title",
        ],
    ),
    (
        "T-006",
        "M2",
        ["T-003", "T-005"],
        [
            "frontend/src/api.ts",
            "frontend/src/TodoList.tsx",
            "frontend/src/App.tsx",
            "frontend/src/list.test.tsx",
        ],
        "frontend/src/list.test.tsx",
        "S",
        "frontend",
        [
            "The page shows the todos returned by GET /api/todos",
            "With no todo, the page shows an empty-state message",
        ],
    ),
    (
        "T-007",
        "M2",
        ["T-006"],
        [
            "frontend/src/AddTodo.tsx",
            "frontend/src/api.ts",
            "frontend/src/App.tsx",
            "frontend/src/add.test.tsx",
        ],
        "frontend/src/add.test.tsx",
        "M",
        "frontend",
        [
            "Submitting the form with a title creates the todo and shows it in the list",
            "Submitting an empty title sends no request and shows an error message",
        ],
    ),
    (
        "T-008",
        "M2",
        ["T-004", "T-007"],
        [
            "frontend/src/TodoList.tsx",
            "frontend/src/api.ts",
            "frontend/src/App.tsx",
            "frontend/src/actions.test.tsx",
        ],
        "frontend/src/actions.test.tsx",
        "S",
        "frontend",
        [
            "Clicking a checkbox toggles the todo and keeps the new state after a reload",
            "Clicking the delete button removes the todo from the list",
        ],
    ),
    (
        "T-009",
        "M3",
        ["T-003"],
        ["app/config.py", "app/db.py", ".gitignore", "tests/test_persistence.py"],
        "tests/test_persistence.py",
        "S",
        "backend",
        ["Todos created before an application restart are still listed after it"],
    ),
    (
        "T-010",
        "M3",
        ["T-006"],
        [
            "frontend/src/style.css",
            "frontend/src/main.tsx",
            "frontend/vite.config.ts",
            "frontend/src/style.test.ts",
        ],
        "frontend/src/style.test.ts",
        "S",
        "frontend",
        [
            "At a width of 375 px the page has no horizontal scroll",
            "Buttons and checkboxes are at least 44 px tall",
        ],
    ),
    (
        "T-011",
        "M3",
        ["T-008", "T-009"],
        ["README.md", "tests/test_docs.py"],
        "tests/test_docs.py",
        "S",
        "docs",
        ["The README explains how to start the application and how to run the tests"],
    ),
]

_TITLES = {
    "en": {
        "M1": "Task API",
        "M2": "Web page",
        "M3": "Polish and delivery",
        "T-001": "Application skeleton and health endpoint",
        "T-002": "Todo model and storage",
        "T-003": "Create and list todos",
        "T-004": "Toggle and delete a todo",
        "T-005": "Web page skeleton",
        "T-006": "Show the todo list",
        "T-007": "Add-a-todo form",
        "T-008": "Tick and delete from the page",
        "T-009": "Keep data across restarts",
        "T-010": "Phone-friendly layout",
        "T-011": "Usage documentation",
    },
    "fr": {
        "M1": "API des tâches",
        "M2": "Page web",
        "M3": "Finitions et livraison",
        "T-001": "Squelette de l'application et point de santé",
        "T-002": "Modèle et stockage des tâches",
        "T-003": "Créer et lister les tâches",
        "T-004": "Cocher et supprimer une tâche",
        "T-005": "Squelette de la page web",
        "T-006": "Afficher la liste des tâches",
        "T-007": "Formulaire d'ajout",
        "T-008": "Cocher et supprimer depuis la page",
        "T-009": "Conserver les données après redémarrage",
        "T-010": "Mise en page pour téléphone",
        "T-011": "Documentation d'utilisation",
    },
}


def valid_plan(lang: str) -> dict[str, Any]:
    titles = _TITLES[lang]
    return {
        "milestones": [{"id": m, "title": titles[m]} for m in ("M1", "M2", "M3")],
        "tasks": [
            {
                "id": tid,
                "title": titles[tid],
                "milestone": milestone,
                "depends_on": depends_on,
                "files": files,
                "acceptance": acceptance,
                "tests": tests,
                "size": size,
                "role": role,
            }
            for tid, milestone, depends_on, files, tests, size, role, acceptance in _TASKS
        ],
    }


def invalid_plan(lang: str, variant: int) -> dict[str, Any]:
    """Three different rejected plans (used by the retry and exhausted scenarios)."""
    plan = valid_plan(lang)
    tasks = plan["tasks"]
    if variant == 1:  # a task without acceptance criteria, a task of size L
        tasks[2]["acceptance"] = []
        tasks[3]["size"] = "L"
    elif variant == 2:  # an absolute path, a size outside S/M
        tasks[0]["files"] = ["/etc/app/main.py"]
        tasks[1]["size"] = "XL"
    else:  # nothing to do
        plan["tasks"] = []
    return plan


def _fenced(plan: dict[str, Any]) -> str:
    return "```json\n" + json.dumps(plan, indent=2, ensure_ascii=False) + "\n```"


def _bare(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False)


def _cassette(messages: list[dict[str, Any]], content: str) -> Cassette:
    return Cassette(
        key=request_key(MODEL, messages),
        response=Response(content=content),
        model=MODEL,
        messages=[{"role": m["role"], "content": m["content"]} for m in messages],
    )


def retry_spec(scenario: str) -> str:
    return f"# Plan retry scenario: {scenario}\n\nA specification used only to test plan retries."


def _plan_scenario(lang: str, scenario: str, replies: list[str], out: dict[str, Cassette]) -> None:
    base = prompts.plan_messages(retry_spec(scenario), lang)
    messages = base
    for number, reply in enumerate(replies, start=1):
        out[f"todo-{lang}-plan-{scenario}-{number}"] = _cassette(messages, reply)
        try:
            parse_plan_reply(reply)
        except PlanInvalid as exc:
            messages = prompts.retry_messages(base, reply, exc.errors)


def build_cassettes() -> dict[str, Cassette]:
    """File stem -> cassette, for every scripted flow."""
    out: dict[str, Cassette] = {}
    for lang in LANGS:
        user1, user2 = USER_MESSAGES[lang]
        reply1, reply2 = ASSISTANT_REPLIES[lang]
        history: list[dict[str, Any]] = [{"role": "user", "content": user1}]
        out[f"todo-{lang}-interview-1"] = _cassette(
            prompts.interview_messages(history, lang), reply1
        )
        history += [
            {"role": "assistant", "content": reply1},
            {"role": "user", "content": user2},
        ]
        out[f"todo-{lang}-interview-2"] = _cassette(
            prompts.interview_messages(history, lang), reply2
        )
        history.append({"role": "assistant", "content": reply2})
        spec = SPECS[lang].strip()
        out[f"todo-{lang}-spec"] = _cassette(prompts.spec_messages(history, lang), spec)
        out[f"todo-{lang}-plan"] = _cassette(
            prompts.plan_messages(spec, lang), _bare(valid_plan(lang))
        )
        _plan_scenario(
            lang, "retry", [_fenced(invalid_plan(lang, 1)), _bare(valid_plan(lang))], out
        )
        _plan_scenario(
            lang,
            "exhausted",
            [_bare(invalid_plan(lang, v)) for v in (1, 2, 3)],
            out,
        )
    return out


def render(cassette: Cassette) -> str:
    return json.dumps(cassette.to_json(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    wanted = {f"{stem}.json": render(c) for stem, c in build_cassettes().items()}
    existing = {p.name for p in CASSETTES.glob(f"{PREFIX}*.json")}
    if "--check" in argv:
        stale = sorted(
            name
            for name, text in wanted.items()
            if not (CASSETTES / name).exists() or (CASSETTES / name).read_text("utf-8") != text
        )
        stale += sorted(existing - set(wanted))
        for name in stale:
            print(f"out of date: {name}", file=sys.stderr)
        return 1 if stale else 0
    CASSETTES.mkdir(parents=True, exist_ok=True)
    for name in existing - set(wanted):
        (CASSETTES / name).unlink()
    for name, text in wanted.items():
        (CASSETTES / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(wanted)} cassettes to {CASSETTES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
