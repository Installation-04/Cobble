import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { AgentsTab } from "../project/AgentsTab";
import { ChatTab } from "../project/ChatTab";
import { CostsTab } from "../project/CostsTab";
import { DemoTab } from "../project/DemoTab";
import { PlanTab } from "../project/PlanTab";
import { ProjectDataProvider } from "../project/ProjectDataProvider";

const SECTIONS = ["chat", "plan", "agents", "demo", "costs"] as const;
type Section = (typeof SECTIONS)[number];
const isSection = (value: string | null): value is Section =>
  (SECTIONS as readonly (string | null)[]).includes(value);

export function ProjectPage() {
  const { t } = useTranslation("shell");
  const { id } = useParams();
  const { projects, loading } = useWorkspace();
  // The tab lives in the URL (?tab=agents&task=T-001) so that links can point into a project.
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab: Section = isSection(requested) ? requested : "chat";
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
        <Tabs
          value={tab}
          onValueChange={(value) => setParams({ tab: value }, { replace: true })}
          className="flex min-h-0 flex-1 flex-col"
        >
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
          <TabsContent value="agents" className="min-h-0 flex-1">
            <AgentsTab />
          </TabsContent>
          <TabsContent value="demo" className="min-h-0 flex-1">
            <DemoTab />
          </TabsContent>
          <TabsContent value="costs" className="min-h-0 flex-1">
            <CostsTab />
          </TabsContent>
        </Tabs>
      </ProjectDataProvider>
    </div>
  );
}
