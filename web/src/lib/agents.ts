// L'équipe : libellés et petites fonctions partagées par les écrans des agents.
import type { AgentSetting, AgentState, SettingOrigin } from "./api";

export const ORIGIN_LABEL: Record<SettingOrigin, string> = {
  preset: "Preset livré",
  global: "Profil global",
  series: "Cette série",
};

export const STATE_TONE: Record<AgentState, string> = {
  ready: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  down: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  misconfigured: "bg-red-500/15 text-red-300 ring-red-500/30",
};

/** Valeur telle que le formulaire l'édite (listes en lignes, nombres en texte). */
export function toFormValue(setting: AgentSetting, value: unknown): unknown {
  if (setting.type === "list" || setting.type === "prompt_list") {
    return Array.isArray(value) ? value.join("\n") : String(value ?? "");
  }
  if (setting.type === "number" || setting.type === "integer") return value === null || value === undefined ? "" : String(value);
  if (setting.type === "boolean") return Boolean(value);
  if (setting.type === "choice") return value ?? "";
  return value ?? "";
}

/** Valeur envoyée au moteur (il refait toutes les vérifications). */
export function fromFormValue(setting: AgentSetting, value: unknown): unknown {
  if (setting.type === "choice" && value === "" && setting.nullable) return null;
  if ((setting.type === "number" || setting.type === "integer") && typeof value === "string") {
    const n = Number(value.trim().replace(",", "."));
    return value.trim() !== "" && Number.isFinite(n) ? n : value;
  }
  return value;
}

/** Valeur lisible (historique, aperçu). */
export function displayValue(value: unknown, max = 120): string {
  if (value === null || value === undefined || value === "") return "—";
  let text: string;
  if (typeof value === "boolean") text = value ? "oui" : "non";
  else if (typeof value === "number") text = value.toLocaleString("fr-FR", { maximumFractionDigits: 4 });
  else if (Array.isArray(value)) text = value.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(" · ");
  else if (typeof value === "object" && "collections" in value && "top_k" in value) {
    const k = value as { collections: string[]; top_k: number };
    text = `${k.collections.join(", ") || "aucune collection"} (top-k ${k.top_k})`;
  } else if (typeof value === "object") text = JSON.stringify(value);
  else text = String(value);
  text = text.replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

const TEMPLATE = /\$(?:(\$)|([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\}|())/g;

/** Même règle que le moteur : `$variable` connue, `$$` pour un dollar. Message en français ou null. */
export function checkTemplate(text: string, variables: string[]): string | null {
  const unknown: string[] = [];
  for (const m of text.matchAll(TEMPLATE)) {
    if (m[1]) continue;
    const name = m[2] ?? m[3];
    if (name === undefined) return "Gabarit invalide : un « $ » isolé doit s'écrire « $$ »";
    if (!variables.includes(name) && !unknown.includes(name)) unknown.push(name);
  }
  if (!unknown.length) return null;
  const plural = unknown.length > 1 ? "s" : "";
  const listed = variables.map((v) => `$${v}`).join(", ") || "aucune";
  return `Variable${plural} inconnue${plural} : ${unknown.map((v) => `$${v}`).join(", ")} (disponibles : ${listed})`;
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";
}
