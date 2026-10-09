// Sens de lecture d'une série : libellés, badge et choix en grandes cartes (groupe de boutons radio).
import type { ReadingDirection } from "@/lib/api";

export const DIRECTIONS: Record<ReadingDirection, string> = {
  rtl: "Droite → gauche (manga)",
  ltr: "Gauche → droite (BD, comics)",
};

const OPTIONS: { value: ReadingDirection; title: string; detail: string }[] = [
  { value: "rtl", title: "Manga — droite → gauche", detail: "On commence en haut à droite, reliure à droite." },
  {
    value: "ltr",
    title: "BD / comics / webtoon européen — gauche → droite",
    detail: "On commence en haut à gauche, reliure à gauche.",
  },
];

const BADGE_TONE: Record<ReadingDirection, string> = {
  rtl: "bg-rose-500/15 text-rose-200 ring-rose-500/30",
  ltr: "bg-sky-500/15 text-sky-200 ring-sky-500/30",
};

const BADGE_LABEL: Record<ReadingDirection, string> = { rtl: "← Manga", ltr: "BD →" };

/** Badge compact avec la flèche du sens de lecture. */
export function DirectionBadge({ direction }: { direction: ReadingDirection }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE_TONE[direction]}`}
      title={`Sens de lecture : ${DIRECTIONS[direction]}`}
      data-testid="direction-badge"
    >
      <span className="sr-only">Sens de lecture : </span>
      {BADGE_LABEL[direction]}
    </span>
  );
}

// Planche schématique : 2 bandes de 2 cases, numérotées dans l'ordre de lecture.
const CELLS = [
  { x: 4, y: 4 },
  { x: 34, y: 4 },
  { x: 4, y: 34 },
  { x: 34, y: 34 },
];

function OrderDiagram({ direction }: { direction: ReadingDirection }) {
  // Ordre de lecture → case de la grille (miroir horizontal en manga).
  const order = direction === "ltr" ? [0, 1, 2, 3] : [1, 0, 3, 2];
  const center = (i: number) => ({ cx: CELLS[order[i]].x + 13, cy: CELLS[order[i]].y + 13 });
  const path = [0, 1, 2, 3].map((i) => `${i ? "L" : "M"}${center(i).cx} ${center(i).cy}`).join(" ");
  return (
    <svg viewBox="0 0 64 64" className="h-20 w-20 shrink-0" aria-hidden="true">
      <rect x="0.5" y="0.5" width="63" height="63" rx="3" className="fill-zinc-950 stroke-zinc-700" />
      {CELLS.map((c, i) => (
        <rect key={i} x={c.x} y={c.y} width="26" height="26" rx="1.5" className="fill-zinc-800 stroke-zinc-500" />
      ))}
      <path d={path} className="fill-none stroke-rose-400/70" strokeWidth="1.5" strokeDasharray="2 2" />
      {[0, 1, 2, 3].map((i) => (
        <text
          key={i}
          x={center(i).cx}
          y={center(i).cy + 4}
          textAnchor="middle"
          className="fill-zinc-100 text-[11px] font-semibold"
        >
          {i + 1}
        </text>
      ))}
    </svg>
  );
}

/**
 * Choix du sens de lecture : deux cartes à égalité. Ce sont de vrais boutons radio (masqués),
 * donc Tab entre dans le groupe, les flèches changent le choix et Espace sélectionne.
 */
export function DirectionPicker({
  value,
  onChange,
  error,
}: {
  value: ReadingDirection | undefined;
  onChange: (value: ReadingDirection) => void;
  error?: string;
}) {
  return (
    <fieldset aria-describedby="reading_direction-help" className="space-y-2">
      <legend className="text-sm font-medium text-zinc-300">Sens de lecture</legend>
      <p id="reading_direction-help" className={`text-xs ${error ? "text-red-400" : "text-zinc-500"}`} role={error ? "alert" : undefined}>
        {error ?? "Il décide de l'ordre des cases, de la reliure et de la place des bulles. Modifiable ensuite."}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {OPTIONS.map((o) => {
          const checked = value === o.value;
          return (
            <label
              key={o.value}
              className={`flex cursor-pointer items-center gap-4 rounded-xl border p-4 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-rose-400 ${
                checked
                  ? "border-rose-400 bg-rose-500/10"
                  : error
                    ? "border-red-500/60 bg-zinc-950 hover:border-zinc-500"
                    : "border-zinc-700 bg-zinc-950 hover:border-zinc-500"
              }`}
            >
              <input
                type="radio"
                name="reading_direction"
                value={o.value}
                checked={checked}
                onChange={() => onChange(o.value)}
                className="sr-only"
                data-testid={`direction-${o.value}`}
              />
              <OrderDiagram direction={o.value} />
              <span className="min-w-0">
                <span className="block font-semibold text-zinc-100">{o.title}</span>
                <span className="mt-1 block text-xs text-zinc-400">{o.detail}</span>
              </span>
              <span
                aria-hidden="true"
                className={`ml-auto flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                  checked ? "border-rose-400 bg-rose-400" : "border-zinc-600"
                }`}
              >
                {checked && <span className="h-2 w-2 rounded-full bg-zinc-950" />}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
