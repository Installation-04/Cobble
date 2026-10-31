import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

interface Item {
  id: number;
  title: string;
  done: boolean;
  due_date: string | null;
}

function respond(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function serve(initial: Item[]) {
  const todos = [...initial];
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { title: string; due_date?: string };
      const todo = { id: todos.length + 1, done: false, due_date: null, ...body };
      todos.push(todo);
      return respond(todo, 201);
    }
    return respond(todos);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("shows the due date of a todo that has one", async () => {
  serve([
    { id: 1, title: "Renew passport", done: false, due_date: "2030-05-01" },
    { id: 2, title: "Buy milk", done: false, due_date: null },
  ]);
  render(<App />);
  expect(await screen.findByText("Due 2030-05-01")).toBeTruthy();
  expect(screen.getAllByText(/^Due \d/)).toHaveLength(1);
});

test("the form sends the due date with the title", async () => {
  const fetchMock = serve([]);
  render(<App />);
  await screen.findByText("No tasks yet.");

  fireEvent.change(screen.getByLabelText("New task"), { target: { value: "Renew passport" } });
  fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2030-05-01" } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(await screen.findByText("Due 2030-05-01")).toBeTruthy();
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    title: "Renew passport",
    due_date: "2030-05-01",
  });
});
