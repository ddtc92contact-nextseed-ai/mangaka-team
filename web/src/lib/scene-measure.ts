// Name scène par scène : mesure de chaque scène face à son profil (moteur : pipeline/scene_name.py), affichée dans
// les écrans Scénario et Direction. Un écart est un avertissement, jamais un blocage.
import type { SceneMeasure, ShotClass } from "./api";

/** « 6 », « 4 à 5 », ou « — » sans valeur attendue. */
export function rangeText(min?: number, max?: number): string {
  if (min === undefined || max === undefined) return "—";
  return min === max ? `${min}` : `${min} à ${max}`;
}

const pct = (share: number) => `${Math.round(share * 100)} %`;

/** Part visée d'une famille de plans : « au moins 50 % », « au plus 17 % », « 15 à 40 % ». */
export function shareText(min: number, max: number): string {
  if (min > 0 && max < 1) return `${Math.round(min * 100)} à ${pct(max)}`;
  if (min > 0) return `au moins ${pct(min)}`;
  return `au plus ${pct(max)}`;
}

export interface ShotRow {
  cls: ShotClass;
  label: string;
  target: string;
  /** Cases de la famille, plans appliqués (ou proposés à défaut), sur le total des cases de la scène. */
  count: number | null;
  total: number;
  /** Hors de la part visée. */
  off: boolean;
}

/** Plans de la scène face à son profil : les plans appliqués aux cases s'ils le sont tous, sinon ceux que propose la
 * direction artistique, sinon rien encore. */
export function shotRows(m: SceneMeasure): { source: "appliqués" | "proposés" | null; rows: ShotRow[] } {
  const total = m.shots.total;
  const source =
    total > 0 && m.shots.applied === total ? "appliqués" : total > 0 && m.shots.proposed === total ? "proposés" : null;
  const counts = source === "appliqués" ? m.shots.applied_counts : source === "proposés" ? m.shots.proposed_counts : undefined;
  const rows = (m.expected.shots ?? []).map((s) => {
    const count = counts ? counts[s.class] ?? 0 : null;
    const allowed = s.max <= 0 ? 0 : Math.max(1, Math.floor(s.max * total + 1e-9));
    const off = count !== null && (count + 1e-9 < s.min * total || (s.max < 1 && count > allowed));
    return { cls: s.class, label: s.label, target: shareText(s.min, s.max), count, total, off };
  });
  return { source, rows };
}

export const MOTION_LABELS = { required: "lignes de mouvement imposées", forbidden: "lignes de mouvement interdites" };
