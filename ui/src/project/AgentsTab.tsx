import { Bot, Loader2, RotateCw } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/errors";
import type { Task } from "../api/types";
import { Badge } from "../components/ui/badge";
import { cn } from "../lib";
import { FailureBanner } from "./FailureBanner";
import { useProjectData } from "./ProjectDataProvider";
import { groupTasks, stateTone, TASK_GROUPS } from "./taskState";
import { TaskDrawer } from "./TaskDrawer";

const SEP = "·";

function TaskCard({ task, onOpen }: { task: Task; onOpen: () => void }) {
  const { t } = useTranslation(["agents", "plan"]);
  return (
    <li>
      <button
        type="button"
        data-testid={`agent-card-${task.ref}`}
        data-state={task.state}
        onClick={onOpen}
        className="flex w-full flex-col gap-2 rounded-lg border border-border bg-card p-3 text-left text-sm text-card-foreground hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">{task.ref}</span>
          <Badge tone={stateTone(task.state)} data-testid="card-state">
            {t(`agents:state.${task.state}`)}
          </Badge>
          {task.escalated && (
            <Badge tone="warning" data-testid="card-escalated">
              {t("agents:escalated")}
            </Badge>
          )}
        </span>
        <span className="font-medium">{task.title}</span>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span data-testid="card-milestone">{task.milestone}</span>
          <span aria-hidden="true">{SEP}</span>
          <span data-testid="card-role">
            {t(`plan:task.role.${task.role}`, { defaultValue: task.role })}
          </span>
          <span aria-hidden="true">{SEP}</span>
          <span data-testid="card-size" aria-label={t("agents:size", { size: task.size })}>
            {task.size}
          </span>
          <span aria-hidden="true">{SEP}</span>
          <span data-testid="card-attempts">{t("agents:attempts", { count: task.attempts })}</span>
        </span>
      </button>
    </li>
  );
}

function EmptyState() {
  const { t } = useTranslation("agents");
  const { phase, jobs } = useProjectData();
  let key: "notStarted" | "ready" | "preparing" | "noTasks";
  if (phase === "ready") key = jobs.start ? "preparing" : "ready";
  else if (phase === "building") key = "preparing";
  else if (phase === "done") key = "noTasks";
  else key = "notStarted";
  return (
    <div
      data-testid="agents-empty"
      data-reason={key}
      className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center"
    >
      {key === "preparing" ? (
        <Loader2
          className="h-8 w-8 animate-spin text-muted-foreground motion-reduce:animate-none"
          aria-hidden="true"
        />
      ) : (
        <Bot className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      )}
      <h2 className="text-lg font-semibold">{t(`empty.${key}.title`)}</h2>
      <p role="status" className="text-sm text-muted-foreground">
        {t(`empty.${key}.description`)}
      </p>
      {key === "ready" && (
        <Link
          to="?tab=plan"
          className="text-sm font-medium text-primary underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          {t("empty.ready.link")}
        </Link>
      )}
    </div>
  );
}

export function AgentsTab() {
  const { t } = useTranslation(["agents", "errors"]);
  const { tasks, buildError, reloadTasks } = useProjectData();
  const [params, setParams] = useSearchParams();
  const selectedRef = params.get("task");
  const grouped = useMemo(() => groupTasks(tasks), [tasks]);
  const selected = selectedRef ? (tasks.find((task) => task.ref === selectedRef) ?? null) : null;

  const open = (ref: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("task", ref);
      return next;
    });
  const close = () =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("task");
      return next;
    });

  return (
    <div
      className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-4"
      data-testid="agents-tab"
    >
      <FailureBanner kinds={["start"]} />
      {buildError != null && (
        <div
          role="alert"
          data-testid="agents-error"
          className="flex items-center justify-between gap-2 rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          <span>{errorMessage(t, buildError)}</span>
          <button
            type="button"
            onClick={() => void reloadTasks()}
            className="flex items-center gap-1 rounded-sm px-2 py-1 font-medium hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <RotateCw className="h-3 w-3" aria-hidden="true" />
            {t("agents:reload")}
          </button>
        </div>
      )}
      {tasks.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <p className="text-sm text-muted-foreground" data-testid="agents-summary">
            {t("summary", { merged: grouped.merged.length, total: tasks.length })}
          </p>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            {TASK_GROUPS.map((group) => (
              <section
                key={group}
                aria-labelledby={`agents-col-${group}`}
                data-testid={`agents-col-${group}`}
                className={cn(
                  "flex min-w-0 flex-col gap-2 rounded-lg bg-muted p-2",
                  group === "attention" && grouped.attention.length > 0 && "ring-1 ring-warning",
                )}
              >
                <h3
                  id={`agents-col-${group}`}
                  className="flex items-center justify-between gap-2 px-1 text-sm font-semibold"
                >
                  {t(`group.${group}`)}
                  <Badge data-testid={`agents-count-${group}`}>{grouped[group].length}</Badge>
                </h3>
                <ul className="flex flex-col gap-2">
                  {grouped[group].map((task) => (
                    <TaskCard key={task.ref} task={task} onOpen={() => open(task.ref)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </>
      )}
      <TaskDrawer task={selected} onClose={close} />
    </div>
  );
}
