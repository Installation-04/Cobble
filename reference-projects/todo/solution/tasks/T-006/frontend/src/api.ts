export interface Todo {
  id: number;
  title: string;
  done: boolean;
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

export async function fetchTodos(): Promise<Todo[]> {
  const response = await call(TODOS_URL);
  return (await response.json()) as Todo[];
}
