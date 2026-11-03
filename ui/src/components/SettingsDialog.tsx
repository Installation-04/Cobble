import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthProvider";
import { isLang, LANGS } from "../i18n";
import { isThemeMode, THEME_MODES } from "../theme/store";
import { useTheme } from "../theme/useTheme";
import { ModelConnections } from "../models/ModelConnections";
import { UI_VERSION } from "../version";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Label } from "./ui/label";
import { Select } from "./ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";

export function SettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t, i18n } = useTranslation(["settings", "common", "models"]);
  const { savePrefs, user } = useAuth();
  const { mode, setMode } = useTheme();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="settings-dialog" className="min-h-80 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("settings:title")}</DialogTitle>
          <DialogDescription>{t("settings:description")}</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="general" className="grid gap-4">
          <TabsList className="w-fit max-w-full">
            <TabsTrigger value="general" data-testid="settings-tab-general">
              {t("settings:tabs.general")}
            </TabsTrigger>
            <TabsTrigger value="appearance" data-testid="settings-tab-appearance">
              {t("settings:tabs.appearance")}
            </TabsTrigger>
            {user?.role === "admin" && (
              <TabsTrigger value="models" data-testid="settings-tab-models">
                {t("models:title")}
              </TabsTrigger>
            )}
            <TabsTrigger value="about" data-testid="settings-tab-about">
              {t("settings:tabs.about")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="general" className="grid gap-2">
            <Label htmlFor="settings-lang">{t("settings:general.language")}</Label>
            <Select
              id="settings-lang"
              data-testid="settings-lang-select"
              value={i18n.language}
              onChange={(e) => {
                if (isLang(e.target.value)) void savePrefs({ lang: e.target.value });
              }}
            >
              {LANGS.map((lang) => (
                <option key={lang} value={lang}>
                  {t(`common:lang.${lang}`)}
                </option>
              ))}
            </Select>
          </TabsContent>
          <TabsContent value="appearance" className="grid gap-2">
            <Label htmlFor="settings-theme">{t("settings:appearance.theme")}</Label>
            <Select
              id="settings-theme"
              data-testid="settings-theme-select"
              value={mode}
              onChange={(e) => {
                if (isThemeMode(e.target.value)) setMode(e.target.value);
              }}
            >
              {THEME_MODES.map((m) => (
                <option key={m} value={m}>
                  {t(`settings:appearance.options.${m}`)}
                </option>
              ))}
            </Select>
          </TabsContent>
          {user?.role === "admin" && (
            <TabsContent value="models">
              <ModelConnections />
            </TabsContent>
          )}
          <TabsContent value="about" className="grid gap-2 text-sm">
            <p>
              <span className="text-muted-foreground">{t("settings:about.version")}</span>{" "}
              <span data-testid="about-version">{UI_VERSION}</span>
            </p>
            <p className="text-muted-foreground">{t("settings:about.license")}</p>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
