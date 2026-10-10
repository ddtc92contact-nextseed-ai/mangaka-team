// Finition d'impression : libellés du dpi effectif des cases (atelier, vue page).
import type { PageData, PrintInfo } from "./api";

/** « 115 dpi → 300 dpi après finition », « 300 dpi (finalisée) », « 312 dpi ». */
export function dpiLabel(info: PrintInfo): string {
  if (info.status === "ok") return `${info.dpi} dpi`;
  if (info.status === "finished") return `${info.dpi} dpi → ${info.finished_dpi} dpi (finalisée)`;
  return `${info.dpi} dpi → ${info.target_dpi} dpi après finition`;
}

/** Libellé court du badge posé sur la case. */
export function dpiShort(info: PrintInfo): string {
  if (info.status === "finished") return `${info.finished_dpi} dpi ✓`;
  if (info.status === "ok") return `${info.dpi} dpi ✓`;
  return `${info.dpi} dpi`;
}

/** Explication complète (infobulle, lecteur d'écran). */
export function dpiTitle(info: PrintInfo): string {
  const box = `${info.width_mm.toLocaleString("fr-FR")} × ${info.height_mm.toLocaleString("fr-FR")} mm imprimés (fond perdu compris)`;
  const source = `image retenue ${info.source_width} × ${info.source_height} px`;
  if (info.status === "ok") return `${info.dpi} dpi à l'impression : ${box}, ${source}. Pas besoin de finition.`;
  if (info.status === "finished")
    return `Finalisée : ${info.finished_width} × ${info.finished_height} px, ${info.finished_dpi} dpi (${box}${info.finished_upscaler ? `, ${info.finished_upscaler}` : ""}).`;
  return `Sous le seuil de ${info.min_dpi} dpi : ${info.dpi} dpi à l'impression (${box}, ${source}). La finition agrandit ×${info.factor.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} jusqu'à ${info.target_width} × ${info.target_height} px.`;
}

/** Cases de la page à finaliser (version retenue sous le seuil). */
export function panelsToFinish(page: PageData): number {
  return page.panels.filter((p) => p.print_info?.status === "low").length;
}
