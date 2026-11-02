import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { modelsApi } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { ModelConnection, ModelProbe, ModelProvider } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";
import { connectionName, isProvider, MODEL_EXAMPLE, PROVIDERS, URL_EXAMPLE } from "./connection";

function ProbeLine({ probe }: { probe: ModelProbe & { name: string } }) {
  const { t } = useTranslation("models");
  const Icon = probe.ok ? CheckCircle2 : XCircle;
  return (
    <p
      role={probe.ok ? "status" : "alert"}
      data-testid="model-test-result"
      data-code={probe.code}
      className={`flex items-start gap-2 text-sm ${probe.ok ? "" : "text-destructive"}`}
    >
      <Icon
        className={`mt-0.5 h-4 w-4 shrink-0 ${probe.ok ? "text-success" : ""}`}
        aria-hidden="true"
      />
      <span>
        <span className="font-medium">{probe.name}</span> {t(`test.${probe.code}`)}
      </span>
    </p>
  );
}

/**
 * Connect a model service with an API key, test it, choose which one answers. The key is typed
 * here and only ever sent: nothing in this component (or the API) can show it again.
 */
export function ModelConnections({ onChanged }: { onChanged?: () => void }) {
  const { t } = useTranslation(["models", "errors", "common"]);
  const listing = useFetched(() => modelsApi.list(), "models");
  const action = useAsyncAction();
  const [provider, setProvider] = useState<ModelProvider>("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [makeDefault, setMakeDefault] = useState(true);
  const [probe, setProbe] = useState<(ModelProbe & { name: string }) | null>(null);
  const [removing, setRemoving] = useState<ModelConnection | null>(null);

  const models = listing.data?.models ?? [];
  const name = connectionName(provider, model.trim());
  const ready = model.trim() !== "" && apiKey.trim() !== "" && name !== "";

  async function check(target: string) {
    const result = await modelsApi.test(target);
    setProbe({ ...result, name: target });
  }

  async function connect(event: FormEvent) {
    event.preventDefault();
    setProbe(null);
    const saved = await action.run(async () => {
      await modelsApi.put(name, {
        provider,
        model: model.trim(),
        api_key: apiKey.trim(),
        base_url: provider === "custom" ? baseUrl.trim() : null,
        make_default: makeDefault,
      });
      listing.reload();
      onChanged?.();
      await check(name);
    });
    if (saved) {
      setApiKey(""); // gone from the page as soon as it has been sent
      setModel("");
    }
  }

  return (
    <div className="grid gap-4" data-testid="model-connections">
      {listing.error != null && listing.data === null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(t, listing.error)}
        </p>
      )}

      {listing.data !== null && models.length === 0 && (
        <p data-testid="models-empty" className="text-sm text-muted-foreground">
          {t("empty", { model: listing.data.configured_default })}
        </p>
      )}

      {models.length > 0 && (
        <ul className="grid gap-2" aria-label={t("list")} data-testid="models-list">
          {models.map((m) => (
            <li
              key={m.name}
              data-testid={`model-${m.name}`}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3 text-sm"
            >
              <span className="font-medium">{m.name}</span>
              <span className="text-muted-foreground">{t(`provider.${m.provider}`)}</span>
              {m.default && <Badge tone="primary">{t("default")}</Badge>}
              <span className="ml-auto flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={action.busy}
                  onClick={() => void action.run(() => check(m.name))}
                  data-testid={`model-test-${m.name}`}
                >
                  {t("testAction")}
                </Button>
                {!m.default && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={action.busy}
                    onClick={() =>
                      void action.run(async () => {
                        await modelsApi.makeDefault(m.name);
                        listing.reload();
                        onChanged?.();
                      })
                    }
                    data-testid={`model-default-${m.name}`}
                  >
                    {t("makeDefault")}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={action.busy}
                  onClick={() => setRemoving(m)}
                  data-testid={`model-remove-${m.name}`}
                >
                  {t("remove")}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {probe && <ProbeLine probe={probe} />}

      <form onSubmit={(e) => void connect(e)} className="grid gap-3" data-testid="model-form">
        <h3 className="text-sm font-semibold">{t("add")}</h3>
        <div className="grid gap-1">
          <Label htmlFor="model-provider">{t("form.provider")}</Label>
          <Select
            id="model-provider"
            data-testid="model-provider"
            value={provider}
            onChange={(e) => {
              if (isProvider(e.target.value)) setProvider(e.target.value);
            }}
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {t(`provider.${p}`)}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="model-name">{t("form.model")}</Label>
          <Input
            id="model-name"
            data-testid="model-model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder={MODEL_EXAMPLE[provider]}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        {provider === "custom" && (
          <div className="grid gap-1">
            <Label htmlFor="model-base-url">{t("form.baseUrl")}</Label>
            <Input
              id="model-base-url"
              data-testid="model-base-url"
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={URL_EXAMPLE}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
        )}
        <div className="grid gap-1">
          <Label htmlFor="model-key">{t("form.apiKey")}</Label>
          <Input
            id="model-key"
            data-testid="model-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-describedby="model-key-help"
          />
          <p id="model-key-help" className="text-xs text-muted-foreground">
            {t("form.keyHelp")}
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={makeDefault}
            onChange={(e) => setMakeDefault(e.target.checked)}
            data-testid="model-make-default"
          />
          {t("form.makeDefault")}
        </label>
        {action.error && (
          <p role="alert" className="text-sm text-destructive" data-testid="model-error">
            {action.error}
          </p>
        )}
        {action.busy && (
          <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t("working")}
          </p>
        )}
        <div>
          <Button type="submit" disabled={!ready || action.busy} data-testid="model-submit">
            {t("form.submit")}
          </Button>
        </div>
      </form>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("removeTitle", { name: removing?.name })}
        description={removing?.default ? t("removeDefault") : t("removeDescription")}
        confirmLabel={t("remove")}
        onConfirm={async () => {
          if (!removing) return;
          await modelsApi.remove(removing.name);
          setRemoving(null);
          setProbe(null);
          listing.reload();
          onChanged?.();
        }}
      />
    </div>
  );
}
