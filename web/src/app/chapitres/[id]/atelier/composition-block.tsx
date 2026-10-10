"use client";

import { useEffect, useState } from "react";
import { ImageDropzone } from "@/components/image-dropzone";
import { Alert, Button, Field, Input, Select } from "@/components/ui";
import {
  api,
  engineUrl,
  type CompositionLock,
  type ControlStatus,
  type ControlTypeInfo,
  type PanelDetail,
  type PanelImage,
} from "@/lib/api";

const PREVIEW_POLL_MS = 1500;

/** Force affichée « 1 », « 0,85 ». */
export const formatStrength = (v: number) => v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });

function parseStrength(text: string): number | null {
  const v = Number(text.replace(",", ".").trim());
  return text.trim() !== "" && Number.isFinite(v) && v >= 0 && v <= 2 ? v : null;
}

/** Badge « composition verrouillée » (atelier, Production). */
export function LockBadge({ title }: { title?: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-medium text-sky-200"
      title={title ?? "Composition verrouillée : les régénérations suivent l'image guide (ControlNet)"}
      data-testid="lock-badge"
    >
      <span aria-hidden>🔒</span> composition verrouillée
    </span>
  );
}

type SourceChoice = "croquis" | "version" | "import";

/**
 * Verrouillage de composition d'une case (ControlNet Union) : source (croquis validé, version, image
 * importée), type de contrôle, force ; aperçu de la carte ; déverrouillage. Masqué avec un message clair
 * quand ComfyUI n'a pas le patch ou son nœud.
 */
export function CompositionBlock({
  panel,
  status,
  statusError,
  busy,
  run,
  onDetail,
  onReload,
  onDone,
}: {
  panel: PanelDetail;
  status: ControlStatus | null;
  statusError: string | null;
  busy: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
  onDetail: (detail: PanelDetail) => void;
  onReload: () => void;
  onDone: (message: string) => void;
}) {
  const lock = panel.composition_lock ?? null;
  const computing = lock !== null && (lock.preview.status === "pending" || lock.preview.status === "running");

  // Aperçu de la carte en cours de calcul (file ComfyUI) : on relit la case jusqu'au résultat.
  useEffect(() => {
    if (!computing) return;
    const timer = setInterval(onReload, PREVIEW_POLL_MS);
    return () => clearInterval(timer);
  }, [computing, onReload]);

  return (
    <div className="space-y-3 rounded-lg border border-zinc-800 p-3" data-testid="panel-composition">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-300">Composition</h3>
        {lock && <LockBadge />}
      </div>
      {statusError && !status ? (
        <Alert>Disponibilité du verrouillage inconnue : {statusError}</Alert>
      ) : !status ? (
        <p className="text-xs text-zinc-500">Vérification du ControlNet dans ComfyUI…</p>
      ) : lock ? (
        <LockedView
          panelId={panel.id}
          lock={lock}
          status={status}
          busy={busy}
          run={run}
          onDetail={onDetail}
          onDone={onDone}
        />
      ) : !status.available ? (
        <p className="text-xs text-amber-300" data-testid="composition-unavailable">
          {status.message ?? "Verrouillage de composition indisponible."} La composition reste guidée par le texte ; les
          autres paliers fonctionnent normalement.
        </p>
      ) : (
        <LockForm panel={panel} status={status} busy={busy} run={run} onDetail={onDetail} onDone={onDone} />
      )}
    </div>
  );
}

function TypeSelect({
  id,
  types,
  value,
  onChange,
  disabled,
}: {
  id: string;
  types: ControlTypeInfo[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
      {types.map((t) => (
        <option key={t.id} value={t.id} disabled={!t.available} title={t.problem ?? t.description}>
          {t.name}
          {t.available ? "" : " (indisponible)"}
        </option>
      ))}
    </Select>
  );
}

function LockForm({
  panel,
  status,
  busy,
  run,
  onDetail,
  onDone,
}: {
  panel: PanelDetail;
  status: ControlStatus;
  busy: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
  onDetail: (detail: PanelDetail) => void;
  onDone: (message: string) => void;
}) {
  const sketch = panel.images.find((i) => i.id === panel.sketch_image_id) ?? null;
  const versions = panel.images;
  const firstAvailable = status.types.find((t) => t.available)?.id ?? "";
  const defaultType =
    status.types.find((t) => t.id === status.default_type && t.available)?.id ?? firstAvailable;
  const [source, setSource] = useState<SourceChoice>(sketch ? "croquis" : versions.length ? "version" : "import");
  const [imageId, setImageId] = useState<number | null>(
    () => (versions.find((i) => i.selected) ?? versions[versions.length - 1] ?? null)?.id ?? null,
  );
  const [file, setFile] = useState<File | null>(null);
  const [type, setType] = useState(defaultType);
  const [strengthText, setStrengthText] = useState(formatStrength(status.default_strength ?? 1));
  const strength = parseStrength(strengthText);
  const chosenType = status.types.find((t) => t.id === type) ?? null;

  const ready =
    Boolean(type) &&
    strength !== null &&
    (source === "croquis" ? sketch !== null : source === "version" ? imageId !== null : file !== null);

  const lock = () =>
    run(async () => {
      const detail =
        source === "import" && file
          ? await api.lockCompositionFromImport(panel.id, file, type, strength)
          : await api.lockComposition(panel.id, {
              source: source === "croquis" ? "croquis" : "version",
              image_id: source === "croquis" ? sketch?.id : imageId,
              type,
              strength,
            });
      onDetail(detail);
      setFile(null);
      onDone(
        `Composition verrouillée (${detail.composition_lock?.type_name ?? type}) : toute régénération de la case suivra cette image guide jusqu'au déverrouillage.`,
      );
    });

  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-400">
        Impose le cadrage et les poses d&apos;une image guide à toutes les régénérations de la case (ControlNet).
      </p>
      <fieldset className="space-y-1.5">
        <legend className="mb-1 text-sm font-medium text-zinc-300">Image guide</legend>
        <SourceRadio
          value="croquis"
          current={source}
          onChange={setSource}
          disabled={!sketch}
          label={sketch ? `Croquis validé (v${sketch.version})` : "Croquis validé (aucun pour l'instant)"}
        />
        <SourceRadio
          value="version"
          current={source}
          onChange={setSource}
          disabled={versions.length === 0}
          label="Une version de la case"
        />
        {source === "version" && versions.length > 0 && (
          <Select
            aria-label="Version qui sert d'image guide"
            value={imageId ?? ""}
            onChange={(e) => setImageId(Number(e.target.value))}
            className="!ml-6 !w-auto"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {versionLabel(v)}
              </option>
            ))}
          </Select>
        )}
        <SourceRadio value="import" current={source} onChange={setSource} label="Une image importée (croquis à la main, photo de pose)" />
        {source === "import" && (
          <div className="ml-6 space-y-1">
            <ImageDropzone
              onFiles={(files) => setFile(files[0] ?? null)}
              disabled={busy}
              label={file ? `Image choisie : ${file.name}` : "Glisse l'image guide ici (PNG, JPEG, WebP)"}
            />
          </div>
        )}
      </fieldset>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type de contrôle" htmlFor="control-type" hint={chosenType?.description}>
          <TypeSelect id="control-type" types={status.types} value={type} onChange={setType} disabled={busy} />
        </Field>
        <Field
          label="Force"
          htmlFor="control-strength"
          error={strength === null ? "Entre 0 et 2" : undefined}
          hint="1 = composition tenue ; plus bas = plus libre."
        >
          <Input
            id="control-strength"
            inputMode="decimal"
            value={strengthText}
            onChange={(e) => setStrengthText(e.target.value)}
            aria-invalid={strength === null || undefined}
          />
        </Field>
      </div>
      <Button onClick={lock} disabled={busy || !ready} data-testid="lock-composition">
        Verrouiller la composition
      </Button>
    </div>
  );
}

function versionLabel(v: PanelImage): string {
  const kind = v.kind === "croquis" ? "croquis" : "version";
  return `${kind} v${v.version}${v.selected ? " (choisie)" : ""}${v.tier ? ` · ${v.tier}` : ""}`;
}

function SourceRadio({
  value,
  current,
  onChange,
  label,
  disabled,
}: {
  value: SourceChoice;
  current: SourceChoice;
  onChange: (v: SourceChoice) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label className={`flex items-center gap-2 text-sm ${disabled ? "text-zinc-600" : "text-zinc-200"}`}>
      <input
        type="radio"
        name="composition-source"
        value={value}
        checked={current === value}
        onChange={() => onChange(value)}
        disabled={disabled}
        className="accent-rose-500"
      />
      {label}
    </label>
  );
}

function LockedView({
  panelId,
  lock,
  status,
  busy,
  run,
  onDetail,
  onDone,
}: {
  panelId: number;
  lock: CompositionLock;
  status: ControlStatus;
  busy: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
  onDetail: (detail: PanelDetail) => void;
  onDone: (message: string) => void;
}) {
  const [typeDraft, setTypeDraft] = useState<string | null>(null);
  const [strengthText, setStrengthText] = useState<string | null>(null);
  const type = typeDraft ?? lock.type;
  const strengthValue = strengthText ?? formatStrength(lock.strength);
  const strength = parseStrength(strengthValue);
  const dirty = type !== lock.type || (strength !== null && strength !== lock.strength);
  const preview = lock.preview;
  const computing = preview.status === "pending" || preview.status === "running";
  const types = status.types.length ? status.types : [{ id: lock.type, name: lock.type_name, description: "", preprocessor: null, available: true, problem: null }];

  const save = () =>
    run(async () => {
      const detail = await api.updateCompositionLock(panelId, {
        ...(type !== lock.type ? { type } : {}),
        ...(strength !== null && strength !== lock.strength ? { strength } : {}),
      });
      onDetail(detail);
      setTypeDraft(null);
      setStrengthText(null);
      onDone(type !== lock.type ? "Type de contrôle changé : nouvelle carte en calcul." : "Force du contrôle enregistrée.");
    });
  const unlock = () =>
    run(async () => {
      onDetail(await api.unlockComposition(panelId));
      onDone("Composition déverrouillée : les prochaines générations repartent du texte seul.");
    });
  const recompute = () =>
    run(async () => {
      onDetail(await api.refreshCompositionPreview(panelId));
    });

  return (
    <div className="space-y-3" data-testid="composition-locked">
      <div className="grid grid-cols-2 gap-2">
        <figure className="space-y-1">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={engineUrl(lock.source_url)}
            alt={`Image guide : ${lock.source_label}`}
            className="aspect-square w-full rounded border border-zinc-800 bg-zinc-950 object-contain"
          />
          <figcaption className="text-[11px] text-zinc-400">Image guide · {lock.source_label}</figcaption>
        </figure>
        <figure className="space-y-1" aria-live="polite">
          {preview.url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={engineUrl(preview.url)}
              alt={`Carte de contrôle (${lock.type_name})`}
              className={`aspect-square w-full rounded border border-zinc-800 bg-white object-contain ${computing ? "opacity-40" : ""}`}
              data-testid="control-map"
            />
          ) : (
            <div className="flex aspect-square w-full items-center justify-center rounded border border-dashed border-zinc-800 p-2 text-center text-[11px] text-zinc-500">
              {computing ? "Calcul de la carte dans ComfyUI…" : preview.status === "failed" ? "Carte non calculée" : "Pas d'aperçu"}
            </div>
          )}
          <figcaption className="text-[11px] text-zinc-400">
            Carte de contrôle · {lock.type_name}
            {computing && " · calcul en cours…"}
          </figcaption>
        </figure>
      </div>
      {preview.status === "failed" && (
        <Alert>
          Aperçu de la carte en échec : {preview.error ?? "erreur inconnue"}{" "}
          <button type="button" className="underline" onClick={recompute} disabled={busy}>
            Recalculer
          </button>
        </Alert>
      )}
      <p className="text-xs text-zinc-400">
        Toute régénération de la case suit cette image guide ({lock.type_name}, force {formatStrength(lock.strength)})
        {lock.preset_name ? ` — ${lock.preset_name}` : ""}, jusqu&apos;au déverrouillage.
      </p>
      {lock.problem && <Alert>{lock.problem}</Alert>}
      {!status.available && (
        <Alert>
          {status.message ?? "Verrouillage de composition indisponible."} Déverrouille la case pour la régénérer sans.
        </Alert>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type de contrôle" htmlFor="lock-type">
          <TypeSelect id="lock-type" types={types} value={type} onChange={setTypeDraft} disabled={busy || !status.available} />
        </Field>
        <Field label="Force" htmlFor="lock-strength" error={strength === null ? "Entre 0 et 2" : undefined}>
          <Input
            id="lock-strength"
            inputMode="decimal"
            value={strengthValue}
            onChange={(e) => setStrengthText(e.target.value)}
            aria-invalid={strength === null || undefined}
          />
        </Field>
      </div>
      <div className="flex flex-wrap gap-2">
        {dirty && (
          <Button variant="secondary" className="!px-2.5 !py-1 text-xs" onClick={save} disabled={busy || strength === null}>
            Enregistrer
          </Button>
        )}
        <Button variant="ghost" className="!px-2.5 !py-1 text-xs" onClick={unlock} disabled={busy} data-testid="unlock-composition">
          Déverrouiller
        </Button>
      </div>
    </div>
  );
}
