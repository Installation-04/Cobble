export interface Todo {
  id: number;
  title: string;
  done: boolean;
  due_date?: string | null;
}

// Relative URL: the page may be served under a prefix (the milestone previews).
const TODOS_URL = "api/todos";

async function call(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response;
}

function jsonRequest(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function fetchTodos(): Promise<Todo[]> {
  const response = await call(TODOS_URL);
  return (await response.json()) as Todo[];
}

export async function createTodo(title: string, dueDate: string | null = null): Promise<Todo> {
  const body = dueDate ? { title, due_date: dueDate } : { title };
  const response = await call(TODOS_URL, jsonRequest("POST", body));
  return (await response.json()) as Todo;
}

export async function setDone(id: number, done: boolean): Promise<Todo> {
  const response = await call(`${TODOS_URL}/${id}`, jsonRequest("PATCH", { done }));
  return (await response.json()) as Todo;
}

export async function deleteTodo(id: number): Promise<void> {
  await call(`${TODOS_URL}/${id}`, { method: "DELETE" });
}
