import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

function serveTodos(todos: unknown[]) {
  const fetchMock = vi.fn(
    async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify(todos), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("shows the todos returned by GET /api/todos", async () => {
  const fetchMock = serveTodos([
    { id: 1, title: "Buy milk", done: false },
    { id: 2, title: "Call the dentist", done: true },
  ]);
  render(<App />);
  expect(await screen.findByText("Buy milk")).toBeTruthy();
  expect(screen.getByText("Call the dentist")).toBeTruthy();
  expect(fetchMock.mock.calls[0][0]).toBe("api/todos");
});

test("shows an empty-state message when there is no todo", async () => {
  serveTodos([]);
  render(<App />);
  expect(await screen.findByText("No tasks yet.")).toBeTruthy();
});

test("tells the user when the todos cannot be loaded", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("boom", { status: 500 })),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toBeTruthy();
});
