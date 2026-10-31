import { Construction } from "lucide-react";
import { useTranslation } from "react-i18next";

export function ComingSoon({ title, testId = "coming-soon" }: { title?: string; testId?: string }) {
  const { t } = useTranslation("shell");
  return (
    <div
      data-testid={testId}
      className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
    >
      <Construction className="h-8 w-8 text-muted-foreground" />
      {title && <h1 className="text-xl font-semibold">{title}</h1>}
      <p className="font-medium">{t("placeholder.title")}</p>
      <p className="text-sm text-muted-foreground">{t("placeholder.description")}</p>
    </div>
  );
}

export function GlobalView({ view }: { view: "agents" | "demos" | "costs" }) {
  const { t } = useTranslation("shell");
  return <ComingSoon title={t(`sidebar.${view}`)} testId={`view-${view}`} />;
}
