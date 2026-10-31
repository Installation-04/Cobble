import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../api/errors";
import { useAuth } from "../auth/AuthProvider";
import { AuthCard } from "../components/AuthCard";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { isLang, LANGS, setLang } from "../i18n";

const MIN_PASSWORD = 10;

export function ActivatePage() {
  const { t, i18n } = useTranslation(["auth", "common", "errors"]);
  const { activate } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(token ? null : t("auth:activate.missingToken"));
  const [busy, setBusy] = useState(false);
  const lang = isLang(i18n.language) ? i18n.language : "en";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(t("auth:activate.passwordTooShort"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await activate(token, email.trim(), password, lang);
      navigate("/", { replace: true });
    } catch (e) {
      setError(errorMessage(t, e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title={t("auth:activate.title")} description={t("auth:activate.description")}>
      <form onSubmit={onSubmit} className="grid gap-4" data-testid="activate-form">
        <div className="grid gap-2">
          <Label htmlFor="activate-email">{t("auth:activate.email")}</Label>
          <Input
            id="activate-email"
            data-testid="activate-email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="activate-password">{t("auth:activate.password")}</Label>
          <Input
            id="activate-password"
            data-testid="activate-password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">{t("auth:activate.passwordHint")}</p>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="activate-lang">{t("auth:activate.language")}</Label>
          <Select
            id="activate-lang"
            data-testid="activate-lang"
            value={lang}
            onChange={(e) => {
              if (isLang(e.target.value)) void setLang(e.target.value);
            }}
          >
            {LANGS.map((l) => (
              <option key={l} value={l}>
                {t(`common:lang.${l}`)}
              </option>
            ))}
          </Select>
        </div>
        {error && (
          <p role="alert" data-testid="activate-error" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" data-testid="activate-submit" disabled={busy || !token}>
          {t("auth:activate.submit")}
        </Button>
      </form>
    </AuthCard>
  );
}
