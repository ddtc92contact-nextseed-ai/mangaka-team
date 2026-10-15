// Garde d'étapes : libellés et petits calculs de la liste des étapes vitales d'un chapitre (moteur :
// pipeline/stage_gate.py). Le moteur refuse les actions ; l'écran l'annonce avant le clic.
import type { ChapterStage, StageKey } from "./api";

/** Actions gardées, avec le verbe que le moteur met dans `blocks` (« générer », « lettrer »…). */
export type StageAction = "script" | "layout" | "generation" | "clean" | "lettering" | "export" | "ready";

export const ACTION_VERB: Record<StageAction, string> = {
  script: "écrire le scénario",
  layout: "mettre en page",
  generation: "générer",
  clean: "passer au propre",
  lettering: "lettrer",
  export: "exporter",
  ready: "passer le chapitre en « prêt »",
};

/** Libellé du lien vers l'écran qui règle une étape. */
const SCREEN_LABEL: Record<string, string> = {
  scenes: "Aller aux Scènes",
  scenario: "Aller au Scénario",
  direction: "Aller à la Direction artistique",
  "mise-en-page": "Aller à la Mise en page",
  atelier: "Aller à l'Atelier",
  lettrage: "Aller au Lettrage",
  croquis: "Aller aux Croquis",
  personnages: "Ouvrir les fiches de la série",
};

/** Lien vers l'écran qui règle l'étape (onglet du chapitre, ou fiches de la série pour les références). */
export function stageHref(stage: Pick<ChapterStage, "screen">, chapterId: number, projectId: number): string {
  if (stage.screen === "personnages") return `/projets/${projectId}`;
  return `/chapitres/${chapterId}/${stage.screen}`;
}

export function stageLinkLabel(stage: Pick<ChapterStage, "screen">): string {
  return SCREEN_LABEL[stage.screen] ?? "Régler l'étape";
}

/** Étapes qui bloquent l'action en ce moment (ni réglées ni forcées). */
export function blockingStages(stages: ChapterStage[] | null | undefined, action: StageAction): ChapterStage[] {
  const verb = ACTION_VERB[action];
  return (stages ?? []).filter((s) => !s.passed && s.blocks.includes(verb));
}

/** Bandeau : « 5 pages de direction en attente » → phrase complète de l'étape qui bloque. */
export function blockingMessage(stage: ChapterStage, action: StageAction): string {
  const verb = ACTION_VERB[action];
  const before = /^[aeéèêiouh]/i.test(verb) ? `d'${verb}` : `de ${verb}`;
  return `${stage.label} : ${stage.summary}. ${stage.fix} avant ${before}.`;
}

/** Explication d'un bouton bloqué (attribut `title` et texte sous le bouton). */
export function blockedReason(stages: ChapterStage[], action: StageAction): string | null {
  const blocking = blockingStages(stages, action);
  if (!blocking.length) return null;
  return `Bloqué : ${blocking.map((s) => `${s.label.toLowerCase()} (${s.summary})`).join(", ")}`;
}

const DATE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" });

/** « forcée par Ouro le 13/10/2026 14:02 », « validée le … », null sans décision en cours. */
export function decisionLabel(stage: Pick<ChapterStage, "decision">): string | null {
  const d = stage.decision;
  if (!d || d.decision === "revoked") return null;
  const when = DATE.format(new Date(d.at));
  const who = d.author ? ` par ${d.author}` : "";
  return d.decision === "forced" ? `forcée${who} le ${when}` : `validée${who} le ${when}`;
}

/** Ordre des étapes (celui du moteur). */
export const STAGE_ORDER: StageKey[] = [
  "scenes",
  "script",
  "direction",
  "layout",
  "references",
  "prompts",
  "name",
  "approved",
  "lettering",
];
