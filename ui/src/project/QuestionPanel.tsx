import { MessageCircleQuestion } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TaskQuestion } from "../api/types";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { useProjectData } from "./ProjectDataProvider";
import { useAsyncAction } from "./useAsyncAction";

/** Keep in step with the API cap (`ANSWER_CHARS`). */
const MAX_ANSWER = 2000;

function OpenQuestion({ question }: { question: TaskQuestion }) {
  const { t } = useTranslation("agents");
  const { answerQuestion } = useProjectData();
  const act = useAsyncAction();
  const [text, setText] = useState("");
  const [sending, setSending] = useState<"send" | "skip" | null>(null);

  const submit = (answer: string | null) => {
    setSending(answer === null ? "skip" : "send");
    void act.run(() => answerQuestion(question.id, answer)).finally(() => setSending(null));
  };

  return (
    <div
      data-testid="question-open"
      className="flex flex-col gap-3 rounded-lg border border-warning p-3 text-sm"
    >
      <div className="flex items-center gap-2 font-semibold">
        <MessageCircleQuestion className="h-4 w-4 text-warning" aria-hidden="true" />
        <h3>{t("questions.title")}</h3>
        <Badge tone="warning">{t("questions.waiting")}</Badge>
      </div>
      <p data-testid="question-text" className="whitespace-pre-wrap">
        {question.question}
      </p>
      <p className="text-xs text-muted-foreground">{t("questions.hint")}</p>
      {question.choices.length > 0 && (
        <div
          role="group"
          aria-label={t("questions.choicesLabel")}
          className="flex flex-wrap gap-2"
          data-testid="question-choices"
        >
          {question.choices.map((choice) => (
            <Button
              key={choice}
              size="sm"
              variant="outline"
              disabled={act.busy}
              data-testid="question-choice"
              onClick={() => submit(choice)}
            >
              {choice}
            </Button>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-2">
        <label htmlFor={`answer-${question.id}`} className="text-xs font-medium">
          {t("questions.answerLabel")}
        </label>
        <Textarea
          id={`answer-${question.id}`}
          data-testid="question-input"
          rows={3}
          maxLength={MAX_ANSWER}
          value={text}
          placeholder={t("questions.placeholder")}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={act.busy}
            data-testid="question-skip"
            onClick={() => submit(null)}
          >
            {sending === "skip" ? t("questions.sending") : t("questions.skip")}
          </Button>
          <Button
            size="sm"
            disabled={act.busy || text.trim() === ""}
            data-testid="question-send"
            onClick={() => submit(text.trim())}
          >
            {sending === "send" ? t("questions.sending") : t("questions.send")}
          </Button>
        </div>
      </div>
      {act.error && (
        <p role="alert" data-testid="question-error" className="text-sm text-destructive">
          {act.error}
        </p>
      )}
    </div>
  );
}

/** The questions of one task in the drawer: the open one to answer, earlier ones as history. */
export function QuestionPanel({ taskRef }: { taskRef: string }) {
  const { t } = useTranslation("agents");
  const { questions } = useProjectData();
  const mine = questions.filter((q) => q.task_id === taskRef);
  const open = mine.find((q) => q.status === "open");
  const closed = mine.filter((q) => q.status !== "open");
  if (!open && closed.length === 0) return null;
  return (
    <section className="flex flex-col gap-2" data-testid="question-panel">
      {open && <OpenQuestion key={open.id} question={open} />}
      {closed.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <h3 className="text-xs font-semibold text-muted-foreground">{t("questions.history")}</h3>
          <ul className="flex flex-col gap-1">
            {closed.map((q) => (
              <li key={q.id} data-testid="question-closed" className="rounded-md bg-muted p-2">
                <p className="whitespace-pre-wrap">{q.question}</p>
                <p className="text-xs text-muted-foreground">
                  {q.status === "answered"
                    ? t("questions.answered", { answer: q.answer ?? "" })
                    : t("questions.skipped")}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
