import type { Todo } from "./api";

interface Props {
  todos: Todo[];
  onToggle: (todo: Todo) => void;
  onDelete: (todo: Todo) => void;
}

export function TodoList({ todos, onToggle, onDelete }: Props) {
  if (todos.length === 0) {
    return <p className="empty">No tasks yet.</p>;
  }
  return (
    <ul className="todo-list">
      {todos.map((todo) => (
        <li key={todo.id} className={todo.done ? "todo-item done" : "todo-item"}>
          <label>
            <input type="checkbox" checked={todo.done} onChange={() => onToggle(todo)} />
            <span>{todo.title}</span>
          </label>
          <button type="button" aria-label={`Delete ${todo.title}`} onClick={() => onDelete(todo)}>
            Delete
          </button>
        </li>
      ))}
    </ul>
  );
}
