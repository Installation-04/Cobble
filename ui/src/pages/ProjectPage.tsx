import { Send } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { ComingSoon } from "./Placeholder";

const SECTIONS = ["chat", "plan", "agents", "demo", "costs"] as const;

function ChatPlaceholder() {
  const { t } = useTranslation("shell");
  return (
    <div className="flex h-full min-h-96 flex-col">
      <div
        data-testid="chat-empty"
        className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-center"
      >
        <h2 className="text-lg font-semibold">{t("chat.emptyTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("chat.emptyDescription")}</p>
      </div>
      <form
        className="flex items-center gap-2 border-t border-border p-3"
        onSubmit={(e) => e.preventDefault()}
      >
        <Input
          disabled
          data-testid="chat-input"
          aria-label={t("chat.inputLabel")}
          placeholder={t("chat.inputPlaceholder")}
        />
        <Button type="submit" size="icon" disabled aria-label={t("chat.send")}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}

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
      <Tabs defaultValue="chat" className="flex min-h-0 flex-1 flex-col" key={project.id}>
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
          <ChatPlaceholder />
        </TabsContent>
        {SECTIONS.filter((s) => s !== "chat").map((s) => (
          <TabsContent key={s} value={s} className="min-h-0 flex-1">
            <ComingSoon title={t(`tabs.${s}`)} testId={`tab-panel-${s}`} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
