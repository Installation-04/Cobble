import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Task, TaskQuestion } from "../api/types";
import { AuthProvider } from "../auth/AuthProvider";
import { setLang } from "../i18n";
import { ProjectPage } from "../pages/ProjectPage";
import { FakeEventSource, installFakeEventSource } from "../test/fakeEventSource";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { canDo, groupOf, stateTone } from "./taskState";

const ID = "p1";
let LANG: "en" | "fr" = "en";

const task = (ref: string, state: Task["state"]): Task => ({
  ref,
  title: `Title of ${ref}`,
  milestone: "M1",
  state,
  attempts: 0,
  escalated: false,
  role: "backend",
  size: "S",
  depends_on: [],
});

const question = (over: Partial<TaskQuestion> = {}): TaskQuestion => ({
  id: "q1",
  task_id: "T-001",
  task_title: "Title of T-001",
  question: "Should the amount include taxes?",
  choices: ["yes", "no"],
  status: "open",
  answer: null,
  created_at: "2026-03-01T10:00:00Z",
  answered_at: null,
  ...over,
});

interface World {
  tasks: Task[];
  questions: TaskQuestion[];
  posts: { path: string; body: unknown }[];
}

function stub(world: World, failAnswer = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? "GET").toUpperCase();
      const path = url.replace(/^\/api\/v1/, "");
      const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const json = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), {
          status,
          headers: { "Content-Type": "application/json" },
        });
      const key = `${method} ${path}`;
      if (key === "GET /folders") return json([]);
      if (key === "GET /projects")
        return json([
          {
            id: ID,
            name: "Todo",
            folder_id: null,
            created_at: "2026-01-01T00:00:00Z",
            status: "active",
            phase: "building",
            budget_usd: "10.00",
          },
        ]);
      if (key === "GET /auth/me")
        return json({ id: "u", email: "a@b.co", role: "admin", lang: LANG, theme: "system" });
      if (key === "GET /projects/p1/messages") return json([]);
      if (key === "GET /projects/p1/tasks") return json(world.tasks);
      if (key === "GET /projects/p1/questions")
        return json({
          open: world.questions.filter((q) => q.status === "open").length,
          items: world.questions,
        });
      if (/^GET \/projects\/p1\/tasks\/[\w-]+$/.test(key))
        return json({ ...world.tasks[0], runs: [] });
      if (/\/logs\?offset=\d+$/.test(key))
        return new Response("", { headers: { "X-Next-Offset": "0" } });
      if (key.endsWith("/diff")) return json({ diff: "", truncated: false });
      const answer = /^POST \/projects\/p1\/questions\/(\w+)\/(answer|skip)$/.exec(key);
      if (answer) {
        world.posts.push({ path, body });
        if (failAnswer) return json({ error: { code: "question_closed", params: {} } }, 409);
        const q = world.questions.find((item) => item.id === answer[1]);
        if (q) {
          q.status = answer[2] === "answer" ? "answered" : "skipped";
          q.answer = answer[2] === "answer" ? (body as { answer: string }).answer : null;
        }
        world.tasks = world.tasks.map((t) => (t.ref === "T-001" ? { ...t, state: "paused" } : t));
        return json(q);
      }
      return json({ error: { code: "not_found", params: {} } }, 404);
    }),
  );
}

async function renderAgents(lang: "en" | "fr" = "en") {
  await setLang(lang);
  render(
    <MemoryRouter initialEntries={[`/projects/${ID}?tab=agents`]}>
      <AuthProvider>
        <WorkspaceProvider>
          <Routes>
            <Route path="projects/:id" element={<ProjectPage />} />
          </Routes>
        </WorkspaceProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
  await screen.findByTestId("project-page");
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
}

beforeEach(() => {
  LANG = "en";
  installFakeEventSource();
});
afterEach(() => vi.unstubAllGlobals());

describe("task state helpers for waiting_human", () => {
  it("is a card that needs attention and can only be stopped or retried", () => {
    expect(groupOf("waiting_human")).toBe("attention");
    expect(stateTone("waiting_human")).toBe("warning");
    expect(canDo("stop", "waiting_human")).toBe(true);
    expect(canDo("retry", "waiting_human")).toBe(true);
    expect(canDo("pause", "waiting_human")).toBe(false);
    expect(canDo("resume", "waiting_human")).toBe(false);
  });
});

describe("questions from agents", () => {
  const fresh = (): World => ({
    tasks: [task("T-001", "waiting_human"), task("T-002", "todo")],
    questions: [question()],
    posts: [],
  });

  it("shows the badge count and the waiting card", async () => {
    stub(fresh());
    await renderAgents();
    expect(await screen.findByTestId("agents-questions-count")).toHaveTextContent(
      "1 question for you",
    );
    const card = await screen.findByTestId("agent-card-T-001");
    expect(within(card).getByTestId("card-state")).toHaveTextContent("Waiting for you");
    expect(within(card).getByTestId("card-question")).toBeVisible();
    const other = await screen.findByTestId("agent-card-T-002");
    expect(within(other).queryByTestId("card-question")).not.toBeInTheDocument();
  });

  it("answers with a choice button", async () => {
    const world = fresh();
    stub(world);
    await renderAgents();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("agent-card-T-001"));
    expect(await screen.findByTestId("question-text")).toHaveTextContent(
      "Should the amount include taxes?",
    );
    const choices = screen.getAllByTestId("question-choice");
    expect(choices.map((c) => c.textContent)).toEqual(["yes", "no"]);
    await user.click(choices[0]);
    await waitFor(() =>
      expect(world.posts).toEqual([
        { path: "/projects/p1/questions/q1/answer", body: { answer: "yes" } },
      ]),
    );
    expect(await screen.findByTestId("question-closed")).toHaveTextContent("Your answer: yes");
    expect(screen.queryByTestId("question-open")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("agents-questions-count")).toBeNull());
  });

  it("answers with free text and skips", async () => {
    const world = fresh();
    world.questions = [question({ choices: [] })];
    stub(world);
    await renderAgents();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("agent-card-T-001"));
    expect(screen.queryByTestId("question-choices")).not.toBeInTheDocument();
    expect(await screen.findByTestId("question-send")).toBeDisabled();
    await user.type(screen.getByTestId("question-input"), "  Taxes excluded ");
    await user.click(screen.getByTestId("question-send"));
    await waitFor(() =>
      expect(world.posts[0]).toEqual({
        path: "/projects/p1/questions/q1/answer",
        body: { answer: "Taxes excluded" },
      }),
    );
  });

  it("skips a question", async () => {
    const world = fresh();
    stub(world);
    await renderAgents();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("agent-card-T-001"));
    await user.click(await screen.findByTestId("question-skip"));
    await waitFor(() => expect(world.posts[0].path).toBe("/projects/p1/questions/q1/skip"));
    expect(await screen.findByTestId("question-closed")).toHaveTextContent("Skipped");
  });

  it("shows a translated error when the answer is refused", async () => {
    stub(fresh(), true);
    await renderAgents();
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("agent-card-T-001"));
    await user.click((await screen.findAllByTestId("question-choice"))[0]);
    expect(await screen.findByTestId("question-error")).toHaveTextContent(
      "already answered or skipped",
    );
  });

  it("refetches when task.question arrives and speaks French", async () => {
    LANG = "fr";
    const world: World = { tasks: [task("T-001", "implementing")], questions: [], posts: [] };
    stub(world);
    await renderAgents("fr");
    await screen.findByTestId("agent-card-T-001");
    expect(screen.queryByTestId("agents-questions-count")).not.toBeInTheDocument();
    world.tasks = [task("T-001", "waiting_human")];
    world.questions = [question()];
    FakeEventSource.last.emit("task.question", {
      task_id: "T-001",
      question_id: "q1",
      question: "Should the amount include taxes?",
      choices: ["yes", "no"],
    });
    expect(await screen.findByTestId("agents-questions-count")).toHaveTextContent(
      "1 question pour vous",
    );
    expect(screen.getByTestId("card-state")).toHaveTextContent("Attend votre réponse");
  });
});
