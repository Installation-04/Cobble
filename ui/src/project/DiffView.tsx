import { useTranslation } from "react-i18next";
import { cn } from "../lib";

export type DiffLineKind = "added" | "removed" | "hunk" | "meta" | "context";

export function classifyLine(line: string): DiffLineKind {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("diff ") || line.startsWith("index ")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "added";
  if (line.startsWith("-")) return "removed";
  return "context";
}

const STYLES: Record<DiffLineKind, string> = {
  added: "bg-diff-added text-diff-added-foreground",
  removed: "bg-diff-removed text-diff-removed-foreground",
  hunk: "bg-muted text-muted-foreground",
  meta: "font-semibold text-foreground",
  context: "text-foreground",
};

/** Unified diff: the +/- prefixes stay in the text, so color is never the only cue. */
export function DiffView({ diff, truncated }: { diff: string; truncated: boolean }) {
  const { t } = useTranslation("agents");
  if (!diff.trim()) {
    return (
      <p data-testid="diff-empty" className="text-sm text-muted-foreground">
        {t("diff.empty")}
      </p>
    );
  }
  const lines = diff.replace(/\n$/, "").split("\n");
  return (
    <div className="flex flex-col gap-2">
      {truncated && (
        <p data-testid="diff-truncated" role="status" className="text-sm text-warning">
          {t("diff.truncated")}
        </p>
      )}
      <pre
        data-testid="diff-view"
        tabIndex={0}
        aria-label={t("diff.label")}
        className="max-h-96 overflow-auto rounded-md border border-border bg-card font-mono text-xs"
      >
        {lines.map((line, index) => {
          const kind = classifyLine(line);
          return (
            <span
              key={index}
              data-testid="diff-line"
              data-kind={kind}
              className={cn("block min-w-full px-2 whitespace-pre", STYLES[kind])}
            >
              {line || " "}
            </span>
          );
        })}
      </pre>
    </div>
  );
}
