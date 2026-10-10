// Bibliothèque d'une série : personnages, objets et décors récurrents (mêmes fiches, mêmes écrans).
import type { LibraryKind } from "./api";

export interface LibraryKindInfo {
  kind: LibraryKind;
  /** Onglet et titre de liste. */
  tab: string;
  /** Segment d'URL des écrans (`/bibliotheque/objets/…`) et valeur de `?onglet=`. */
  slug: string;
  /** « personnage », « objet », « décor ». */
  singular: string;
  newTitle: string;
  createLabel: string;
  addLabel: string;
  emptyList: string;
  saved: string;
  deleteConfirm: (name: string) => string;
  namePlaceholder: string;
  descriptionHint: string;
  descriptionPlaceholder: string;
  keywordsPlaceholder: string;
  loraLabel: string;
  loraPlaceholder: string;
  imagesHint: string;
  /** Pastille dans l'atelier et le scénario. */
  badge: string;
}

export const LIBRARY_KINDS: Record<LibraryKind, LibraryKindInfo> = {
  character: {
    kind: "character",
    tab: "Personnages",
    slug: "personnages",
    singular: "personnage",
    newTitle: "Nouveau personnage",
    createLabel: "Créer le personnage",
    addLabel: "Nouveau personnage",
    emptyList: "Aucun personnage dans cette série",
    saved: "Personnage enregistré.",
    deleteConfirm: (name) => `Supprimer ${name} et ses images de référence ?`,
    namePlaceholder: "Aiko",
    descriptionHint: "Ce qui doit rester identique d'une case à l'autre : visage, coiffure, tenue, signes distinctifs.",
    descriptionPlaceholder: "Jeune femme, cheveux noirs courts, cicatrice sur la joue gauche, kimono rouge",
    keywordsPlaceholder: "aiko, kimono rouge, katana",
    loraLabel: "LoRA d'identité (optionnel)",
    loraPlaceholder: "aiko_v1.safetensors",
    imagesHint: "Planche de référence, visage, profil, tenue : elles guideront la génération de chaque case.",
    badge: "bg-violet-500/15 text-violet-200",
  },
  object: {
    kind: "object",
    tab: "Objets",
    slug: "objets",
    singular: "objet",
    newTitle: "Nouvel objet",
    createLabel: "Créer l'objet",
    addLabel: "Nouvel objet",
    emptyList: "Aucun objet récurrent dans cette série",
    saved: "Objet enregistré.",
    deleteConfirm: (name) => `Supprimer l'objet « ${name} » et ses images de référence ? Il sera retiré des cases qui le montrent.`,
    namePlaceholder: "Robot R-2",
    descriptionHint: "Forme, couleurs, matières, détails à garder d'une case à l'autre.",
    descriptionPlaceholder: "Petit robot rond en métal blanc, antenne rouge, un œil bleu lumineux",
    keywordsPlaceholder: "robot rond, antenne rouge, œil bleu",
    loraLabel: "LoRA de l'objet (optionnel)",
    loraPlaceholder: "robot_r2_v1.safetensors",
    imagesHint: "Vues de face, de profil, détails : elles guideront chaque case où l'objet apparaît.",
    badge: "bg-sky-500/15 text-sky-200",
  },
  decor: {
    kind: "decor",
    tab: "Décors",
    slug: "decors",
    singular: "décor",
    newTitle: "Nouveau décor",
    createLabel: "Créer le décor",
    addLabel: "Nouveau décor",
    emptyList: "Aucun décor récurrent dans cette série",
    saved: "Décor enregistré.",
    deleteConfirm: (name) => `Supprimer le décor « ${name} » et ses images de référence ? Il sera retiré des cases qui s'y passent.`,
    namePlaceholder: "Le labo",
    descriptionHint: "Architecture, mobilier, lumière, ambiance : ce qui rend le lieu reconnaissable.",
    descriptionPlaceholder: "Laboratoire encombré sous les toits, néons blafards, établi couvert de pièces détachées",
    keywordsPlaceholder: "laboratoire, néons, établi",
    loraLabel: "LoRA du décor (optionnel)",
    loraPlaceholder: "labo_v1.safetensors",
    imagesHint: "Plans d'ensemble, angles caractéristiques : ils guideront chaque case qui s'y passe.",
    badge: "bg-amber-500/15 text-amber-200",
  },
};

export const LIBRARY_ORDER: LibraryKind[] = ["character", "object", "decor"];

export function kindFromSlug(slug: string | null | undefined): LibraryKind | null {
  return LIBRARY_ORDER.find((k) => LIBRARY_KINDS[k].slug === slug) ?? null;
}

/** Fiche d'une entrée (les personnages gardent leur adresse historique `/personnages/{id}`). */
export function entryHref(kind: LibraryKind, id: number): string {
  return kind === "character" ? `/personnages/${id}` : `/bibliotheque/${LIBRARY_KINDS[kind].slug}/${id}`;
}

export function newEntryHref(kind: LibraryKind, projectId: number): string {
  return `/projets/${projectId}/bibliotheque/${LIBRARY_KINDS[kind].slug}/nouveau`;
}

export function libraryHref(projectId: number, kind: LibraryKind = "character"): string {
  return `/bibliotheque?serie=${projectId}&onglet=${LIBRARY_KINDS[kind].slug}`;
}
