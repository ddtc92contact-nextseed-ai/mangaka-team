"use client";

import { useState } from "react";
import { useToast } from "@/components/toast";
import { Alert, Select } from "@/components/ui";
import { api, engineUrl, fullErrorMessage, type PanelDetail, type ReferenceChoice } from "@/lib/api";

/**
 * Sélecteur de fiche : pour chaque personnage à l'image, l'image de référence qui passera en tête à la prochaine
 * génération de la case (portrait, expressions, planche de poses…), ou « Automatique » (vue la plus proche de
 * l'angle, puis du plan). Écrit dans `reference_choice` de la case ; les autres cases ne bougent pas.
 */
export function ReferenceChooser({
  detail,
  disabled,
  onSaved,
}: {
  detail: PanelDetail;
  disabled?: boolean;
  onSaved: (next: PanelDetail) => void;
}) {
  const choices = detail.reference_choices ?? [];
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  if (!choices.length) return null;

  async function choose(r: ReferenceChoice, value: string) {
    const imageId = value ? Number(value) : null;
    setBusy(r.character_id);
    setError(null);
    try {
      onSaved(await api.setReferenceChoice(detail.id, r.character_id, imageId));
      const label = r.images.find((i) => i.image_id === imageId)?.label;
      toast(label ? `Fiche de ${r.name} : ${label}` : `Fiche de ${r.name} : automatique`);
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <fieldset className="space-y-2 text-xs" data-testid="reference-chooser">
      <legend className="mb-1 text-zinc-500">Fiche envoyée en tête (prochaine génération)</legend>
      {error && <Alert>{error}</Alert>}
      {choices.map((r) => {
        const current = r.images.find((i) => i.image_id === r.current_image_id) ?? null;
        const automatic = r.images.find((i) => i.image_id === r.automatic_image_id)?.label ?? "image principale";
        const id = `reference-choice-${detail.id}-${r.character_id}`;
        return (
          <div key={r.character_id} className="flex items-center gap-2" data-testid="reference-choice" data-character={r.name}>
            {current ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={engineUrl(current.url)}
                alt={`Fiche de ${r.name} : ${current.label}`}
                className="h-10 w-10 shrink-0 rounded bg-zinc-950 object-cover"
              />
            ) : (
              <span className="h-10 w-10 shrink-0 rounded bg-zinc-950" aria-hidden />
            )}
            <div className="min-w-0 flex-1">
              <label htmlFor={id} className="block text-zinc-300">
                {r.name}
                {r.chosen_image_id !== null && <span className="ml-1 text-rose-300">· choisie pour la case</span>}
              </label>
              <Select
                id={id}
                value={r.chosen_image_id ?? ""}
                onChange={(e) => choose(r, e.target.value)}
                disabled={disabled || busy !== null || r.images.length < 2}
                title={r.images.length < 2 ? `${r.name} n'a qu'une image de référence` : undefined}
                className="!py-1 text-xs"
              >
                <option value="">Automatique ({automatic})</option>
                {r.images.map((img) => (
                  <option key={img.image_id} value={img.image_id}>
                    {img.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        );
      })}
    </fieldset>
  );
}
