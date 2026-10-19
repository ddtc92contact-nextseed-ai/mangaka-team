import type { Chapter } from "@/lib/api";
import type { ConfirmOptions } from "./confirm";

/** Ce qui reste quand on supprime des chapitres : tout ce qui appartient à la série elle-même. */
const KEPT = [
  "l'ADN de la série",
  "les personnages, décors, objets, véhicules et créatures, avec leurs fiches de référence et les variantes gardées",
  "la planche de style",
  "la charte de couverture, les palettes et le logo",
  "les tomes et leurs couvertures (un tome peut rester vide)",
  "les réglages des agents de la série",
  "la base de savoir et la bible (sauf les résumés des chapitres supprimés)",
  "les autres chapitres, qui gardent leur numéro",
];

function size(c: Chapter): string {
  if (!c.page_count) return "pas encore découpé";
  return `${c.page_count} page${c.page_count > 1 ? "s" : ""}, ${c.panel_count} case${c.panel_count > 1 ? "s" : ""}`;
}

/** Fenêtre de confirmation de la suppression d'un ou plusieurs chapitres : la liste, ce qui part, ce qui reste. */
export function chapterDeleteDialog(chapters: Chapter[]): ConfirmOptions {
  const many = chapters.length > 1;
  return {
    title: many ? `Supprimer ${chapters.length} chapitres ?` : `Supprimer le chapitre ${chapters[0]?.number} ?`,
    confirmLabel: many ? `Supprimer les ${chapters.length} chapitres` : "Supprimer le chapitre",
    danger: true,
    message: (
      <div className="space-y-3 whitespace-normal" data-testid="chapter-delete-message">
        <ul className="space-y-1 rounded-md bg-zinc-950/60 p-3" aria-label="Chapitres supprimés">
          {chapters.map((c) => (
            <li key={c.id} className="flex flex-wrap gap-x-2">
              <span className="font-mono text-zinc-500">#{c.number}</span>
              <span className="font-medium text-zinc-100">{c.title || `Chapitre ${c.number}`}</span>
              <span className="text-zinc-500">· {size(c)}</span>
            </li>
          ))}
        </ul>
        <p>
          {many ? "Ces chapitres partent" : "Ce chapitre part"} avec tout {many ? "leur" : "son"} contenu : pages,
          cases, images générées, bulles et lettrage, ainsi que {many ? "leurs" : "ses"} dossiers dans ComfyUI.{" "}
          {many ? "Leurs résumés quittent" : "Son résumé quitte"} la bible : le scénariste n&apos;en tirera plus de
          continuité. Action définitive.
        </p>
        <div>
          <p className="font-medium text-emerald-300">Ce qui reste intact :</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-zinc-400">
            {KEPT.map((k) => (
              <li key={k}>{k}</li>
            ))}
          </ul>
        </div>
      </div>
    ),
  };
}
