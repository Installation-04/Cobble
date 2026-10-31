import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";

const MAX_LINES = 1000;
const STICK_THRESHOLD_PX = 24;

/** Monospace log, one element per line so a polite live region only announces new lines. */
export function LogView({ text, running }: { text: string; running: boolean }) {
  const { t } = useTranslation("agents");
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const { lines, first } = useMemo(() => {
    const all = text.replace(/\n$/, "").split("\n");
    const start = Math.max(0, all.length - MAX_LINES);
    return { lines: all.slice(start), first: start };
  }, [text]);

  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <div className="flex flex-col gap-2">
      {running && (
        <p data-testid="log-live" className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {t("log.live")}
        </p>
      )}
      <div
        ref={box}
        role="log"
        aria-live="polite"
        aria-label={t("log.label")}
        data-testid="task-log"
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD_PX;
        }}
        className="max-h-96 min-h-24 overflow-auto rounded-md border border-border bg-card p-2 font-mono text-xs text-card-foreground"
      >
        {text ? (
          lines.map((line, index) => (
            <div key={first + index} className="break-words whitespace-pre-wrap">
              {line || " "}
            </div>
          ))
        ) : (
          <span className="text-muted-foreground" data-testid="log-empty">
            {t("log.empty")}
          </span>
        )}
      </div>
    </div>
  );
}
