// Bibliothèque d'une série : personnages, objets, décors, véhicules et créatures récurrents (mêmes fiches, mêmes
// écrans).
import type { LibraryKind, PanelObjectKind } from "./api";

export interface LibraryKindInfo {
  kind: LibraryKind;
  /** Onglet et titre de liste. */
  tab: string;
  /** Segment d'URL des écrans (`/bibliotheque/objets/…`) et valeur de `?onglet=`. */
  slug: string;
  /** « personnage », « objet », « décor », « véhicule », « créature ». */
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
  /** Libellé du choix de catégorie (objet ↔ véhicule ↔ créature). */
  category?: string;
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
    category: "Objet (accessoire, arme, outil…)",
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
  vehicle: {
    kind: "vehicle",
    tab: "Véhicules",
    slug: "vehicules",
    singular: "véhicule",
    newTitle: "Nouveau véhicule",
    createLabel: "Créer le véhicule",
    addLabel: "Créer un véhicule",
    emptyList: "Aucun véhicule récurrent dans cette série",
    saved: "Véhicule enregistré.",
    deleteConfirm: (name) => `Supprimer le véhicule « ${name} » et ses images de référence ? Il sera retiré des cases qui le montrent.`,
    namePlaceholder: "Le Faucon d'argent",
    descriptionHint: "Silhouette, proportions, couleurs, marquages, détails : ce qui doit rester identique sous tous les angles.",
    descriptionPlaceholder: "Vaisseau effilé argenté, deux réacteurs bleus à l'arrière, cockpit vitré à l'avant, bande rouge sur le flanc",
    keywordsPlaceholder: "vaisseau argenté, réacteurs bleus, bande rouge",
    loraLabel: "LoRA du véhicule (optionnel)",
    loraPlaceholder: "faucon_v1.safetensors",
    imagesHint: "Vue 3/4, profil, face, dessus, arrière : la vue qui correspond au cadrage de la case passe en premier.",
    badge: "bg-emerald-500/15 text-emerald-200",
    category: "Véhicule (vaisseau, voiture, moto, mécha piloté…)",
  },
  creature: {
    kind: "creature",
    tab: "Créatures",
    slug: "creatures",
    singular: "créature",
    newTitle: "Nouvelle créature",
    createLabel: "Créer la créature",
    addLabel: "Créer une créature",
    emptyList: "Aucune créature récurrente dans cette série",
    saved: "Créature enregistrée.",
    deleteConfirm: (name) => `Supprimer la créature « ${name} » et ses images de référence ? Elle sera retirée des cases qui la montrent.`,
    namePlaceholder: "Momo",
    descriptionHint: "Tête, corps, pelage ou écailles, marques, taille : ce qui la rend reconnaissable. Une créature ne parle pas : elle n'entre pas dans la distribution.",
    descriptionPlaceholder: "Petit chat roux aux oreilles noires, tache blanche en étoile sur le front, queue touffue",
    keywordsPlaceholder: "chat roux, oreilles noires, étoile blanche",
    loraLabel: "LoRA de la créature (optionnel)",
    loraPlaceholder: "momo_v1.safetensors",
    imagesHint: "Portrait de face, corps entier de face, de profil et de dos : elles guideront chaque case où elle apparaît.",
    badge: "bg-lime-500/15 text-lime-200",
    category: "Créature (animal, monstre, créature récurrente)",
  },
};

export const LIBRARY_ORDER: LibraryKind[] = ["character", "object", "decor", "vehicle", "creature"];

/** Sortes qu'une case montre dans « objets » (et entre lesquelles une fiche peut changer de catégorie). */
export const PANEL_OBJECT_KINDS: PanelObjectKind[] = ["object", "vehicle", "creature"];

export function isPanelObjectKind(kind: LibraryKind | string | undefined): kind is PanelObjectKind {
  return PANEL_OBJECT_KINDS.includes(kind as PanelObjectKind);
}

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
