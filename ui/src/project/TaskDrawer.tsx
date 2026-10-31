import { useState } from "react";
import { useTranslation } from "react-i18next";
import { buildApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { Task, TaskRun } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "../components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { DiffView } from "./DiffView";
import { LogView } from "./LogView";
import { useProjectData } from "./ProjectDataProvider";
import { canDo, isRunning, stateTone, TASK_ACTIONS, type TaskAction } from "./taskState";
import { useAsyncAction } from "./useAsyncAction";
import { useFetched } from "./useFetched";
import { useTaskLog } from "./useTaskLog";

function RunsTable({ runs, lang }: { runs: TaskRun[]; lang: string }) {
  const { t } = useTranslation("agents");
  if (runs.length === 0) {
    return (
      <p data-testid="runs-empty" className="text-sm text-muted-foreground">
        {t("runs.empty")}
      </p>
    );
  }
  const time = new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "short" });
  return (
    <div className="overflow-x-auto">
      <table data-testid="runs-table" className="w-full text-left text-sm">
        <caption className="sr-only">{t("runs.title")}</caption>
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("runs.kind")}
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("runs.attempt")}
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("runs.model")}
            </th>
            <th scope="col" className="py-1 pr-3 font-medium">
              {t("runs.state")}
            </th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">
              {t("runs.iterations")}
            </th>
            <th scope="col" className="py-1 font-medium">
              {t("runs.started")}
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run, index) => (
            <tr key={index} data-testid="run-row" className="border-t border-border">
              <td className="py-1 pr-3">{run.kind}</td>
              <td className="py-1 pr-3">{run.attempt}</td>
              <td className="py-1 pr-3 font-mono text-xs">{run.model}</td>
              <td className="py-1 pr-3">
                {t(`runState.${run.state}`, { defaultValue: run.state })}
              </td>
              <td className="py-1 pr-3 text-right">{run.iterations}</td>
              <td className="py-1">{time.format(new Date(run.started_at))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Actions({ task, onDone }: { task: Task; onDone: () => void }) {
  const { t } = useTranslation("agents");
  const { project, reloadTasks, upsertTask } = useProjectData();
  const act = useAsyncAction();
  const [pending, setPending] = useState<TaskAction | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);

  async function perform(action: TaskAction) {
    const updated = await buildApi[action](project.id, task.ref);
    if (updated && typeof updated.ref === "string") upsertTask(updated);
    else await reloadTasks();
    onDone();
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("actions.label")}>
        {TASK_ACTIONS.map((action) => (
          <Button
            key={action}
            size="sm"
            variant={action === "stop" ? "destructive" : "outline"}
            data-testid={`task-${action}`}
            disabled={!canDo(action, task.state) || act.busy}
            onClick={() => {
              if (action === "stop") {
                setConfirmStop(true);
                return;
              }
              setPending(action);
              void act.run(() => perform(action)).finally(() => setPending(null));
            }}
          >
            {pending === action ? t("actions.working") : t(`actions.${action}`)}
          </Button>
        ))}
      </div>
      {act.error && (
        <p role="alert" data-testid="task-action-error" className="text-sm text-destructive">
          {act.error}
        </p>
      )}
      <ConfirmDialog
        open={confirmStop}
        onOpenChange={setConfirmStop}
        title={t("actions.stopTitle")}
        description={t("actions.stopDescription", { ref: task.ref })}
        confirmLabel={t("actions.stop")}
        onConfirm={() => perform("stop")}
      />
    </div>
  );
}

function DrawerBody({ task }: { task: Task }) {
  const { t, i18n } = useTranslation(["agents", "errors", "plan"]);
  const { project } = useProjectData();
  const key = `${task.ref}:${task.state}:${task.attempts}`;
  const detail = useFetched(() => buildApi.task(project.id, task.ref), key);
  const diff = useFetched(() => buildApi.diff(project.id, task.ref), key);
  const runs = detail.data?.runs ?? [];
  const running = isRunning(task.state);
  const log = useTaskLog(
    project.id,
    task.ref,
    running,
    runs.length > 0 ? `${task.attempts}:${runs.at(-1)?.started_at}` : "",
  );

  return (
    <>
      <div className="flex flex-col gap-1 pr-6">
        <SheetTitle className="text-lg font-semibold">
          <span className="font-mono text-sm text-muted-foreground">{task.ref}</span> {task.title}
        </SheetTitle>
        <SheetDescription className="sr-only">{t("agents:drawer.description")}</SheetDescription>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={stateTone(task.state)} data-testid="drawer-state">
            {t(`agents:state.${task.state}`)}
          </Badge>
          <Badge>{task.milestone}</Badge>
          <Badge>{t(`plan:task.role.${task.role}`, { defaultValue: task.role })}</Badge>
          <Badge>{task.size}</Badge>
          <span className="text-muted-foreground">
            {t("agents:attempts", { count: task.attempts })}
          </span>
          {task.escalated && <Badge tone="warning">{t("agents:escalated")}</Badge>}
        </div>
      </div>

      <Actions task={task} onDone={detail.reload} />

      <section aria-labelledby="runs-title" className="flex flex-col gap-2">
        <h3 id="runs-title" className="text-sm font-semibold">
          {t("agents:runs.title")}
        </h3>
        {detail.error != null && detail.data === null ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(t, detail.error)}
          </p>
        ) : (
          <RunsTable runs={runs} lang={i18n.language} />
        )}
      </section>

      <Tabs defaultValue="log" className="flex flex-col gap-2">
        <TabsList aria-label={t("agents:drawer.views")} className="self-start">
          <TabsTrigger value="log" data-testid="drawer-tab-log">
            {t("agents:log.title")}
          </TabsTrigger>
          <TabsTrigger value="diff" data-testid="drawer-tab-diff">
            {t("agents:diff.title")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="log" className="flex flex-col gap-2">
          {log.error != null && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(t, log.error)}
            </p>
          )}
          <LogView text={log.text} running={running} />
        </TabsContent>
        <TabsContent value="diff">
          {diff.error != null && diff.data === null ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(t, diff.error)}
            </p>
          ) : diff.data ? (
            <DiffView diff={diff.data.diff} truncated={diff.data.truncated} />
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              {t("common:loading")}
            </p>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}

export function TaskDrawer({ task, onClose }: { task: Task | null; onClose: () => void }) {
  return (
    <Sheet open={task !== null} onOpenChange={(open) => !open && onClose()}>
      {task && (
        <SheetContent data-testid="task-drawer">
          <DrawerBody task={task} key={task.ref} />
        </SheetContent>
      )}
    </Sheet>
  );
}
