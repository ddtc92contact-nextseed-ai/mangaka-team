"use client";

import { useId } from "react";
import type { AngleInput, CameraLoras } from "@/lib/api";
import { InfoTip } from "./info-tip";
import { Field, Input, Select } from "./ui";

/** Réglages d'une génération d'angle (formulaire) : angle, LoRA d'angle, poids (texte : saisie en cours). */
export interface AngleForm {
  angle: string;
  lora: string;
  weight: string;
}

export function initialAngleForm(catalog: CameraLoras | null): AngleForm {
  const lora = catalog?.loras.find((l) => l.role === "angles" && l.default) ?? catalog?.loras.find((l) => l.role === "angles");
  return { angle: catalog?.angles[0]?.id ?? "", lora: lora?.id ?? "", weight: lora ? String(lora.weight) : "1" };
}

/** Poids valide (0 à 2) du formulaire, ou null. */
export function angleWeight(form: AngleForm): number | null {
  const n = Number(form.weight.replace(",", "."));
  return form.weight.trim() !== "" && Number.isFinite(n) && n >= 0 && n <= 2 ? n : null;
}

export function angleInput(form: AngleForm): AngleInput {
  return { angle: form.angle, lora: form.lora || null, weight: angleWeight(form) };
}

/** Libellé français d'un angle du catalogue (l'id s'il est inconnu). */
export function angleLabel(catalog: CameraLoras | null | undefined, id: string | null | undefined): string {
  if (!id) return "";
  return catalog?.angles.find((a) => a.id === id)?.label ?? id;
}

/** « Disponible en palier Qualité » : l'option existe mais ne s'applique pas ici (jamais ignorée en silence). */
export function TierRestriction({ label, detail }: { label: string; detail?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" data-testid="tier-restriction">
      <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs font-medium text-amber-300" title={detail}>
        {label}
      </span>
      <InfoTip help="camera.tier" label={label} />
    </span>
  );
}

/** Angle de caméra, version du LoRA Multiple-Angles et poids (bulles d'aide sur le poids et le palier). */
export function AngleFields({
  catalog,
  form,
  onChange,
  disabled,
}: {
  catalog: CameraLoras;
  form: AngleForm;
  onChange: (form: AngleForm) => void;
  disabled?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const loras = catalog.loras.filter((l) => l.role === "angles");
  const lora = loras.find((l) => l.id === form.lora);
  const weightError = angleWeight(form) === null ? "De 0 à 2" : undefined;
  const set = (patch: Partial<AngleForm>) => onChange({ ...form, ...patch });
  return (
    <div className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_minmax(0,0.8fr)] sm:items-start">
      <Field label="Angle de caméra" htmlFor={`${id}-angle`} help="camera.angle">
        <Select
          id={`${id}-angle`}
          value={form.angle}
          disabled={disabled}
          onChange={(e) => set({ angle: e.target.value })}
          data-testid="camera-angle"
        >
          {catalog.angles.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="LoRA d'angle" htmlFor={`${id}-lora`} help="camera.lora" hint={lora?.description}>
        <Select
          id={`${id}-lora`}
          value={form.lora}
          disabled={disabled}
          onChange={(e) => {
            const next = loras.find((l) => l.id === e.target.value);
            set({ lora: e.target.value, ...(next ? { weight: String(next.weight) } : {}) });
          }}
          data-testid="camera-lora"
        >
          {loras.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
              {l.default ? " (par défaut)" : ""}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Poids" htmlFor={`${id}-weight`} help="camera.weight" error={weightError}>
        <Input
          id={`${id}-weight`}
          type="number"
          min={0}
          max={2}
          step={0.05}
          value={form.weight}
          disabled={disabled}
          onChange={(e) => set({ weight: e.target.value })}
          aria-invalid={Boolean(weightError)}
          data-testid="camera-weight"
        />
      </Field>
    </div>
  );
}
