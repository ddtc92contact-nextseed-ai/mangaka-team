/** LoRA d'une fiche (personnage, bibliothèque) ou de la série : un poids n'a de sens qu'avec un fichier. */

export const NO_LORA = "aucun LoRA";

/** Vrai quand un fichier de LoRA est choisi : son poids se montre et se règle ; sinon il est masqué. */
export function hasLoraFile(name: string | null | undefined): boolean {
  return Boolean(name?.trim());
}

function frNumber(x: number): string {
  return x.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

/** « LoRA aiko_v1.safetensors · poids 0,8 » ; « aucun LoRA » sans fichier (le poids stocké n'est pas montré). */
export function loraSummary(name: string | null | undefined, weight: number | null | undefined): string {
  if (!hasLoraFile(name)) return NO_LORA;
  const file = name!.trim().split("/").pop();
  return weight === null || weight === undefined || !Number.isFinite(weight)
    ? `LoRA ${file}`
    : `LoRA ${file} · poids ${frNumber(weight)}`;
}

/** Flux d'une série, vu par la fiche série ou une fiche de la bibliothèque. */
export interface LoraWorkflow {
  name: string;
  engine?: string | null;
  engine_name?: string | null;
  supports_lora?: boolean;
}

/**
 * Avertissement des champs LoRA quand le flux de la série n'en prend pas (pas de `lora_chain`) ; null quand il en prend, ou tant que le flux est inconnu. Le moteur, lui, ignore alors
 * ces LoRA et le note sur chaque génération.
 */
export function loraUnsupportedNotice(workflow: LoraWorkflow | null | undefined): string | null {
  if (!workflow || workflow.supports_lora !== false) return null;
  const engine = workflow.engine_name || workflow.name;
  return `Le flux de cette série (${engine}) ne prend pas de LoRA : les LoRA de la série et des fiches sont ignorés à la génération, et chaque génération le signale.`;
}
