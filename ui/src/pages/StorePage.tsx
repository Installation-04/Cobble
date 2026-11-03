import { Blocks, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { modulesApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { ModuleEntry, ModulePack } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { cn } from "../lib";
import { useFetched } from "../project/useFetched";
import { ModuleSheet } from "../store/ModuleSheet";
import { PackSheet, packText } from "../store/PackSheet";
import { fitProblems, localizedDescription, packProblems, stateTone } from "../store/moduleView";
import { useModuleOperation } from "../store/useModuleOperation";
import { useModuleStream } from "../store/useModuleStream";

function matches(module: ModuleEntry, query: string, lang: string): boolean {
  if (!query) return true;
  const haystack = [module.id, module.name, localizedDescription(module, lang), ...module.provides]
    .join(" ")
    .toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

function ModuleCard({ module, onOpen }: { module: ModuleEntry; onOpen: () => void }) {
  const { t, i18n } = useTranslation("store");
  const fits = module.hardware.ok;
  const state = module.installed?.state;
  const problems = fitProblems(t, module);
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        data-testid={`module-card-${module.id}`}
        data-fits={fits}
        className={cn(
          "flex h-full w-full flex-col gap-2 rounded-lg border border-border bg-card p-4 text-left text-card-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          fits ? "hover:bg-accent" : "opacity-60",
        )}
      >
        <span className="flex items-start justify-between gap-2">
          <span className="font-medium">{module.name}</span>
          <span className="text-xs text-muted-foreground">{module.version}</span>
        </span>
        <span className="text-sm text-muted-foreground">
          {localizedDescription(module, i18n.language)}
        </span>
        <span className="mt-auto flex flex-wrap items-center gap-2 pt-1">
          <Badge tone="neutral">
            {t(`category.${module.category}`, { defaultValue: module.category })}
          </Badge>
          <Badge tone={stateTone(state)} data-testid={`module-state-${module.id}`}>
            {t(`state.${state ?? "none"}`)}
          </Badge>
          {!fits && <Badge tone="warning">{t("fit.no")}</Badge>}
        </span>
        {!fits && problems.length > 0 && (
          <span
            className="text-xs text-muted-foreground"
            data-testid={`module-reason-${module.id}`}
          >
            {problems.join(" · ")}
          </span>
        )}
      </button>
    </li>
  );
}

function PackCard({ pack, onOpen }: { pack: ModulePack; onOpen: () => void }) {
  const { t, i18n } = useTranslation("store");
  const problems = packProblems(t, pack);
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        data-testid={`pack-card-${pack.id}`}
        data-fits={pack.fit.ok}
        data-recommended={pack.recommended}
        className={cn(
          "flex h-full w-full flex-col gap-2 rounded-lg border bg-card p-4 text-left text-card-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          pack.recommended ? "border-primary" : "border-border",
          pack.fit.ok ? "hover:bg-accent" : "opacity-60",
        )}
      >
        <span className="font-medium">{packText(pack, "name", i18n.language)}</span>
        <span className="text-sm text-muted-foreground">
          {packText(pack, "description", i18n.language)}
        </span>
        <span className="mt-auto flex flex-wrap items-center gap-2 pt-1">
          {pack.recommended && <Badge tone="primary">{t("packs.recommended")}</Badge>}
          {pack.installed && <Badge tone="success">{t("packs.installed")}</Badge>}
          {!pack.fit.ok && <Badge tone="warning">{t("fit.no")}</Badge>}
        </span>
        {!pack.fit.ok && problems.length > 0 && (
          <span className="text-xs text-muted-foreground" data-testid={`pack-reason-${pack.id}`}>
            {problems.join(" · ")}
          </span>
        )}
      </button>
    </li>
  );
}

/**
 * The Store: what can be installed, what is, and the install / removal flow. Only administrators
 * get the view (and make any request): the server refuses the others anyway.
 */
export function StorePage() {
  const { t } = useTranslation("store");
  const { status, user } = useAuth();
  if (status === "loading") return null; // no flash of "forbidden" while the profile loads
  if (user?.role !== "admin") {
    return (
      <div className="p-6" data-testid="view-store-forbidden">
        <p role="alert" className="text-sm text-destructive">
          {t("forbidden")}
        </p>
      </div>
    );
  }
  return <StoreView />;
}

function StoreView() {
  const { t, i18n } = useTranslation(["store", "errors", "common"]);
  const catalog = useFetched(() => modulesApi.catalog(), "modules");
  // The packs are a convenience on top of the catalogue: if they cannot be read, the catalogue
  // still works and the section is simply not shown.
  const packsData = useFetched(() => modulesApi.packs(), "packs");
  const [openPackId, setOpenPackId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const reloadCatalog = catalog.reload;
  const reloadPacks = packsData.reload;
  const operation = useModuleOperation(() => {
    reloadCatalog();
    reloadPacks();
  });
  useModuleStream({
    onStep: operation.onStep,
    onOperation: operation.onOperation,
    onResync: () => {
      catalog.reload();
      packsData.reload();
      void operation.resync();
    },
  });

  const modules = useMemo(() => catalog.data?.modules ?? [], [catalog.data]);
  const categories = useMemo(
    () => [...new Set(modules.map((m) => m.category))].sort((a, b) => a.localeCompare(b)),
    [modules],
  );
  const shown = modules.filter(
    (m) => (!category || m.category === category) && matches(m, query, i18n.language),
  );
  const open = modules.find((m) => m.id === openId) ?? null;
  const packs = packsData.data?.packs ?? [];
  const openPack = packs.find((p) => p.id === openPackId) ?? null;
  const running = operation.flow.stage === "running";
  const failed = operation.flow.stage === "failed";
  const finished = operation.flow.stage === "done";
  const reset = operation.reset;
  // An operation that ends while nobody is looking at it needs no further attention: the
  // catalogue has been refreshed. A failure stays visible until it is opened.
  useEffect(() => {
    if (finished && openId === null && openPackId === null) reset();
  }, [finished, openId, openPackId, reset]);

  return (
    <div className="flex flex-col gap-4 p-6" data-testid="view-store">
      <header className="flex flex-col gap-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Blocks className="h-5 w-5" aria-hidden="true" />
          {t("store:title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("store:description")}</p>
      </header>

      {(running || failed) && open === null && openPack === null && (
        <button
          type="button"
          onClick={() => {
            if (operation.flow.pack) setOpenPackId(operation.flow.pack);
            else setOpenId(operation.flow.target);
          }}
          data-testid="store-operation-banner"
          role={failed ? "alert" : "status"}
          className={cn(
            "flex items-center gap-2 rounded-lg border bg-card p-3 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            failed ? "border-destructive text-destructive" : "border-border",
          )}
        >
          {running && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
          {t(failed ? "store:bannerFailed" : "store:banner", { module: operation.flow.target })}
        </button>
      )}

      {packs.length > 0 && (
        <section aria-labelledby="store-packs-title" className="flex flex-col gap-2">
          <div className="flex flex-col gap-0.5">
            <h2 id="store-packs-title" className="text-base font-semibold">
              {t("store:packs.title")}
            </h2>
            <p className="text-sm text-muted-foreground">{t("store:packs.description")}</p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="store-packs">
            {packs.map((pack) => (
              <PackCard key={pack.id} pack={pack} onOpen={() => setOpenPackId(pack.id)} />
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("store:searchPlaceholder")}
          aria-label={t("store:search")}
          data-testid="store-search"
          className="sm:max-w-sm"
        />
        <Select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          aria-label={t("store:categoryLabel")}
          data-testid="store-category"
          className="sm:max-w-48"
        >
          <option value="">{t("store:allCategories")}</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {t(`store:category.${c}`, { defaultValue: c })}
            </option>
          ))}
        </Select>
      </div>

      {catalog.error != null && catalog.data === null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(t, catalog.error)}
        </p>
      )}
      {catalog.loading && catalog.data === null && <p role="status">{t("common:loading")}</p>}
      {catalog.data !== null && modules.length === 0 && (
        <p data-testid="store-empty" className="text-sm text-muted-foreground">
          {t("store:emptyCatalog")}
        </p>
      )}
      {modules.length > 0 && shown.length === 0 && (
        <p data-testid="store-no-match" className="text-sm text-muted-foreground">
          {t("store:noMatch")}
        </p>
      )}
      {shown.length > 0 && (
        <ul
          className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
          aria-label={t("store:listLabel")}
          data-testid="store-grid"
        >
          {shown.map((module) => (
            <ModuleCard key={module.id} module={module} onOpen={() => setOpenId(module.id)} />
          ))}
        </ul>
      )}

      <ModuleSheet module={open} operation={operation} onClose={() => setOpenId(null)} />
      <PackSheet pack={openPack} operation={operation} onClose={() => setOpenPackId(null)} />
    </div>
  );
}
