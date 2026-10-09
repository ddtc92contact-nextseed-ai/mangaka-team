// Libellés et petits calculs du contrôle qualité (étape 4).
import type { PanelData, QCLayer, QCLayerName, QCVerdict } from "./api";

export const QC_VERDICT: Record<QCVerdict, string> = {
  ok: "OK",
  review: "À revoir",
  reject: "Rejet",
};

export const QC_LAYERS: { id: QCLayerName; label: string; hint: string }[] = [
  { id: "detectors", label: "Détecteurs", hint: "visages, mains, texte parasite" },
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

/** « 120 ms », « 1,4 s ». */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
}
