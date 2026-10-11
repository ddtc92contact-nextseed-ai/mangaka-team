export function formatCfg(cfg: number): string {
  return cfg.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

/** Le prompt négatif n'est lu qu'au-dessus de cfg 1 : on le dit, pour ne plus induire en erreur. */
export function NegativeBadge({ cfg }: { cfg: number }) {
  const active = cfg > 1;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-xs ${active ? "bg-emerald-500/15 text-emerald-300" : "bg-zinc-800 text-zinc-400"}`}
      title={
        active
          ? `cfg ${formatCfg(cfg)} : le prompt négatif est lu par le modèle (pas de texte, pas de collage, pas de personnage en trop…).`
          : "À cfg 1, ComfyUI saute la passe négative : le prompt négatif est ignoré par le modèle."
      }
      data-testid="negative-state"
    >
      {active ? `négatif actif (cfg ${formatCfg(cfg)})` : "négatif inactif (cfg 1)"}
    </span>
  );
}
