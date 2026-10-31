import { type FormEvent, useState } from "react";

interface Props {
  onAdd: (title: string, dueDate: string | null) => Promise<void>;
}

export function AddTodo({ onAdd }: Props) {
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = title.trim();
    if (trimmed === "") {
      setError("Please enter a title.");
      return;
    }
    setError(null);
    setTitle("");
    setDueDate("");
    await onAdd(trimmed, dueDate === "" ? null : dueDate);
  }

  return (
    <form className="add-form" onSubmit={submit}>
      <label htmlFor="new-task">New task</label>
      <input
        id="new-task"
        type="text"
        value={title}
        maxLength={200}
        onChange={(event) => setTitle(event.target.value)}
      />
      <label htmlFor="new-task-due">Due date</label>
      <input
        id="new-task-due"
        type="date"
        value={dueDate}
        onChange={(event) => setDueDate(event.target.value)}
      />
      <button type="submit">Add</button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}
