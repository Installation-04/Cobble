import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../api/errors";
import { useAuth } from "../auth/AuthProvider";
import { AuthCard } from "../components/AuthCard";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export function LoginPage() {
  const { t } = useTranslation(["auth", "common"]);
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate("/", { replace: true });
    } catch (e) {
      setError(errorMessage(t, e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title={t("auth:login.title")} description={t("auth:login.description")}>
      <form onSubmit={onSubmit} className="grid gap-4" data-testid="login-form">
        <div className="grid gap-2">
          <Label htmlFor="login-email">{t("auth:login.email")}</Label>
          <Input
            id="login-email"
            data-testid="login-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="login-password">{t("auth:login.password")}</Label>
          <Input
            id="login-password"
            data-testid="login-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && (
          <p role="alert" data-testid="login-error" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" data-testid="login-submit" disabled={busy}>
          {t("auth:login.submit")}
        </Button>
      </form>
    </AuthCard>
  );
}
