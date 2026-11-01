import type { TFunction } from "i18next";
import type { BadgeTone } from "../components/ui/badge";
import type { ModuleEntry, ModuleState } from "../api/types";

/** The description in the user's language; English if a translation is ever missing. */
export function localizedDescription(module: ModuleEntry, lang: string): string {
  const description = module.description;
  return (
    (lang === "fr" ? description.fr : description.en) || description.en || description.fr || ""
  );
}

export function stateTone(state: ModuleState | undefined): BadgeTone {
  switch (state) {
    case "running":
      return "success";
    case "installing":
    case "removing":
      return "primary";
    case "failed":
      return "destructive";
    default:
      return "neutral";
  }
}

/** Why a module does not fit this machine, in words ("needs 8192 MB of memory, ... has 4096"). */
export function fitProblems(t: TFunction, module: ModuleEntry): string[] {
  if (module.hardware.ok) return [];
  const gpu = (value: string) => t(`store:gpu.${value}`, { defaultValue: value });
  return module.hardware.problems.map((problem) =>
    problem.code === "ram"
      ? t("store:fit.ram", { needed: problem.needed, have: problem.have })
      : t("store:fit.gpu", { needed: gpu(problem.needed), have: gpu(problem.have) }),
  );
}
