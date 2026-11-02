import { ArrowRight, Cpu } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { flowApi, modulesApi, setupApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import { useAuth } from "../auth/AuthProvider";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { ModelConnections } from "../models/ModelConnections";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";
import { PackSheet, packText } from "../store/PackSheet";
import { useModuleOperation } from "../store/useModuleOperation";
import { useModuleStream } from "../store/useModuleStream";
import { useWorkspace } from "../workspace/WorkspaceProvider";

const STEPS = ["machine", "model", "project"] as const;
type Step = (typeof STEPS)[number];

function ramLabel(mb: number): string {
  return `${Math.round(mb / 1024)} GB`;
}

/** Step 1: what this machine can run, and the starter pack that suits it. */
function MachineStep({ onNext }: { onNext: () => void }) {
  const { t, i18n } = useTranslation(["welcome", "errors", "store"]);
  const catalog = useFetched(() => modulesApi.catalog(), "welcome-modules");
  const packsData = useFetched(() => modulesApi.packs(), "welcome-packs");
  const [open, setOpen] = useState(false);
  const operation = useModuleOperation(() => {
    catalog.reload();
    packsData.reload();
  });
  useModuleStream({
    onStep: operation.onStep,
    onOperation: operation.onOperation,
    onResync: () => {
      packsData.reload();
      void operation.resync();
    },
  });
  const hardware = catalog.data?.hardware;
  const packs = packsData.data?.packs ?? [];
  const recommended = packs.find((p) => p.recommended) ?? null;
  const unavailable = catalog.error != null && catalog.data === null;

  return (
    <section
      className="grid gap-4"
      data-testid="welcome-machine"
      aria-labelledby="welcome-h-machine"
    >
      <h2 id="welcome-h-machine" className="text-lg font-semibold">
        {t("machine.title")}
      </h2>
      {hardware && (
        <p className="flex items-center gap-2 text-sm" data-testid="welcome-hardware">
          <Cpu className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          {t("machine.detected", {
            ram: ramLabel(hardware.ram_mb),
            gpu: hardware.gpu === "none" ? t("machine.noGpu") : hardware.gpu,
          })}
        </p>
      )}
      {unavailable && (
        <p role="alert" className="text-sm text-destructive" data-testid="welcome-unavailable">
          {errorMessage(t, catalog.error)}
        </p>
      )}
      {recommended && (
        <div className="grid gap-2 rounded-lg border border-primary bg-card p-4 text-card-foreground">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{packText(recommended, "name", i18n.language)}</span>
            <Badge tone="primary">{t("store:packs.recommended")}</Badge>
            {recommended.installed && <Badge tone="success">{t("store:packs.installed")}</Badge>}
          </div>
          <p className="text-sm text-muted-foreground">
            {packText(recommended, "description", i18n.language)}
          </p>
          {!recommended.installed && (
            <div>
              <Button onClick={() => setOpen(true)} data-testid="welcome-pack-open">
                {t("machine.install")}
              </Button>
            </div>
          )}
        </div>
      )}
      {!unavailable && packsData.data !== null && !recommended && (
        <p className="text-sm text-muted-foreground" data-testid="welcome-no-pack">
          {t("machine.noPack")}
        </p>
      )}
      <PackSheet
        pack={open ? recommended : null}
        operation={operation}
        onClose={() => setOpen(false)}
      />
      <div>
        <Button variant="outline" onClick={onNext} data-testid="welcome-next">
          {t("next")}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </section>
  );
}

/** Step 3: a first project, started with an example so the owner sees the whole loop. */
function ProjectStep({ onFinish }: { onFinish: (projectId: string | null) => Promise<void> }) {
  const { t } = useTranslation(["welcome", "errors"]);
  const { createProject } = useWorkspace();
  const action = useAsyncAction();
  return (
    <section
      className="grid gap-4"
      data-testid="welcome-project"
      aria-labelledby="welcome-h-project"
    >
      <h2 id="welcome-h-project" className="text-lg font-semibold">
        {t("project.title")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("project.description")}</p>
      {action.error && (
        <p role="alert" className="text-sm text-destructive">
          {action.error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={action.busy}
          data-testid="welcome-example"
          onClick={() =>
            void action.run(async () => {
              const project = await createProject(t("project.exampleName"), null);
              await flowApi.sendMessage(project.id, t("project.examplePrompt"));
              await onFinish(project.id);
            })
          }
        >
          {t("project.start")}
        </Button>
        <Button
          variant="outline"
          disabled={action.busy}
          data-testid="welcome-finish"
          onClick={() => void action.run(() => onFinish(null))}
        >
          {t("project.skip")}
        </Button>
      </div>
    </section>
  );
}

/**
 * First-run wizard for the administrator: the machine and its starter pack, a model service,
 * and an example project. Every step can be skipped; finishing or skipping is remembered so it
 * is offered once. The account itself was created on the activation page.
 */
export function WelcomePage() {
  const { t } = useTranslation(["welcome", "models"]);
  const { status, user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("machine");
  const done = async (projectId: string | null) => {
    await setupApi.complete();
    navigate(projectId ? `/projects/${projectId}` : "/", { replace: true });
  };
  const finish = useAsyncAction();
  if (status === "loading") return null;
  if (user?.role !== "admin") {
    navigate("/", { replace: true });
    return null;
  }
  const index = STEPS.indexOf(step);
  return (
    <div className="mx-auto grid max-w-2xl gap-6 p-6" data-testid="welcome">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("intro")}</p>
        <p className="text-xs text-muted-foreground" data-testid="welcome-progress">
          {t("progress", { current: index + 1, total: STEPS.length })}
        </p>
      </header>
      {step === "machine" && <MachineStep onNext={() => setStep("model")} />}
      {step === "model" && (
        <section
          className="grid gap-4"
          data-testid="welcome-model"
          aria-labelledby="welcome-h-model"
        >
          <h2 id="welcome-h-model" className="text-lg font-semibold">
            {t("model.title")}
          </h2>
          <p className="text-sm text-muted-foreground">{t("model.description")}</p>
          <ModelConnections />
          <div>
            <Button variant="outline" onClick={() => setStep("project")} data-testid="welcome-next">
              {t("next")}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </section>
      )}
      {step === "project" && <ProjectStep onFinish={done} />}
      {finish.error && <p role="alert">{finish.error}</p>}
      {step !== "project" && (
        <div>
          <Button
            variant="ghost"
            size="sm"
            data-testid="welcome-skip"
            disabled={finish.busy}
            onClick={() => void finish.run(() => done(null))}
          >
            {t("skipAll")}
          </Button>
        </div>
      )}
    </div>
  );
}
