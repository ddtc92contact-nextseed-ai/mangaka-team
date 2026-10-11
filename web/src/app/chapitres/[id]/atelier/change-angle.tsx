"use client";

import { useState } from "react";
import { AngleFields, TierRestriction, angleInput, angleLabel, angleWeight, initialAngleForm, type AngleForm } from "@/components/camera-angle";
import { InfoTip } from "@/components/info-tip";
import { Button } from "@/components/ui";
import { api, type CameraLoras, type PanelImage } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

/**
 * « Changer l'angle » : une nouvelle version de la case, la version choisie vue sous un autre angle de caméra
 * (LoRA Multiple-Angles, palier Qualité). Les autres versions ne bougent pas ; une génération à la fois.
 */
export function ChangeAngleBlock({
  panelId,
  chosen,
  busy,
  run,
  onQueued,
}: {
  panelId: number;
  chosen: PanelImage | null;
  busy: boolean;
  run: (action: () => Promise<void>, done?: string) => Promise<void>;
  onQueued: (message: string) => void;
}) {
  const camera = useEngineData(() => api.cameraLoras());
  const [open, setOpen] = useState(false);
  if (!camera.data || camera.data.angles.length === 0) return null;
  const catalog = camera.data;
  return (
    <div className="space-y-2" data-testid="change-angle">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => setOpen((o) => !o)}
          disabled={busy || catalog.angle_problem !== null || chosen === null}
          aria-expanded={open}
          title={chosen === null ? "Génère d'abord une version : c'est elle qui tourne" : undefined}
          data-testid="change-angle-toggle"
        >
          Changer l&apos;angle
        </Button>
        <InfoTip help="camera.change_angle" label="Changer l'angle" />
        {catalog.angle_problem !== null && <TierRestriction label={catalog.tier_label} detail={catalog.angle_problem} />}
      </div>
      {open && chosen && catalog.angle_problem === null && (
        <ChangeAngleForm
          key={panelId}
          catalog={catalog}
          panelId={panelId}
          chosen={chosen}
          busy={busy}
          run={run}
          onQueued={(message) => {
            setOpen(false);
            onQueued(message);
          }}
        />
      )}
    </div>
  );
}

function ChangeAngleForm({
  catalog,
  panelId,
  chosen,
  busy,
  run,
  onQueued,
}: {
  catalog: CameraLoras;
  panelId: number;
  chosen: PanelImage;
  busy: boolean;
  run: (action: () => Promise<void>, done?: string) => Promise<void>;
  onQueued: (message: string) => void;
}) {
  const [form, setForm] = useState<AngleForm>(() => initialAngleForm(catalog));
  const submit = () =>
    run(async () => {
      await api.changePanelAngle(panelId, { ...angleInput(form), source_image_id: chosen.id });
      onQueued(
        `Nouvelle version « ${angleLabel(catalog, form.angle)} » mise en file depuis la version ${chosen.version} (palier ${catalog.workflow_tier ?? "Qualité"}) : les autres versions ne bougent pas.`,
      );
    }, "Changement d'angle lancé");
  return (
    <div className="space-y-3 rounded-md border border-zinc-800 bg-zinc-900/40 p-3" data-testid="change-angle-form">
      <p className="flex items-center gap-1.5 text-xs text-zinc-500">
        Depuis la version {chosen.version} · palier {catalog.workflow_tier ?? "Qualité"} (~1 min), quel que soit celui de la série
        <InfoTip help="camera.tier" label="Palier des angles" />
      </p>
      <AngleFields catalog={catalog} form={form} onChange={setForm} disabled={busy} />
      <Button onClick={submit} disabled={busy || !form.angle || angleWeight(form) === null} data-testid="change-angle-submit">
        Générer sous cet angle
      </Button>
    </div>
  );
}
