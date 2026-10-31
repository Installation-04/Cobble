import { type FormEvent, useState } from "react";

interface Props {
  onAdd: (title: string) => Promise<void>;
}

export function AddTodo({ onAdd }: Props) {
  const [title, setTitle] = useState("");
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
    await onAdd(trimmed);
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
      <button type="submit">Add</button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}
