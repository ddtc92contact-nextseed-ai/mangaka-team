// Libellés et petits calculs du contrôle qualité (étape 4).
import type {
  AnnotationLabel,
  BenchLayerName,
  DefectId,
  PanelData,
  QCLayer,
  QCLayerName,
  QCTone,
  QCVerdict,
} from "./api";

export const QC_VERDICT: Record<QCVerdict, string> = {
  ok: "OK",
  review: "À revoir",
  reject: "Rejet",
};

export const QC_LAYERS: { id: QCLayerName; label: string; hint: string }[] = [
  { id: "detectors", label: "Détecteurs", hint: "visages, mains, texte parasite, tonalité" },
  { id: "identity", label: "Cohérence des personnages", hint: "ressemblance aux fiches (CCIP)" },
  { id: "vision", label: "Vision", hint: "la case colle-t-elle à sa description ?" },
];

export const QC_LAYER_STATUS: Record<QCLayer["status"], string> = {
  done: "faite",
  skipped: "non lancée",
  unavailable: "indisponible",
  error: "en erreur",
};

export const QC_SOURCE: Record<string, string> = {
  auto: "automatique, après génération",
  manual: "relancé à la main",
  human: "décision humaine",
};

/** Case à relire par un humain : verdict « à revoir » ou « rejet » de la version choisie. */
export function needsReview(panel: Pick<PanelData, "qc_verdict">): boolean {
  return panel.qc_verdict === "review" || panel.qc_verdict === "reject";
}

function pct(x: number): string {
  return `${Math.round(x * 100)} %`;
}

/** « Tonalité : 68 % sombres (cible ≤ 45 %) · 30 % noir pur (cible ≤ 25 %) », ou pourquoi elle n'est pas vérifiée. */
export function toneSummary(tone: QCTone | null | undefined): string | null {
  if (!tone) return null;
  if (!tone.checked || tone.dark === null || tone.black === null) {
    return `Tonalité non vérifiée${tone.message ? ` : ${tone.message}` : ""}`;
  }
  const target = (max: number | null) => (max === null ? "" : ` (cible ≤ ${pct(max)})`);
  return `Tonalité : ${pct(tone.dark)} de pixels sombres${target(tone.max_dark)} · ${pct(tone.black)} de noir pur${target(tone.max_black)}`;
}

/** « 120 ms », « 1,4 s ». */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
}

// --- Banc d'essai du QC -------------------------------------------------------------

export const ANNOTATION_LABEL: Record<AnnotationLabel, string> = { good: "Bonne", bad: "Mauvaise" };

export const DEFECTS: { id: DefectId; label: string }[] = [
  { id: "face", label: "Visage raté" },
  { id: "hands", label: "Mains" },
  { id: "identity", label: "Perso pas reconnaissable" },
  { id: "description", label: "Ne colle pas à la description" },
  { id: "text", label: "Texte parasite" },
  { id: "other", label: "Autre" },
];

export const BENCH_LAYERS: { id: BenchLayerName; label: string; variable: string }[] = [
  { id: "detectors", label: "Détecteurs", variable: "score de la couche" },
  { id: "identity", label: "Cohérence des personnages", variable: "similarité minimale × 100" },
  { id: "vision", label: "Vision", variable: "score de la couche" },
  { id: "combined", label: "QC combiné", variable: "score combiné" },
];

/** « 87 % » (ou « — » si non mesurable). */
export function formatPct(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return `${Math.round(x * 100)} %`;
}
