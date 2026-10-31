import { useEffect, useState } from "react";

import { type Todo, fetchTodos } from "./api";
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

  return (
    <main className="page">
      <h1>To-do list</h1>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {todos === null ? <p className="loading">Loading…</p> : <TodoList todos={todos} />}
    </main>
  );
}
