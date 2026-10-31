import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** A tiny in-memory server: what the page sees after a reload is what it changed before. */
function serve(initial: Item[]) {
  let todos = [...initial];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const id = Number(url.split("/")[2]);
    if (init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as { done: boolean };
      todos = todos.map((todo) => (todo.id === id ? { ...todo, done: body.done } : todo));
      return respond(todos.find((todo) => todo.id === id));
    }
    if (init?.method === "DELETE") {
      todos = todos.filter((todo) => todo.id !== id);
      return new Response(null, { status: 204 });
    }
    return respond(todos);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("clicking a checkbox toggles the todo and the new state survives a reload", async () => {
  const fetchMock = serve([{ id: 1, title: "Buy milk", done: false }]);
  const first = render(<App />);
  const checkbox = (await screen.findByRole("checkbox", { name: "Buy milk" })) as HTMLInputElement;
  expect(checkbox.checked).toBe(false);

  fireEvent.click(checkbox);
  await waitFor(() => expect(checkbox.checked).toBe(true));
  const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
  expect(patch?.[0]).toBe("api/todos/1");
  expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ done: true });

  first.unmount();
  render(<App />);
  const reloaded = (await screen.findByRole("checkbox", { name: "Buy milk" })) as HTMLInputElement;
  expect(reloaded.checked).toBe(true);
});

test("clicking a checked todo unticks it", async () => {
  serve([{ id: 4, title: "Pay the rent", done: true }]);
  render(<App />);
  const checkbox = (await screen.findByRole("checkbox", { name: "Pay the rent" })) as HTMLInputElement;
  fireEvent.click(checkbox);
  await waitFor(() => expect(checkbox.checked).toBe(false));
});

test("clicking the delete button removes the todo from the list", async () => {
  const fetchMock = serve([
    { id: 1, title: "Buy milk", done: false },
    { id: 2, title: "Call the dentist", done: false },
  ]);
  render(<App />);
  await screen.findByText("Buy milk");

  fireEvent.click(screen.getByRole("button", { name: "Delete Buy milk" }));

  await waitFor(() => expect(screen.queryByText("Buy milk")).toBeNull());
  expect(screen.getByText("Call the dentist")).toBeTruthy();
  const removal = fetchMock.mock.calls.find(([, init]) => init?.method === "DELETE");
  expect(removal?.[0]).toBe("api/todos/1");
});
