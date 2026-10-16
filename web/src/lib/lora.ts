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
