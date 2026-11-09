import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Lesson } from "../api/lessons";
import { setLang } from "../i18n";
import { mockFetch, renderApp, type Handler } from "../test/utils";
import { LessonsPanel } from "./LessonsPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

const LESSON: Lesson = {
  id: "l1",
  text: "CI failed on tests/test_a.py::test_x: <b>assert 1 == 2</b>",
  source: "ci_failure",
  task_ref: "T-001",
  active: true,
  hits: 2,
  created_at: "2026-01-01T00:00:00Z",
  injected: true,
};

function routes(extra: Record<string, Handler> = {}) {
  let rows: Lesson[] = [LESSON];
  const handlers: Record<string, Handler> = {
    "GET /projects/p1/lessons": () => ({ body: rows }),
    "POST /projects/p1/lessons": ({ body }) => {
      const created = {
        ...LESSON,
        id: "l2",
        text: (body as { text: string }).text,
        source: "manual" as const,
      };
      rows = [created, ...rows];
      return { status: 201, body: created };
    },
    "PATCH /projects/p1/lessons/l1": ({ body }) => {
      rows = rows.map((r) => (r.id === "l1" ? { ...r, ...(body as object) } : r));
      return { body: rows[0] };
    },
    "DELETE /projects/p1/lessons/l1": () => {
      rows = [];
      return { status: 204 };
    },
    ...extra,
  };
  return mockFetch(handlers);
}

describe("the lessons panel", () => {
  it("lists lessons as plain text with their source and visibility", async () => {
    routes();
    await renderApp(<LessonsPanel projectId="p1" />);
    const row = await screen.findByTestId("lesson-l1");
    expect(within(row).getByTestId("lesson-text")).toHaveTextContent("<b>assert 1 == 2</b>");
    expect(row.querySelector("b")).toBeNull(); // never rendered as markup
    expect(within(row).getByText("CI failure")).toBeInTheDocument();
    expect(within(row).getByText("Shown to agents")).toBeInTheDocument();
    expect(within(row).getByText("Seen 2 times")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    routes({ "GET /projects/p1/lessons": () => ({ body: [] }) });
    await renderApp(<LessonsPanel projectId="p1" />);
    expect(await screen.findByTestId("lessons-empty")).toBeInTheDocument();
  });

  it("adds, edits, disables and deletes a lesson", async () => {
    const user = userEvent.setup();
    const { calls } = routes();
    await renderApp(<LessonsPanel projectId="p1" />);
    await screen.findByTestId("lesson-l1");

    await user.type(screen.getByTestId("lesson-new"), "Use uv");
    await user.click(screen.getByTestId("lesson-add"));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ text: "Use uv" }),
    );
    expect(await screen.findByTestId("lesson-l2")).toBeInTheDocument();

    const row = screen.getByTestId("lesson-l1");
    await user.click(within(row).getByRole("button", { name: "Edit" }));
    const box = within(row).getByTestId("lesson-edit");
    await user.clear(box);
    await user.type(box, "New text");
    await user.click(within(row).getByTestId("lesson-save"));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ text: "New text" }),
    );

    await user.click(within(screen.getByTestId("lesson-l1")).getByTestId("lesson-toggle"));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ active: false }),
    );

    await user.click(within(screen.getByTestId("lesson-l1")).getByTestId("lesson-delete"));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    await waitFor(() => expect(screen.queryByTestId("lesson-l1")).toBeNull());
  });

  it("explains when too many lessons are active, in French too", async () => {
    const user = userEvent.setup();
    routes({
      "POST /projects/p1/lessons": () => ({
        status: 409,
        body: { error: { code: "lessons_full", params: { max: 20 } } },
      }),
    });
    await renderApp(<LessonsPanel projectId="p1" />);
    await screen.findByTestId("lesson-l1");
    await user.type(screen.getByTestId("lesson-new"), "x");
    await user.click(screen.getByTestId("lesson-add"));
    expect(await screen.findByTestId("lessons-error")).toHaveTextContent("already 20 active");
    await setLang("fr");
    expect(await screen.findByText("Leçons apprises")).toBeInTheDocument();
  });
});
