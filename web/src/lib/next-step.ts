// Étape d'un chapitre pas encore permise : à partir du message du moteur (« découpe d'abord le chapitre… »,
// « page pas encore mise en page… »), l'onglet où faire ce qui manque.

export type ChapterStep = "scenario" | "direction" | "mise-en-page" | "croquis" | "atelier";

export interface NextStep {
  step: ChapterStep;
  /** Libellé du bouton qui mène à l'étape. */
  label: string;
}

const STEPS: { step: ChapterStep; label: string; pattern: RegExp }[] = [
  { step: "scenario", label: "Aller au Scénario", pattern: /découpe d'abord|aucune page à (diriger|mettre en page)|écris d'abord le synopsis/ },
  { step: "direction", label: "Aller à la Direction artistique", pattern: /lance d'abord l'agent|lance l'agent d'abord/ },
  {
    step: "mise-en-page",
    label: "Aller à la Mise en page",
    pattern: /pas (encore )?mise? en page|calcule la mise en page d'abord|lance « recalculer » d'abord/,
  },
  { step: "croquis", label: "Aller aux Croquis", pattern: /valide d'abord une composition|croque-la d'abord/ },
  { step: "atelier", label: "Aller à l'Atelier", pattern: /génère d'abord (la case|une version)/ },
];

/** Étape à faire d'abord d'après un message d'erreur, ou `null` (erreur ordinaire). */
export function nextStep(message: string): NextStep | null {
  const text = message.toLowerCase().replace(/[’`]/g, "'");
  const found = STEPS.find((s) => s.pattern.test(text));
  return found ? { step: found.step, label: found.label } : null;
}

/** Lien vers l'onglet d'un chapitre (`/chapitres/12/mise-en-page`). */
export const stepHref = (chapterId: number, step: ChapterStep) => `/chapitres/${chapterId}/${step}`;
