// Taille du texte d'une bulle redimensionnée à la main (écran Lettrage).

export interface BubbleFont {
  size_pt: number;
  /** Bornes du style de la bulle (fonts.yaml) : le texte d'un cadre ajusté à la main reste entre les deux. */
  min_size_pt: number;
  max_size_pt: number;
  /** Taille saisie à la main : elle ne suit pas le cadre. */
  manual_size: boolean;
}

/**
 * Aperçu pendant le glissé de la poignée : taille du texte (pt) dans le cadre `to`, depuis celle calculée
 * pour le cadre `from`. Proportionnelle au plus petit rapport des côtés, bornée au minimum et au plafond
 * du style ; une taille saisie à la main ne bouge pas. Le moteur recalcule la taille exacte au lâcher.
 */
export function previewSizePt(font: BubbleFont, from: { w: number; h: number }, to: { w: number; h: number }): number {
  if (font.manual_size || from.w <= 0 || from.h <= 0) return font.size_pt;
  const k = Math.min(to.w / from.w, to.h / from.h);
  const lo = Math.min(font.min_size_pt, font.size_pt);
  const hi = Math.max(font.max_size_pt, font.size_pt);
  return Math.round(Math.min(hi, Math.max(lo, font.size_pt * k)) * 2) / 2;
}
