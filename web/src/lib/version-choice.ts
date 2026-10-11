// Action principale d'une version dans « Versions » : choisir une version propre, valider un croquis.
// Sans import `@/` : testé par `node --test` (version-choice.test.ts).

export interface VersionLike {
  id: number;
  kind?: string;
  selected: boolean;
}

export type VersionAction = "select" | "validate" | null;

export interface VersionChoice {
  /** Ce que fait le bouton (null : rien, la version est déjà retenue). */
  action: VersionAction;
  /** Libellé de la vue simple. */
  label: string;
  /** Libellé court de la comparaison. */
  short: string;
  /** Version déjà retenue par la case (choisie, ou croquis validé). */
  retained: boolean;
  title?: string;
}

export const isSketchVersion = (img: Pick<VersionLike, "kind">): boolean => img.kind === "croquis";

/** Croquis retenu par la case (`validatedSketchId`) ou version propre choisie. */
export function isRetained(img: VersionLike, validatedSketchId: number | null): boolean {
  return isSketchVersion(img) ? img.id === validatedSketchId : img.selected;
}

export function versionChoice(img: VersionLike, validatedSketchId: number | null): VersionChoice {
  const retained = isRetained(img, validatedSketchId);
  if (isSketchVersion(img)) {
    return retained
      ? { action: null, label: "Croquis validé", short: "Validé", retained, title: "La case part de ce croquis (aperçu, cadrage, « Passer au propre »)" }
      : {
          action: "validate",
          label: "Valider ce croquis",
          short: "Choisir celle-ci",
          retained,
          title: "La case partira de ce croquis : aperçu, mise en page et « Passer au propre »",
        };
  }
  return retained
    ? { action: null, label: "Version choisie", short: "Choisie", retained }
    : { action: "select", label: "Choisir cette version", short: "Choisir celle-ci", retained };
}
