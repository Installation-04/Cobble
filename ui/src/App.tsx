import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { WelcomePage } from "./pages/WelcomePage";
import { ActivatePage } from "./pages/ActivatePage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { GlobalView } from "./pages/GlobalViews";
import { StorePage } from "./pages/StorePage";
import { ProjectPage } from "./pages/ProjectPage";
import { Shell } from "./pages/Shell";

function Splash() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      data-testid="splash"
      className="flex h-full items-center justify-center text-muted-foreground"
    >
      {t("loading")}
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") return <Splash />;
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return children;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "loading") return <Splash />;
  if (status === "authenticated") return <Navigate to="/" replace />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/activate" element={<ActivatePage />} />
      <Route
        path="/login"
        element={
          <PublicOnly>
            <LoginPage />
          </PublicOnly>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="projects/:id" element={<ProjectPage />} />
        <Route path="agents" element={<GlobalView view="agents" />} />
        <Route path="demos" element={<GlobalView view="demos" />} />
        <Route path="costs" element={<GlobalView view="costs" />} />
        <Route path="store" element={<StorePage />} />
        <Route path="welcome" element={<WelcomePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
