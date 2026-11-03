import { useState } from "react";
import { useTranslation } from "react-i18next";
import { modelsApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { ModelListing, RoleRoutes as RoleRoutesData } from "../api/types";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";
import { Presets } from "./Presets";

const SLOTS = 3; // the chosen model, then up to two fallbacks (the server allows `max_chain`)

/** The models of a role as the three selects show them: empty slots are dropped on save. */
function toSlots(chain: string[] | undefined): string[] {
  return Array.from({ length: SLOTS }, (_, i) => chain?.[i] ?? "");
}

function toChain(slots: string[]): string[] {
  return [...new Set(slots.filter((name) => name !== ""))];
}

function RoleRows({
  data,
  models,
  fallback,
  onSaved,
}: {
  data: RoleRoutesData;
  models: string[];
  fallback: string;
  onSaved: (next: RoleRoutesData) => void;
}) {
  const { t } = useTranslation(["models", "errors"]);
  const action = useAsyncAction();
  const [draft, setDraft] = useState<Record<string, string[]>>(() =>
    Object.fromEntries(data.roles.map((role) => [role, toSlots(data.routes[role])])),
  );
  const [saved, setSaved] = useState(false);
  const options = [...new Set([...models, fallback])];

  function change(role: string, slot: number, value: string) {
    setSaved(false);
    setDraft((prev) => ({
      ...prev,
      [role]: (prev[role] ?? toSlots(undefined)).map((v, i) => (i === slot ? value : v)),
    }));
  }

  async function save() {
    const routes = Object.fromEntries(
      data.roles.map((role) => [role, toChain(draft[role] ?? [])]).filter(([, c]) => c.length > 0),
    );
    const ok = await action.run(async () => {
      onSaved(await modelsApi.saveRoutes(routes));
    });
    setSaved(ok);
  }

  return (
    <div className="grid gap-3" data-testid="role-routes">
      <h3 className="text-sm font-semibold">{t("routes.title")}</h3>
      <p className="text-sm text-muted-foreground">{t("routes.description")}</p>
      {data.roles.map((role) => (
        <fieldset
          key={role}
          className="grid gap-2 rounded-lg border border-border p-3"
          data-testid={`route-${role}`}
        >
          <legend className="px-1 text-sm font-medium">{t(`routes.role.${role}`)}</legend>
          <p className="text-xs text-muted-foreground">{t(`routes.hint.${role}`)}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {(draft[role] ?? []).map((value, slot) => (
              <Select
                key={slot}
                value={value}
                aria-label={t(slot === 0 ? "routes.first" : "routes.then", { n: slot })}
                data-testid={`route-${role}-${slot}`}
                onChange={(e) => change(role, slot, e.target.value)}
              >
                <option value="">
                  {slot === 0 ? t("routes.followDefault") : t("routes.none")}
                </option>
                {options.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
            ))}
          </div>
          <p className="text-xs text-muted-foreground" data-testid={`route-${role}-effective`}>
            {t("routes.effective", {
              chain: (data.effective[role] ?? []).join(" → "),
            })}
          </p>
        </fieldset>
      ))}
      {action.error && (
        <p role="alert" className="text-sm text-destructive" data-testid="routes-error">
          {action.error}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm text-muted-foreground" data-testid="routes-saved">
          {t("routes.saved")}
        </p>
      )}
      <div>
        <Button onClick={() => void save()} disabled={action.busy} data-testid="routes-save">
          {t("routes.save")}
        </Button>
      </div>
    </div>
  );
}

/** Which models each role tries, in order: the first one, then fallbacks when it cannot answer. */
export function RoleRoutes() {
  const { t } = useTranslation(["models", "errors"]);
  const routes = useFetched(() => modelsApi.routes(), "model-routes");
  const listing = useFetched<ModelListing>(() => modelsApi.list(), "model-routes-models");
  const [override, setOverride] = useState<RoleRoutesData | null>(null);
  // A preset replaces every route: the rows start again from what it stored.
  const [version, setVersion] = useState(0);
  const data = override ?? routes.data;

  if (routes.error != null && data === null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {errorMessage(t, routes.error)}
      </p>
    );
  }
  if (data === null || listing.data === null) return null;
  const names = [
    ...listing.data.models.map((m) => m.name),
    ...(listing.data.local ?? []).map((m) => m.name),
  ];
  return (
    <div className="grid gap-6">
      <Presets
        onApplied={(next) => {
          setOverride(next);
          setVersion((v) => v + 1);
        }}
      />
      <RoleRows
        key={version}
        data={data}
        models={names}
        fallback={listing.data.configured_default}
        onSaved={setOverride}
      />
    </div>
  );
}
