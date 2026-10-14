// Libellés et petits calculs du journal des générations (verdicts, tonalité, statistiques).
import type { Judge, JournalSettings, MeasureKey } from "./api";

export const VERDICT_LABEL: Record<string, string> = {
  validated: "Gardée",
  rejected: "Rejetée",
  regenerated: "Régénérée",
  edited: "Retouchée",
};

/** Ce qui a produit un verdict (action de l'auteur). */
export const ACTION_LABEL: Record<string, string> = {
  judge: "jugement",
  select: "version choisie",
  delete: "version supprimée",
  regenerate: "régénération",
  regenerate_quality: "régénération en Qualité",
  resketch: "re-croquis",
  validate_sketch: "croquis validé",
  crop: "recadrage",
  repair: "réparation",
  change_angle: "changement d'angle",
  qc_override: "« Valider quand même »",
  annotate: "annotation du banc QC",
  ab_choice: "comparaison A/B",
  keep: "gardée comme référence",
  refine: "affinée",
  choose_style: "essai de style retenu",
  stage_override: "étape du chapitre forcée",
  crowd_mark: "foule marquée sans fiche",
  crowd_unmark: "marque « foule sans fiche » levée",
};

export const AB_MODE_LABEL: Record<string, string> = {
  prompt: "deux prompts",
  tier: "deux paliers",
  cfg: "deux CFG",
};

const NUMBER = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

/** « 21,7 % » ; « — » sans valeur. */
export function formatPct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${NUMBER.format(value)} %`;
}

/** Écart à la cible en points : « +8,3 pts », « −1,2 pt », « = cible ». */
export function formatGap(gap: number | null | undefined): string {
  if (gap === null || gap === undefined) return "";
  const rounded = Math.round(gap * 10) / 10;
  if (rounded === 0) return "= cible";
  const abs = NUMBER.format(Math.abs(rounded));
  return `${rounded > 0 ? "+" : "−"}${abs} pt${Math.abs(rounded) >= 2 ? "s" : ""}`;
}

/** Couleur de l'écart : proche (≤ 3 pts), à surveiller (≤ 10), loin. */
export function gapTone(gap: number | null | undefined): "near" | "mid" | "far" | null {
  if (gap === null || gap === undefined) return null;
  const abs = Math.abs(gap);
  return abs <= 3 ? "near" : abs <= 10 ? "mid" : "far";
}

/** Libellé d'une mesure (réglages du journal, sinon la clé). */
export function measureLabel(settings: JournalSettings | null, key: MeasureKey): string {
  return settings?.measures.find((m) => m.key === key)?.label ?? key;
}

export type JudgeKeyAction = { verdict: Judge; reason: string | null } | null;

/**
 * Raccourcis du jugement en un clic : G = je garde, X = je rejette (sans raison), 1 à 9 = je rejette pour la
 * raison n (ordre de presets/journal.yaml).
 */
export function judgeKeyAction(key: string, reasons: { id: string }[]): JudgeKeyAction {
  const k = key.toLowerCase();
  if (k === "g") return { verdict: "validated", reason: null };
  if (k === "x") return { verdict: "rejected", reason: null };
  if (/^[1-9]$/.test(k)) {
    const reason = reasons[Number(k) - 1];
    return reason ? { verdict: "rejected", reason: reason.id } : null;
  }
  return null;
}

/** « 66,7 % (2/3) » ; « — » sans case jugée. */
export function rateLabel(rate: number | null, validated: number, judged: number): string {
  return rate === null ? "—" : `${NUMBER.format(rate)} % (${validated}/${judged})`;
}
