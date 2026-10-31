import { useTranslation } from "react-i18next";

export function HomePage() {
  const { t } = useTranslation("shell");
  return (
    <div
      data-testid="home"
      className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
    >
      <h1 className="text-2xl font-semibold">{t("home.title")}</h1>
      <p className="max-w-md text-muted-foreground">{t("home.description")}</p>
    </div>
  );
}
