import type { Todo } from "./api";

interface Props {
  todos: Todo[];
}

export function TodoList({ todos }: Props) {
  if (todos.length === 0) {
    return <p className="empty">No tasks yet.</p>;
  }
  return (
    <ul className="todo-list">
      {todos.map((todo) => (
        <li key={todo.id} className={todo.done ? "todo-item done" : "todo-item"}>
          <span>{todo.title}</span>
        </li>
      ))}
    </ul>
  );
}
