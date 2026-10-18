// Alertes de noms de personnages d'une case (moteur : pipeline/names.py) : petits calculs des listes de l'atelier.
import type { NameNote } from "./api";

/** Clé React d'une alerte : unique même si le moteur renvoie deux fois le même nom (fiches retenues, puis rang). */
export function noteKey(note: Pick<NameNote, "kind" | "source" | "name" | "chosen">, index: number): string {
  return `${note.kind}-${note.source}-${note.name}-${note.chosen.map((c) => c.id).join("+")}-${index}`;
}
