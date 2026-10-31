import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { ChatTab } from "../project/ChatTab";
import { PlanTab } from "../project/PlanTab";
import { ProjectDataProvider } from "../project/ProjectDataProvider";
import { ComingSoon } from "./Placeholder";

const SECTIONS = ["chat", "plan", "agents", "demo", "costs"] as const;
const PLACEHOLDER_SECTIONS = SECTIONS.filter((s) => s !== "chat" && s !== "plan");

export function ProjectPage() {
  const { t } = useTranslation("shell");
  const { id } = useParams();
  const { projects, loading } = useWorkspace();
  const project = projects.find((p) => p.id === id);

  if (!project) {
    if (loading) return null;
    return (
      <div data-testid="project-not-found" className="p-8 text-center">
        <h1 className="text-xl font-semibold">{t("notFound.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("notFound.description")}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" data-testid="project-page">
      <h1 className="sr-only">{project.name}</h1>
      <ProjectDataProvider project={project} key={project.id}>
        <Tabs defaultValue="chat" className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-border px-3 py-2">
            <TabsList aria-label={t("tabs.label")}>
              {SECTIONS.map((s) => (
                <TabsTrigger key={s} value={s} data-testid={`tab-${s}`}>
                  {t(`tabs.${s}`)}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          <TabsContent value="chat" className="min-h-0 flex-1">
            <ChatTab />
          </TabsContent>
          <TabsContent value="plan" className="min-h-0 flex-1">
            <PlanTab />
          </TabsContent>
          {PLACEHOLDER_SECTIONS.map((s) => (
            <TabsContent key={s} value={s} className="min-h-0 flex-1">
              <ComingSoon title={t(`tabs.${s}`)} testId={`tab-panel-${s}`} />
            </TabsContent>
          ))}
        </Tabs>
      </ProjectDataProvider>
    </div>
  );
}
