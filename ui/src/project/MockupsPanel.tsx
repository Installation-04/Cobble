import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { FailureBanner } from "./FailureBanner";
import { useProjectData } from "./ProjectDataProvider";
import { useAsyncAction } from "./useAsyncAction";

/**
 * Optional step before the plan (ADR 0018): the planner proposes 2 or 3 mockups and the user
 * picks one. A mockup is plain text. It is rendered as an escaped text node inside <pre>, never
 * as markup, so nothing a model wrote can run.
 */
export function MockupsPanel() {
  const { t } = useTranslation("mockups");
  const { project, paused, jobs, mockups, generateMockups, chooseMockup } = useProjectData();
  const { updateProject } = useWorkspace();
  const toggle = useAsyncAction();
  const generate = useAsyncAction();
  const choose = useAsyncAction();
  const enabled = project.mockups_enabled === true;
  const running = jobs.mockups;
  const error = toggle.error ?? generate.error ?? choose.error;

  return (
    <section
      aria-labelledby="mockups-title"
      data-testid="mockups-panel"
      data-state={enabled ? "on" : "off"}
      className="flex w-full flex-col gap-3 rounded-lg border border-border bg-card p-4 text-left text-card-foreground"
    >
      <h3 id="mockups-title" className="text-sm font-semibold">
        {t("title")}
      </h3>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={enabled}
          disabled={toggle.busy}
          data-testid="mockups-toggle"
          onChange={(e) =>
            void toggle.run(() => updateProject(project.id, { mockups_enabled: e.target.checked }))
          }
        />
        <span>{t("label")}</span>
      </label>
      <p className="text-xs text-muted-foreground">{enabled ? t("onHelp") : t("offHelp")}</p>

      {enabled && (
        <>
          <FailureBanner kinds={["mockups"]} />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={mockups.length > 0 ? "outline" : "default"}
              data-testid="mockups-generate"
              disabled={paused || running}
              onClick={() => void generate.run(() => generateMockups())}
            >
              {running && (
                <Loader2
                  className="h-4 w-4 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              )}
              {running ? t("generating") : mockups.length > 0 ? t("regenerate") : t("generate")}
            </Button>
            {mockups.length > 0 && !mockups.some((m) => m.chosen) && (
              <p className="text-xs text-muted-foreground" data-testid="mockups-pick-hint">
                {t("pickHint")}
              </p>
            )}
          </div>
          {mockups.length > 0 && (
            <ul className="grid gap-3 md:grid-cols-3" data-testid="mockups-list">
              {mockups.map((variant) => (
                <li
                  key={variant.id}
                  data-testid={`mockup-${variant.position}`}
                  data-chosen={variant.chosen}
                  className={`flex min-w-0 flex-col gap-2 rounded-md border bg-background p-3 text-sm ${
                    variant.chosen ? "border-primary" : "border-border"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="font-medium">{variant.title}</h4>
                    {variant.chosen && <Badge tone="success">{t("chosen")}</Badge>}
                  </div>
                  <p className="text-muted-foreground">{variant.summary}</p>
                  <pre
                    tabIndex={0}
                    aria-label={t("wireframe", { title: variant.title })}
                    data-testid={`mockup-wireframe-${variant.position}`}
                    className="max-h-72 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre text-muted-foreground"
                  >
                    {variant.wireframe}
                  </pre>
                  <Button
                    size="sm"
                    variant={variant.chosen ? "outline" : "default"}
                    data-testid={`mockup-choose-${variant.position}`}
                    aria-pressed={variant.chosen}
                    disabled={variant.chosen || paused || choose.busy}
                    onClick={() => void choose.run(() => chooseMockup(variant.id))}
                  >
                    {variant.chosen ? t("chosen") : t("choose")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="mockups-error">
          {error}
        </p>
      )}
    </section>
  );
}
