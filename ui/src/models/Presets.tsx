import { useState } from "react";
import { useTranslation } from "react-i18next";
import { modelsApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { PresetSlot, PresetsData, RoleRoutes } from "../api/types";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";

const SLOTS: PresetSlot[] = ["local", "cheap", "strong"];

function PresetCards({
  data,
  onApplied,
}: {
  data: PresetsData;
  onApplied: (routes: RoleRoutes) => void;
}) {
  const { t } = useTranslation(["models", "errors"]);
  const action = useAsyncAction();
  const [chosen, setChosen] = useState<Record<PresetSlot, string>>(() => ({
    local: data.suggested.local ?? "",
    cheap: data.suggested.cheap ?? "",
    strong: data.suggested.strong ?? "",
  }));
  const [preview, setPreview] = useState<PresetsData>(data);
  const [applied, setApplied] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function pick(slot: PresetSlot, value: string) {
    const next = { ...chosen, [slot]: value };
    setChosen(next);
    setApplied(null);
    setConfirming(null);
    await action.run(async () => {
      setPreview(await modelsApi.presets(next));
    });
  }

  async function apply(id: string) {
    const ok = await action.run(async () => {
      onApplied(await modelsApi.applyPreset(id, chosen));
    });
    setConfirming(null);
    setApplied(ok ? id : null);
  }

  return (
    <div className="grid gap-3" data-testid="presets">
      <h3 className="text-sm font-semibold">{t("presets.title")}</h3>
      <p className="text-sm text-muted-foreground">{t("presets.description")}</p>
      <div className="grid gap-2 sm:grid-cols-3">
        {SLOTS.map((slot) => (
          <div key={slot} className="grid gap-1">
            <Label htmlFor={`preset-slot-${slot}`}>{t(`presets.slot.${slot}`)}</Label>
            <Select
              id={`preset-slot-${slot}`}
              data-testid={`preset-slot-${slot}`}
              value={chosen[slot]}
              onChange={(e) => void pick(slot, e.target.value)}
            >
              <option value="">{t("presets.noModel")}</option>
              {(slot === "local" ? preview.local : preview.models).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{t(`presets.slotHint.${slot}`)}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {preview.presets.map((preset) => (
          <div
            key={preset.id}
            data-testid={`preset-${preset.id}`}
            data-available={preset.available}
            className="grid content-start gap-2 rounded-lg border border-border bg-card p-3 text-card-foreground"
          >
            <span className="font-medium">{t(`presets.name.${preset.id}`)}</span>
            <span className="text-sm text-muted-foreground">
              {t(`presets.summary.${preset.id}`)}
            </span>
            {preset.available ? (
              <ul className="grid gap-0.5 text-xs" data-testid={`preset-${preset.id}-routes`}>
                {Object.entries(preset.routes).map(([role, chain]) => (
                  <li key={role}>
                    <span className="text-muted-foreground">{t(`routes.role.${role}`)}</span>{" "}
                    {chain.join(" → ")}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-destructive" data-testid={`preset-${preset.id}-missing`}>
                {t("presets.needs", {
                  slots: preset.missing.map((slot) => t(`presets.slot.${slot}`)).join(", "),
                })}
              </p>
            )}
            {confirming === preset.id ? (
              <div className="grid gap-2">
                <p role="alert" className="text-xs">
                  {t("presets.confirm")}
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={action.busy}
                    onClick={() => void apply(preset.id)}
                    data-testid={`preset-${preset.id}-confirm`}
                  >
                    {t("presets.apply")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                    {t("presets.cancel")}
                  </Button>
                </div>
              </div>
            ) : (
              <div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!preset.available || action.busy}
                  onClick={() => setConfirming(preset.id)}
                  data-testid={`preset-${preset.id}-apply`}
                >
                  {t("presets.apply")}
                </Button>
              </div>
            )}
            {applied === preset.id && (
              <p role="status" className="text-xs text-muted-foreground">
                {t("presets.applied")}
              </p>
            )}
          </div>
        ))}
      </div>
      {action.error && (
        <p role="alert" className="text-sm text-destructive" data-testid="presets-error">
          {action.error}
        </p>
      )}
    </div>
  );
}

/** Ready-made sets of routes ("Économique local", "Équilibré"), filled with the owner's models. */
export function Presets({ onApplied }: { onApplied: (routes: RoleRoutes) => void }) {
  const { t } = useTranslation(["models", "errors"]);
  const presets = useFetched(() => modelsApi.presets(), "model-presets");
  if (presets.error != null && presets.data === null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {errorMessage(t, presets.error)}
      </p>
    );
  }
  if (presets.data === null) return null;
  return <PresetCards data={presets.data} onApplied={onApplied} />;
}
