import { useState } from "react";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";

interface Props {
  idPrefix: string;
  label: string;
  placeholder: string;
  submitLabel: string;
  cancelLabel: string;
  busy: boolean;
  onSubmit: (feedback: string) => Promise<boolean>;
  onCancel: () => void;
}

/** Free-text "request changes" form; submit is disabled while the feedback is empty. */
export function FeedbackForm({
  idPrefix,
  label,
  placeholder,
  submitLabel,
  cancelLabel,
  busy,
  onSubmit,
  onCancel,
}: Props) {
  const [text, setText] = useState("");
  const feedback = text.trim();
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        if (feedback && (await onSubmit(feedback))) setText("");
      }}
    >
      <Label htmlFor={`${idPrefix}-feedback`}>{label}</Label>
      <Textarea
        id={`${idPrefix}-feedback`}
        data-testid={`${idPrefix}-feedback`}
        rows={3}
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {cancelLabel}
        </Button>
        <Button
          type="submit"
          size="sm"
          data-testid={`${idPrefix}-feedback-submit`}
          disabled={busy || !feedback}
        >
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
