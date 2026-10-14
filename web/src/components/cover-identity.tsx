import type { CoverIdentity } from "@/lib/api";

function fr(x: number): string {
  return x.toFixed(2).replace(".", ",");
}

/**
 * Contrôle d'identité d'une version de couverture (charte des couvertures) : chaque personnage comparé à sa fiche.
 * Un écart est un avertissement visible, jamais un blocage.
 */
export function IdentityBadge({ identity, compact = false }: { identity: CoverIdentity | null; compact?: boolean }) {
  if (!identity) return null;
  if (identity.status !== "done") {
    if (identity.status === "skipped" || compact) return null;
    return (
      <p className="text-[10px] text-zinc-500" data-testid="cover-identity">
        Identité non vérifiée : {identity.message}
      </p>
    );
  }
  const off = identity.characters.filter((c) => !c.ok);
  const detail = identity.characters.map((c) => `${c.name} ${fr(c.similarity)}`).join(" · ");
  if (!off.length) {
    return (
      <p className="text-[10px] text-emerald-300" title={detail} data-testid="cover-identity">
        Identité conforme{compact ? "" : ` (${detail})`}
      </p>
    );
  }
  return (
    <div
      className="rounded border border-amber-500/50 bg-amber-500/10 px-1.5 py-1 text-[10px] leading-snug text-amber-200"
      role="status"
      title={identity.warnings.join("\n")}
      data-testid="cover-identity-warning"
    >
      ⚠ Ne ressemble pas à sa fiche : {off.map((c) => `${c.name} (${fr(c.similarity)})`).join(", ")}
    </div>
  );
}
