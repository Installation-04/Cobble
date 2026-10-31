import { Bot, Coins, MonitorPlay } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { costsApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { Project } from "../api/types";
import { Badge } from "../components/ui/badge";
import { formatCost } from "../project/format";
import { PHASE_LABEL_KEY } from "../project/PhaseStepper";
import { useFetched } from "../project/useFetched";
import { useWorkspace } from "../workspace/WorkspaceProvider";

const ICONS = { agents: Bot, demos: MonitorPlay, costs: Coins } as const;
const TABS = { agents: "agents", demos: "demo", costs: "costs" } as const;

type View = keyof typeof ICONS;

function ViewHeader({ view }: { view: View }) {
  const { t } = useTranslation("shell");
  const Icon = ICONS[view];
  return (
    <header className="flex flex-col gap-1">
      <h1 className="flex items-center gap-2 text-xl font-semibold">
        <Icon className="h-5 w-5" aria-hidden="true" />
        {t(`sidebar.${view}`)}
      </h1>
      <p className="text-sm text-muted-foreground">{t(`global.${view}.description`)}</p>
    </header>
  );
}

function Empty({ view }: { view: View }) {
  const { t } = useTranslation("shell");
  return (
    <p data-testid={`view-${view}-empty`} className="text-sm text-muted-foreground">
      {t("global.empty")}
    </p>
  );
}

const linkClass =
  "font-medium text-primary underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

/** Agents and demos: the user's projects with their phase and a link to the matching tab. */
function ProjectLinks({ view }: { view: "agents" | "demos" }) {
  const { t } = useTranslation(["shell", "chat"]);
  const { projects, loading } = useWorkspace();
  return (
    <div className="flex flex-col gap-4 p-6" data-testid={`view-${view}`}>
      <ViewHeader view={view} />
      {!loading && projects.length === 0 ? (
        <Empty view={view} />
      ) : (
        <ul className="flex flex-col gap-2">
          {projects.map((project: Project) => (
            <li
              key={project.id}
              data-testid={`view-${view}-row`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card p-3 text-card-foreground"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{project.name}</span>
                <Badge data-testid="view-phase">
                  {t(`chat:stepper.${PHASE_LABEL_KEY[project.phase]}`)}
                </Badge>
              </span>
              <Link to={`/projects/${project.id}?tab=${TABS[view]}`} className={linkClass}>
                {t(`global.${view}.open`)}
                <span className="sr-only"> {project.name}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CostsView() {
  const { t, i18n } = useTranslation(["shell", "errors"]);
  const lang = i18n.language;
  const { data, error, loading } = useFetched(() => costsApi.all(), "costs");
  const rows = data ?? [];
  const total = rows.reduce((sum, row) => sum + (Number.parseFloat(row.spent_usd) || 0), 0);
  return (
    <div className="flex flex-col gap-4 p-6" data-testid="view-costs">
      <ViewHeader view="costs" />
      {error != null && data === null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(t, error)}
        </p>
      )}
      {loading && <p role="status">{t("common:loading")}</p>}
      {data !== null && rows.length === 0 && <Empty view="costs" />}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table data-testid="view-costs-table" className="w-full text-left text-sm">
            <caption className="sr-only">{t("global.costs.caption")}</caption>
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("global.costs.project")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t("global.costs.spent")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t("global.costs.budget")}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("global.costs.status")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.project_id}
                  data-testid="view-costs-row"
                  className="border-t border-border"
                >
                  <th scope="row" className="px-3 py-2 font-medium">
                    <Link to={`/projects/${row.project_id}?tab=costs`} className={linkClass}>
                      {row.name}
                    </Link>
                  </th>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatCost(row.spent_usd, lang)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.budget_usd === null
                      ? t("global.costs.noBudget")
                      : formatCost(row.budget_usd, lang)}
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={row.status === "paused" ? "warning" : "neutral"}>
                      {t(`global.costs.state.${row.status}`)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-border bg-muted font-medium">
                <th scope="row" className="px-3 py-2">
                  {t("global.costs.total")}
                </th>
                <td className="px-3 py-2 text-right tabular-nums" data-testid="view-costs-total">
                  {formatCost(total, lang)}
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

export function GlobalView({ view }: { view: View }) {
  return view === "costs" ? <CostsView /> : <ProjectLinks view={view} />;
}
