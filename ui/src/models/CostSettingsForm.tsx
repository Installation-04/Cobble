import { useState } from "react";
import { useTranslation } from "react-i18next";
import { costSettingsApi } from "../api/endpoints";
import type { CostSettings } from "../api/types";
import { errorMessage } from "../api/errors";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";

/** Settings → Models: electricity of local models and the cost cap per task (admin). */
export function CostSettingsForm() {
  const { t } = useTranslation(["costs", "errors"]);
  const fetched = useFetched(() => costSettingsApi.get(), "cost-settings");
  const data = fetched.data;
  if (fetched.error != null && data === null) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {errorMessage(t, fetched.error)}
      </p>
    );
  }
  if (data === null) return null;
  return <CostSettingsFields data={data} />;
}

function CostSettingsFields({ data }: { data: CostSettings }) {
  const { t } = useTranslation(["costs", "errors"]);
  const action = useAsyncAction();
  const [price, setPrice] = useState(data.electricity_price_kwh_usd ?? "");
  const [watts, setWatts] = useState(
    data.electricity_watts === null ? "" : String(data.electricity_watts),
  );
  const [counts, setCounts] = useState(data.electricity_counts_in_budget);
  const [multiplier, setMultiplier] = useState(data.task_budget_multiplier ?? "");
  const [saved, setSaved] = useState(false);

  async function save() {
    const ok = await action.run(async () => {
      await costSettingsApi.save({
        electricity_price_kwh_usd: price.trim() === "" ? null : price.trim(),
        electricity_watts: watts.trim() === "" ? null : Number.parseInt(watts, 10),
        electricity_counts_in_budget: counts,
        task_budget_multiplier: multiplier.trim() === "" ? null : multiplier.trim(),
      });
    });
    setSaved(ok);
  }

  return (
    <div className="grid gap-3" data-testid="cost-settings">
      <h3 className="text-sm font-semibold">{t("costs:settings.title")}</h3>
      <fieldset className="grid gap-2 rounded-lg border border-border p-3">
        <legend className="px-1 text-sm font-medium">{t("costs:settings.electricityTitle")}</legend>
        <p className="text-xs text-muted-foreground">{t("costs:settings.electricityHelp")}</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="grid gap-1">
            <Label htmlFor="cost-price">{t("costs:settings.price")}</Label>
            <Input
              id="cost-price"
              inputMode="decimal"
              value={price}
              data-testid="cost-price"
              onChange={(e) => {
                setSaved(false);
                setPrice(e.target.value);
              }}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="cost-watts">{t("costs:settings.watts")}</Label>
            <Input
              id="cost-watts"
              inputMode="numeric"
              value={watts}
              data-testid="cost-watts"
              onChange={(e) => {
                setSaved(false);
                setWatts(e.target.value);
              }}
            />
          </div>
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={counts}
            data-testid="cost-counts"
            onChange={(e) => {
              setSaved(false);
              setCounts(e.target.checked);
            }}
          />
          <span>{t("costs:settings.counts")}</span>
        </label>
      </fieldset>
      <fieldset className="grid gap-2 rounded-lg border border-border p-3">
        <legend className="px-1 text-sm font-medium">{t("costs:settings.taskTitle")}</legend>
        <p className="text-xs text-muted-foreground">
          {t("costs:settings.taskHelp", {
            floor: data.task_budget_floor_usd ?? "",
            default: data.effective_task_budget_multiplier ?? "",
          })}
        </p>
        <div className="grid gap-1 sm:max-w-xs">
          <Label htmlFor="cost-multiplier">{t("costs:settings.multiplier")}</Label>
          <Input
            id="cost-multiplier"
            inputMode="decimal"
            value={multiplier}
            data-testid="cost-multiplier"
            onChange={(e) => {
              setSaved(false);
              setMultiplier(e.target.value);
            }}
          />
        </div>
      </fieldset>
      {action.error && (
        <p role="alert" className="text-sm text-destructive" data-testid="cost-settings-error">
          {action.error}
        </p>
      )}
      {saved && (
        <p
          role="status"
          className="text-sm text-muted-foreground"
          data-testid="cost-settings-saved"
        >
          {t("costs:settings.saved")}
        </p>
      )}
      <div>
        <Button onClick={() => void save()} disabled={action.busy} data-testid="cost-settings-save">
          {t("costs:settings.save")}
        </Button>
      </div>
    </div>
  );
}
