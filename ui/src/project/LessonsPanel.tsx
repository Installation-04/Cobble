import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../api/client";
import { errorMessage } from "../api/errors";
import { lessonsApi, type Lesson } from "../api/lessons";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { useFetched } from "./useFetched";

const MAX_ACTIVE = 20; // keep in step with `MAX_ACTIVE` of backend/cobble/scheduler/lessons.py
const MAX_TEXT = 300;

function LessonRow({
  lesson,
  onSave,
  onToggle,
  onDelete,
}: {
  lesson: Lesson;
  onSave: (text: string) => Promise<void>;
  onToggle: (active: boolean) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const { t } = useTranslation("lessons");
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <li
      data-testid={`lesson-${lesson.id}`}
      data-active={lesson.active}
      className="flex flex-col gap-2 rounded-md border border-border bg-background p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge>{t(`source.${lesson.source}`)}</Badge>
        {lesson.task_ref && <span className="font-mono">{lesson.task_ref}</span>}
        <span>{t("hits", { count: lesson.hits })}</span>
        {lesson.injected && <Badge tone="primary">{t("injected")}</Badge>}
        {!lesson.active && <Badge tone="warning">{t("disabled")}</Badge>}
      </div>
      {draft === null ? (
        <p className="break-words whitespace-pre-wrap" data-testid="lesson-text">
          {lesson.text}
        </p>
      ) : (
        <textarea
          aria-label={t("editLabel")}
          data-testid="lesson-edit"
          value={draft}
          maxLength={MAX_TEXT}
          rows={3}
          onChange={(e) => setDraft(e.target.value)}
          className="w-full rounded-md border border-input bg-background p-2 text-sm text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        />
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={lesson.active}
            aria-label={t("enabledLabel", { text: lesson.text })}
            data-testid="lesson-toggle"
            onChange={(e) => void onToggle(e.target.checked)}
          />
        </label>
        {draft === null ? (
          <Button size="sm" variant="outline" onClick={() => setDraft(lesson.text)}>
            {t("edit")}
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              data-testid="lesson-save"
              disabled={!draft.trim()}
              onClick={() => void onSave(draft).then(() => setDraft(null))}
            >
              {t("save")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
              {t("cancel")}
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant="ghost"
          data-testid="lesson-delete"
          aria-label={t("deleteLabel", { text: lesson.text })}
          onClick={() => void onDelete()}
        >
          {t("delete")}
        </Button>
      </div>
    </li>
  );
}

/**
 * Lessons learned of the project (ADR 0026): what agents got wrong here, which the next agents
 * are told. The owner can read, edit, disable, delete and add lessons. Text only, never markup.
 */
export function LessonsPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation(["lessons", "errors"]);
  const {
    data,
    error: loadError,
    reload,
  } = useFetched(() => lessonsApi.list(projectId), projectId);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const act = async (action: () => Promise<unknown>): Promise<void> => {
    setError(null);
    try {
      await action();
      reload();
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "lessons_full"
          ? t("lessons:full", { max: MAX_ACTIVE })
          : errorMessage(t, e),
      );
    }
  };

  const lessons = data ?? [];
  return (
    <section
      aria-labelledby="lessons-title"
      data-testid="lessons-panel"
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="lessons-title" className="text-sm font-semibold">
        {t("lessons:title")}
      </h3>
      <p className="text-xs text-muted-foreground">
        {t("lessons:description", { max: MAX_ACTIVE })}
      </p>
      {loadError != null && data === null && (
        <p className="text-sm text-destructive" data-testid="lessons-load-error">
          {t("lessons:loadError")}
        </p>
      )}
      {data !== null && lessons.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="lessons-empty">
          {t("lessons:empty")}
        </p>
      )}
      {lessons.length > 0 && (
        <ul className="flex flex-col gap-2" data-testid="lessons-list">
          {lessons.map((lesson) => (
            <LessonRow
              key={lesson.id}
              lesson={lesson}
              onSave={(next) => act(() => lessonsApi.update(projectId, lesson.id, { text: next }))}
              onToggle={(active) => act(() => lessonsApi.update(projectId, lesson.id, { active }))}
              onDelete={() => act(() => lessonsApi.remove(projectId, lesson.id))}
            />
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const value = text.trim();
          if (!value) return;
          void act(() => lessonsApi.add(projectId, value)).then(() => setText(""));
        }}
      >
        <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs">
          {t("lessons:addLabel")}
          <input
            type="text"
            value={text}
            maxLength={MAX_TEXT}
            placeholder={t("lessons:addPlaceholder")}
            data-testid="lesson-new"
            onChange={(e) => setText(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          />
        </label>
        <Button type="submit" size="sm" data-testid="lesson-add" disabled={!text.trim()}>
          {t("lessons:add")}
        </Button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="lessons-error">
          {error}
        </p>
      )}
    </section>
  );
}
