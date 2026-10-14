// Taille du texte d'une bulle redimensionnée à la main (écran Lettrage).

export interface BubbleFont {
  size_pt: number;
  /** Bornes du style de la bulle (fonts.yaml) : le texte d'un cadre ajusté à la main reste entre les deux. */
  min_size_pt: number;
  max_size_pt: number;
  /** Taille saisie à la main : elle ne suit pas le cadre. */
  manual_size: boolean;
  /** Taille normale du style (fonts.yaml `size_pt`) : à cette taille, les marges valent `margin_px`. */
  style_size_pt: number;
  /** Marges totales de la bulle autour du texte (px de la page) à la taille normale du style. */
  margin_px: { w: number; h: number };
}

/**
 * Aperçu pendant le glissé de la poignée : taille du texte (pt) dans le cadre `to`, depuis celle calculée
 * pour le cadre `from`. Même règle que le moteur : un cadre ajusté à la main est rempli avec des marges
 * proportionnelles à la taille du texte (cadre ×2 → texte ×2). `filled` : le cadre `from` est déjà rempli
 * ainsi (ajusté à la main) ; sinon (placement automatique) ses marges sont celles de la taille normale.
 * Le plus petit des deux côtés compte ; bornée au minimum et au plafond du style ; une taille saisie à la
 * main ne bouge pas. Le moteur recalcule la taille exacte au lâcher (même retour à la ligne : écart ≤ 0,5 pt).
 */
export function previewSizePt(
  font: BubbleFont,
  from: { w: number; h: number },
  to: { w: number; h: number },
  filled = false,
): number {
  if (font.manual_size || from.w <= 0 || from.h <= 0 || font.size_pt <= 0) return font.size_pt;
  const base = font.style_size_pt > 0 ? font.style_size_pt : font.size_pt;
  // Marges du cadre de départ, puis taille t telle que texte(t) + marges(t) = côté du cadre d'arrivée.
  const scale = filled ? font.size_pt / base : 1;
  const side = (f: number, t: number, margin: number) => {
    const text = Math.max(1, f - margin * scale);
    return t / (text / font.size_pt + margin / base);
  };
  const size = Math.min(side(from.w, to.w, font.margin_px.w), side(from.h, to.h, font.margin_px.h));
  const lo = Math.min(font.min_size_pt, font.size_pt);
  const hi = Math.max(font.max_size_pt, font.size_pt);
  return Math.round(Math.min(hi, Math.max(lo, size)) * 2) / 2;
}
