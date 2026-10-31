import { Loader2, Send } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Markdown } from "../components/Markdown";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { cn } from "../lib";
import { FailureBanner } from "./FailureBanner";
import { PhaseStepper } from "./PhaseStepper";
import { useProjectData } from "./ProjectDataProvider";
import { SpecPanel } from "./SpecPanel";
import { useAsyncAction } from "./useAsyncAction";

export function ChatTab() {
  const { t } = useTranslation("chat");
  const { phase, paused, loaded, loadError, messages, spec, jobs, sendMessage, generateSpec } =
    useProjectData();
  const [draft, setDraft] = useState("");
  const send = useAsyncAction();
  const spec$ = useAsyncAction();
  const endRef = useRef<HTMLDivElement>(null);

  const canType = phase === "interview" && !paused;
  const content = draft.trim();
  const canSend = canType && !jobs.reply && !send.busy && content.length > 0;
  const hasUserMessage = messages.some((m) => m.role === "user");

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, jobs.reply]);

  async function submit() {
    if (!canSend) return;
    const text = content;
    setDraft("");
    const ok = await send.run(() => sendMessage(text));
    if (!ok) setDraft((current) => current || text);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  }

  const notice = paused ? t("paused") : phase !== "interview" ? t("closed") : null;
  const showSpecButton = phase === "interview" && hasUserMessage;

  return (
    <div className="flex h-full min-h-96 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
        <PhaseStepper phase={phase} />
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {spec && (
          <div className="max-h-[45%] min-h-0 shrink-0 overflow-y-auto border-b border-border lg:max-h-none lg:w-1/2 lg:border-r lg:border-b-0">
            <SpecPanel />
          </div>
        )}

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div
            role="log"
            aria-live="polite"
            aria-label={t("messages")}
            data-testid="chat-messages"
            className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4"
          >
            {loaded && messages.length === 0 && (
              <div
                data-testid="chat-empty"
                className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-center"
              >
                <h2 className="text-lg font-semibold">{t("emptyTitle")}</h2>
                <p className="text-sm text-muted-foreground">{t("emptyDescription")}</p>
              </div>
            )}
            {messages.map((m) => (
              <div
                key={m.id}
                data-testid={`chat-message-${m.role}`}
                data-pending={m.pending ? "true" : undefined}
                className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
              >
                <div
                  className={cn(
                    "max-w-[85%] rounded-lg px-3 py-2 text-sm",
                    m.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "border border-border bg-card text-card-foreground",
                    m.pending && "opacity-70",
                  )}
                >
                  <span className="sr-only">{t(`from.${m.role}`)}</span>
                  {m.role === "assistant" ? (
                    <Markdown>{m.content}</Markdown>
                  ) : (
                    <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">{m.content}</p>
                  )}
                </div>
              </div>
            ))}
            {jobs.reply && (
              <div
                role="status"
                data-testid="chat-typing"
                className="flex items-center gap-2 text-sm text-muted-foreground"
              >
                <Loader2
                  className="h-4 w-4 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
                {t("typing")}
              </div>
            )}
            <div ref={endRef} />
          </div>

          <div className="flex flex-col gap-2 border-t border-border p-3">
            {loadError != null && (
              <p role="alert" className="text-sm text-destructive" data-testid="chat-load-error">
                {t("loadError")}
              </p>
            )}
            <FailureBanner />
            {send.error && (
              <p role="alert" className="text-sm text-destructive" data-testid="chat-error">
                {send.error}
              </p>
            )}
            {spec$.error && (
              <p
                role="alert"
                className="text-sm text-destructive"
                data-testid="spec-generate-error"
              >
                {spec$.error}
              </p>
            )}
            {notice && (
              <p
                role="status"
                data-testid={paused ? "chat-paused" : "chat-closed"}
                className="text-sm text-muted-foreground"
              >
                {notice}
              </p>
            )}
            {showSpecButton && (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  data-testid="spec-generate"
                  variant="outline"
                  disabled={paused || jobs.spec || jobs.reply}
                  onClick={() => void spec$.run(() => generateSpec())}
                >
                  {jobs.spec && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                  {jobs.spec ? t("generatingSpec") : t("generateSpec")}
                </Button>
                <span className="text-xs text-muted-foreground">{t("generateSpecHint")}</span>
              </div>
            )}
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <Textarea
                data-testid="chat-input"
                aria-label={t("inputLabel")}
                placeholder={t("inputPlaceholder")}
                title={t("inputHint")}
                rows={2}
                maxLength={8000}
                value={draft}
                disabled={!canType}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
              />
              <Button
                type="submit"
                size="icon"
                data-testid="chat-send"
                disabled={!canSend}
                aria-label={t("send")}
              >
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
