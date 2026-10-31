import { ChevronDown, LogOut, Menu, Moon, Settings, Sun, User as UserIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMatch, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useTheme } from "../theme/useTheme";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

interface Props {
  onToggleSidebar: () => void;
  onOpenSettings: () => void;
}

export function TopBar({ onToggleSidebar, onOpenSettings }: Props) {
  const { t, i18n } = useTranslation(["shell", "common"]);
  const { user, logout, savePrefs } = useAuth();
  const { dark, toggle: toggleTheme } = useTheme();
  const { projects } = useWorkspace();
  const navigate = useNavigate();
  const match = useMatch("/projects/:id");
  const current = projects.find((p) => p.id === match?.params.id);
  const otherLang = i18n.language === "fr" ? "en" : "fr";

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <header
      data-testid="topbar"
      className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3"
    >
      <Button
        variant="ghost"
        size="icon"
        data-testid="sidebar-toggle"
        aria-label={t("shell:sidebar.toggle")}
        onClick={onToggleSidebar}
      >
        <Menu className="h-5 w-5" />
      </Button>

      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" data-testid="project-selector" className="max-w-56 min-w-0">
            <span className="truncate">{current?.name ?? t("shell:topbar.noProject")}</span>
            <ChevronDown className="h-4 w-4 shrink-0" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>{t("shell:topbar.projectSelector")}</DropdownMenuLabel>
          {projects.map((p) => (
            <DropdownMenuItem
              key={p.id}
              data-testid="project-selector-item"
              onSelect={() => navigate(`/projects/${p.id}`)}
            >
              {p.name}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <div className="flex-1" />

      <Button
        variant="ghost"
        data-testid="lang-toggle"
        aria-label={t("shell:topbar.switchLanguage")}
        title={t("shell:topbar.switchLanguage")}
        onClick={() => void savePrefs({ lang: otherLang })}
      >
        {t(`common:lang.short.${i18n.language === "fr" ? "fr" : "en"}`)}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        data-testid="theme-toggle"
        aria-label={t("shell:topbar.switchTheme")}
        title={t("shell:topbar.switchTheme")}
        onClick={toggleTheme}
      >
        {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        data-testid="settings-button"
        aria-label={t("shell:topbar.settings")}
        title={t("shell:topbar.settings")}
        onClick={onOpenSettings}
      >
        <Settings className="h-5 w-5" />
      </Button>

      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            data-testid="profile-menu"
            aria-label={t("shell:topbar.profile")}
          >
            <UserIcon className="h-5 w-5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel data-testid="profile-email">{user?.email}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem data-testid="menu-settings" onSelect={onOpenSettings}>
            <Settings className="h-4 w-4" />
            {t("shell:topbar.settings")}
          </DropdownMenuItem>
          <DropdownMenuItem data-testid="logout-button" onSelect={() => void onLogout()}>
            <LogOut className="h-4 w-4" />
            {t("shell:topbar.logout")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
