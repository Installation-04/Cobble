import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { setupApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthProvider";
import { useFetched } from "../project/useFetched";

/** The first time, the administrator is offered the welcome steps (once; they can be skipped). */
function FirstRun() {
  const progress = useFetched(() => setupApi.progress(), "setup-progress");
  if (progress.data !== null && !progress.data.completed) return <Navigate to="/welcome" replace />;
  return null;
}

export function HomePage() {
  const { t } = useTranslation("shell");
  const { user } = useAuth();
  return (
    <div
      data-testid="home"
      className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center"
    >
      {user?.role === "admin" && <FirstRun />}
      <h1 className="text-2xl font-semibold">{t("home.title")}</h1>
      <p className="max-w-md text-muted-foreground">{t("home.description")}</p>
    </div>
  );
}
