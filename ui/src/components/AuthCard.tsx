import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export function AuthCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="flex min-h-full items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm rounded-lg border border-border bg-card p-6 text-card-foreground shadow-sm">
        <p className="text-sm font-semibold text-primary">{t("app.name")}</p>
        <h1 className="mt-1 text-xl font-semibold">{title}</h1>
        <p className="mt-1 mb-5 text-sm text-muted-foreground">{description}</p>
        {children}
      </div>
    </div>
  );
}
