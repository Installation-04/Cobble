import { useEffect, useState } from "react";

import { AddTodo } from "./AddTodo";
import { type Todo, createTodo, fetchTodos } from "./api";
import { TodoList } from "./TodoList";

export function App() {
  const [todos, setTodos] = useState<Todo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchTodos()
      .then((items) => {
        if (active) setTodos(items);
      })
      .catch(() => {
        if (active) {
          setError("Could not load the tasks.");
          setTodos([]);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch {
      setError("Something went wrong. Please try again.");
    }
  }

  const add = (title: string) =>
    run(async () => {
      const todo = await createTodo(title);
      setTodos((current) => [...(current ?? []), todo]);
    });

  return (
    <main className="page">
      <h1>To-do list</h1>
      <AddTodo onAdd={add} />
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {todos === null ? <p className="loading">Loading…</p> : <TodoList todos={todos} />}
    </main>
  );
}
