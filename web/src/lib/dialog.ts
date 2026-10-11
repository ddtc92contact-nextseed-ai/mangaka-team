// Dialogue avec l'IA sur une case (atelier) : libellés et différence mot à mot entre l'ancien et le nouveau prompt.

export const DIALOG_STATUS: Record<string, string> = {
  proposed: "proposition en attente",
  applied: "appliquée",
  cancelled: "annulée",
};

/** Un morceau de texte : gardé, retiré (ancien prompt seulement) ou ajouté (nouveau prompt seulement). */
export interface DiffPart {
  text: string;
  kind: "same" | "removed" | "added";
}

/** Au-delà, la table de plus longue sous-suite commune serait trop grosse : tout est marqué changé. */
const MAX_CELLS = 400_000;

/** Différence mot à mot (plus longue sous-suite commune), morceaux consécutifs de même sorte fusionnés. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/\s+/).filter(Boolean);
  const b = after.split(/\s+/).filter(Boolean);
  const parts: DiffPart[] = [];
  const push = (text: string, kind: DiffPart["kind"]) => {
    const last = parts[parts.length - 1];
    if (last && last.kind === kind) last.text += ` ${text}`;
    else parts.push({ text, kind });
  };
  if ((a.length + 1) * (b.length + 1) > MAX_CELLS) {
    if (a.length) push(a.join(" "), "removed");
    if (b.length) push(b.join(" "), "added");
    return parts;
  }
  // lcs[i][j] : longueur de la plus longue sous-suite commune de a[i:] et b[j:].
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push(a[i], "same");
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) push(a[i++], "removed");
    else push(b[j++], "added");
  }
  while (i < a.length) push(a[i++], "removed");
  while (j < b.length) push(b[j++], "added");
  return parts;
}
