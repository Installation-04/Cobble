import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

interface Item {
  id: number;
  title: string;
  done: boolean;
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
      const body = JSON.parse(String(init.body)) as { title: string };
      const todo = { id: todos.length + 1, title: body.title, done: false };
      todos.push(todo);
      return respond(todo, 201);
    }
    return respond(todos);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function posts(fetchMock: ReturnType<typeof serve>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("submitting a title creates the todo and shows it in the list", async () => {
  const fetchMock = serve([{ id: 1, title: "Buy milk", done: false }]);
  render(<App />);
  await screen.findByText("Buy milk");

  fireEvent.change(screen.getByLabelText("New task"), { target: { value: "Walk the dog" } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  expect(await screen.findByText("Walk the dog")).toBeTruthy();
  expect(screen.getByText("Buy milk")).toBeTruthy();
  const [[url, init]] = posts(fetchMock);
  expect(url).toBe("api/todos");
  expect(JSON.parse(String(init?.body))).toEqual({ title: "Walk the dog" });
});

test("the title field is cleared after adding", async () => {
  serve([]);
  render(<App />);
  const input = screen.getByLabelText("New task") as HTMLInputElement;
  fireEvent.change(input, { target: { value: "Walk the dog" } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
  await screen.findByText("Walk the dog");
  expect(input.value).toBe("");
});

test("submitting an empty title sends no request and shows an error message", async () => {
  const fetchMock = serve([]);
  render(<App />);
  await screen.findByText("No tasks yet.");

  fireEvent.change(screen.getByLabelText("New task"), { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));

  expect((await screen.findByRole("alert")).textContent).toBe("Please enter a title.");
  expect(posts(fetchMock)).toHaveLength(0);
});
