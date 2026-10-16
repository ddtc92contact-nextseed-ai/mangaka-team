// L'équipe : liste déroulante « Modèle » des agents DeepSeek (GET /providers/deepseek/models).
import type { AgentSetting, DeepSeekModel, DeepSeekModels } from "./api";

/** Valeur de l'entrée « Autre… » : le nom du modèle se tape alors dans un champ libre. */
export const OTHER_MODEL = "__autre__";

export interface ModelOption {
  value: string;
  text: string;
}

/** Le modèle n'est pas dans la liste : « Autre… » est sélectionné et le champ libre s'affiche. */
export function isOtherModel(list: DeepSeekModels | null, value: string): boolean {
  if (!list) return false; // liste pas encore chargée : la valeur s'affiche telle quelle
  return !list.models.some((m) => m.id === value.trim());
}

function optionText(m: DeepSeekModel, envModel: string | null): string {
  const note = m.note ? ` — ${m.note}` : "";
  return `${m.id}${note}${m.id === envModel ? " (choisi dans .env)" : ""}`;
}

/** Entrées de la liste déroulante : les modèles (id — note), puis « Autre… ». */
export function modelOptions(list: DeepSeekModels | null, value: string): ModelOption[] {
  if (!list) {
    const current = value.trim();
    return [...(current ? [{ value: current, text: current }] : []), { value: OTHER_MODEL, text: "Autre…" }];
  }
  return [...list.models.map((m) => ({ value: m.id, text: optionText(m, list.env_model) })), { value: OTHER_MODEL, text: "Autre…" }];
}

/**
 * Dernier geste de l'utilisateur sur le champ : « Autre… » choisi (ou nom tapé dans le champ libre),
 * ou un modèle pris dans la liste. `value` est la valeur que ce geste a produite.
 */
export interface ModelChoice {
  other: boolean;
  value: string;
}

/**
 * « Autre… » est actif : décidé par le dernier geste tant que la valeur est celle qu'il a produite
 * (taper « deepseek-chat-v2 » passe par « deepseek-chat » sans revenir à la liste), sinon déduit
 * de la valeur (chargement, réinitialisation).
 */
export function inOtherMode(list: DeepSeekModels | null, value: string, choice: ModelChoice | null): boolean {
  if (choice && choice.value === value) return choice.other;
  return isOtherModel(list, value);
}

/** Valeur de la liste déroulante pour la valeur du formulaire. */
export function selectValue(list: DeepSeekModels | null, value: string, choice: ModelChoice | null = null): string {
  return inOtherMode(list, value, choice) ? OTHER_MODEL : value.trim();
}

/** Valeur du formulaire après un choix dans la liste (« Autre… » : champ libre vide à remplir). */
export function pickModel(choice: string): string {
  return choice === OTHER_MODEL ? "" : choice;
}

/** Geste « choix dans la liste déroulante ». */
export function chooseModel(option: string): ModelChoice {
  return { other: option === OTHER_MODEL, value: pickModel(option) };
}

/** Geste « frappe dans le champ libre » : on reste sur « Autre… », même si le nom tapé est dans la liste. */
export function typeModel(text: string): ModelChoice {
  return { other: true, value: text };
}

/** Signale la valeur venue de .env (DEEPSEEK_MODEL) : null si .env ne remplace rien. */
export function envNote(setting: Pick<AgentSetting, "env_override" | "env_value">, value: string): string | null {
  if (!setting.env_override || !setting.env_value) return null;
  const used = value.trim() === setting.env_value;
  return `${setting.env_override}=${setting.env_value} dans .env remplace la valeur livrée${used ? " : c'est le modèle sélectionné" : " ; ce profil choisit un autre modèle"}.`;
}

/** D'où vient la liste, et ce qu'il faut savoir du modèle choisi. Messages en français. */
export function modelNotes(list: DeepSeekModels | null, value: string): string[] {
  if (!list) return [];
  const out = [
    list.source === "live"
      ? "Liste en direct de DeepSeek."
      : `Liste livrée (presets/providers.yaml)${list.detail ? ` : ${list.detail}` : ""}.`,
  ];
  const id = value.trim();
  const model = list.models.find((m) => m.id === id);
  if (!id) out.push(`Vide : le modèle par défaut (${list.default_model}) est utilisé.`);
  else if (!model && list.source === "live") out.push(`« ${id} » n'est pas dans la liste de DeepSeek : l'appel risque d'être refusé.`);
  else if (!model) out.push(`« ${id} » n'est pas dans la liste livrée : vérifie son nom chez DeepSeek.`);
  if (model?.reasoning || (!model && /reasoner/i.test(id)))
    out.push("Modèle qui raisonne : plus lent, la température n'est pas envoyée.");
  return out;
}
