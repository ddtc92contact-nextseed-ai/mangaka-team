// Tomes et couverture : aperçu à l'échelle, surimpression des zones réservées, chapitres libres.
// Sans import `@/` : testé par `node --test` (cover.test.ts).

/** Ce que l'aperçu lit d'un format de couverture (voir `CoverFormat` de api.ts). */
export interface CoverFormatLike {
  width_mm: number;
  height_mm: number;
  bleed_mm: number;
  safety_mm: number;
  full_width_mm: number;
  full_height_mm: number;
}

/** Rectangle en fraction de l'image complète (fond perdu compris). */
export interface RelRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Échelle de l'aperçu : 2,6 px d'écran par mm, la même pour tous les formats (13 × 18 plus petit que l'A4). */
export const PREVIEW_PX_PER_MM = 2.6;

/** Taille d'écran de l'aperçu « à l'échelle » (fond perdu compris), en px CSS. */
export function previewSize(fmt: CoverFormatLike, pxPerMm = PREVIEW_PX_PER_MM): { width: number; height: number } {
  return { width: Math.round(fmt.full_width_mm * pxPerMm), height: Math.round(fmt.full_height_mm * pxPerMm) };
}

/** Format rogné (trait de coupe) dans l'image complète. */
export function trimRect(fmt: CoverFormatLike): RelRect {
  return {
    x: fmt.bleed_mm / fmt.full_width_mm,
    y: fmt.bleed_mm / fmt.full_height_mm,
    width: fmt.width_mm / fmt.full_width_mm,
    height: fmt.height_mm / fmt.full_height_mm,
  };
}

/** Zone de sécurité (format rogné moins la marge de sécurité) dans l'image complète. */
export function safetyRect(fmt: CoverFormatLike): RelRect {
  const inset = fmt.bleed_mm + fmt.safety_mm;
  return {
    x: inset / fmt.full_width_mm,
    y: inset / fmt.full_height_mm,
    width: (fmt.width_mm - 2 * fmt.safety_mm) / fmt.full_width_mm,
    height: (fmt.height_mm - 2 * fmt.safety_mm) / fmt.full_height_mm,
  };
}

/** Position CSS (en %) d'un rectangle relatif, pour une surimpression `absolute`. */
export function rectStyle(r: RelRect): { left: string; top: string; width: string; height: string } {
  const pct = (v: number) => `${(v * 100).toFixed(3)}%`;
  return { left: pct(r.x), top: pct(r.y), width: pct(r.width), height: pct(r.height) };
}

/** Dimensions lisibles d'un format (« 130 × 180 mm · 300 dpi · fond perdu 3 mm »). */
export function formatSummary(fmt: CoverFormatLike & { dpi: number }): string {
  const mm = (v: number) => String(Math.round(v * 10) / 10).replace(".", ",");
  return `${mm(fmt.width_mm)} × ${mm(fmt.height_mm)} mm · ${fmt.dpi} dpi · fond perdu ${mm(fmt.bleed_mm)} mm`;
}

export interface VolumeLike {
  id: number;
  number: number;
  chapters: { id: number }[];
}

/** Tome qui contient déjà chaque chapitre (hors `volumeId`) : un chapitre n'est que dans un seul tome. */
export function chapterOwners(volumes: VolumeLike[], volumeId: number | null): Map<number, number> {
  const owners = new Map<number, number>();
  for (const v of volumes) {
    if (v.id === volumeId) continue;
    for (const c of v.chapters) owners.set(c.id, v.number);
  }
  return owners;
}

/** Numéro proposé pour un nouveau tome : le suivant du plus grand. */
export function nextVolumeNumber(volumes: { number: number }[]): number {
  return volumes.reduce((max, v) => Math.max(max, v.number), 0) + 1;
}

/** Chapitres cochés, dans l'ordre des numéros de chapitre (ordre de lecture du tome). */
export function orderedChapterIds(selected: Iterable<number>, chapters: { id: number; number: number }[]): number[] {
  const set = new Set(selected);
  return [...chapters].filter((c) => set.has(c.id)).sort((a, b) => a.number - b.number).map((c) => c.id);
}

// --- Composition de la couverture (1re, 4e, dos) ---

/** Signes espaces compris, comme le moteur : espaces et sauts de paragraphe comptent pour une espace. */
export function signCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).join(" ").length;
}

/** Longueur du résumé de 4e par rapport aux bornes du preset (« 742 signes · 600 à 900 »). */
export function summaryLength(text: string, min: number, max: number): { count: number; state: "short" | "ok" | "long"; label: string } {
  const count = signCount(text);
  const state = count < min ? "short" : count > max ? "long" : "ok";
  const hint = state === "short" ? " — un peu court" : state === "long" ? " — plus long que visé" : "";
  return { count, state, label: `${count} signe${count > 1 ? "s" : ""} · visé ${min} à ${max}${hint}` };
}

const FACE_NAMES = { front: "1re", spine: "dos", back: "4e" } as const;

/** Ordre de la couverture à plat, en mots (« 1re · dos · 4e — sens de lecture manga »). */
export function flatOrderLabel(order: (keyof typeof FACE_NAMES)[], direction: "ltr" | "rtl"): string {
  const faces = order.map((k) => FACE_NAMES[k]).join(" · ");
  return `${faces} — ${direction === "rtl" ? "sens de lecture manga (rtl) : la 1re est à gauche du dos" : "sens de lecture occidental (ltr) : la 1re est à droite du dos"}`;
}

/** Millimètres lisibles en français (« 12,1 mm »). */
export function mmLabel(mm: number): string {
  return `${String(Math.round(mm * 10) / 10).replace(".", ",")} mm`;
}
