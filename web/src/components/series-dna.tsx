"use client";

import { useMemo, useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, Loading } from "@/components/ui";
import { api, EngineError, errorMessage, type DnaField, type DnaValue, type PreDirection } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

/** « 0.35 » → « 35 % », 4 → « 4 », true → « oui ». */
export function formatDna(field: DnaField, value: DnaValue | undefined): string {
  if (value === undefined) return "—";
  if (field.kind === "bool") return value ? "oui" : "non";
  if (field.kind === "share") return `${Math.round(Number(value) * 100)} %`;
  return String(value);
}

function same(a: DnaValue | undefined, b: DnaValue | undefined): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
  return a === b;
}

/**
 * ADN de la série : la charte chiffrée (cases par planche, formes de planche, échelle des plans, présence,
 * dialogue, courbe de rythme). Valeurs héritées du genre, ajustables une à une par des curseurs bornés.
 */
export function SeriesDnaCard({ projectId, genreKey }: { projectId: number; genreKey?: string | null }) {
  const dna = useEngineData(() => api.getPreDirection(projectId), [projectId, genreKey]);
  return (
    <Card data-testid="series-dna">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-1.5 font-semibold text-zinc-100">
          ADN de la série
          <InfoTip help="serie.adn" label="ADN de la série" />
        </h2>
        {dna.data?.available && (
          <span className="text-xs text-zinc-500" data-testid="dna-summary">
            {dna.data.genre_name ? `Hérité du genre « ${dna.data.genre_name} »` : "Valeurs par défaut (pas de genre)"} ·{" "}
            {adjustedLabel(Object.keys(dna.data.overrides).length)}
          </span>
        )}
      </div>
      <p className="mb-4 text-sm text-zinc-400">
        La charte chiffrée que reçoivent le scénariste et le directeur artistique. Une règle enfreinte les relance,
        puis devient un avertissement : jamais un blocage.
      </p>
      {dna.loading && !dna.data ? (
        <Loading />
      ) : dna.error || !dna.data ? (
        <Alert>{dna.error ?? "ADN introuvable"}</Alert>
      ) : !dna.data.available ? (
        <Alert tone="info">ADN indisponible : presets/pre_direction.yaml absent ou invalide.</Alert>
      ) : (
        <DnaForm key={JSON.stringify(dna.data.effective)} projectId={projectId} initial={dna.data} onSaved={dna.setData} />
      )}
    </Card>
  );
}

function adjustedLabel(n: number): string {
  return n === 0 ? "aucune valeur ajustée" : `${n} valeur${n > 1 ? "s" : ""} ajustée${n > 1 ? "s" : ""}`;
}

function DnaForm({
  projectId,
  initial,
  onSaved,
}: {
  projectId: number;
  initial: PreDirection;
  onSaved: (d: PreDirection) => void;
}) {
  const [values, setValues] = useState<Record<string, DnaValue>>(initial.effective);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const groups = useMemo(() => {
    const out: { key: string; label: string; fields: DnaField[] }[] = [];
    for (const f of initial.fields) {
      let g = out.find((x) => x.key === f.group);
      if (!g) {
        g = { key: f.group, label: initial.groups[f.group] ?? f.group, fields: [] };
        out.push(g);
      }
      g.fields.push(f);
    }
    return out;
  }, [initial]);
  const dirty = initial.fields.some((f) => !same(values[f.path], initial.effective[f.path]));

  async function save(next: Record<string, DnaValue>) {
    setBusy(true);
    setErrors({});
    try {
      const overrides = Object.fromEntries(
        initial.fields.filter((f) => !same(next[f.path], initial.inherited[f.path])).map((f) => [f.path, next[f.path]]),
      );
      onSaved(await api.savePreDirection(projectId, overrides));
      toast("ADN de la série enregistré");
    } catch (err) {
      setErrors(
        err instanceof EngineError && Object.keys(err.fieldErrors).length ? err.fieldErrors : { form: errorMessage(err) },
      );
    } finally {
      setBusy(false);
    }
  }

  const set = (path: string, value: DnaValue) => setValues((v) => ({ ...v, [path]: value }));
  const formErrors = Object.entries(errors).filter(([k]) => !initial.fields.some((f) => f.path === k));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void save(values);
      }}
      className="space-y-4"
      noValidate
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {groups.map((g) => (
          <fieldset key={g.key} className="rounded-lg border border-zinc-800 p-3" data-testid={`dna-group-${g.key}`}>
            <legend className="px-1 text-sm font-medium text-zinc-200">{g.label}</legend>
            <ul className="space-y-3">
              {g.fields.map((f) => (
                <DnaRow
                  key={f.path}
                  field={f}
                  value={values[f.path]}
                  inherited={initial.inherited[f.path]}
                  genre={initial.genre_name}
                  error={errors[f.path]}
                  disabled={busy}
                  onChange={(v) => set(f.path, v)}
                />
              ))}
            </ul>
          </fieldset>
        ))}
      </div>
      {formErrors.map(([k, m]) => (
        <Alert key={k}>{m}</Alert>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={busy || !dirty} data-testid="save-dna">
          {busy ? "Enregistrement…" : dirty ? "Enregistrer l'ADN" : "Enregistré ✓"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={busy || Object.keys(initial.overrides).length === 0}
          onClick={() => {
            setValues(initial.inherited);
            void save(initial.inherited);
          }}
        >
          Tout reprendre du genre
        </Button>
        {dirty && <span className="text-xs text-amber-300">Modifications non enregistrées</span>}
      </div>
    </form>
  );
}

function DnaRow({
  field,
  value,
  inherited,
  genre,
  error,
  disabled,
  onChange,
}: {
  field: DnaField;
  value: DnaValue | undefined;
  inherited: DnaValue | undefined;
  genre: string | null;
  error?: string;
  disabled: boolean;
  onChange: (v: DnaValue) => void;
}) {
  const id = `adn-${field.path.replaceAll(".", "-")}`;
  const adjusted = !same(value, inherited);
  const from = genre ? `genre ${genre}` : "défaut";
  return (
    <li>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-xs text-zinc-300" title={field.help || undefined}>
          {field.label}
        </label>
        <span className="flex shrink-0 items-center gap-1.5 text-xs">
          <span className="font-medium tabular-nums text-zinc-100" data-testid={`${id}-value`}>
            {formatDna(field, value)}
          </span>
          {adjusted ? (
            <button
              type="button"
              className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] text-rose-200 hover:bg-rose-500/25"
              onClick={() => inherited !== undefined && onChange(inherited)}
              disabled={disabled}
              title={`Reprendre la valeur du ${from} (${formatDna(field, inherited)})`}
              aria-label={`${field.label} : reprendre la valeur du ${from} (${formatDna(field, inherited)})`}
            >
              ajusté ({formatDna(field, inherited)}) ↺
            </button>
          ) : (
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">hérité</span>
          )}
        </span>
      </div>
      {field.kind === "bool" ? (
        <input
          id={id}
          type="checkbox"
          className="mt-1 h-4 w-4 accent-rose-500"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
      ) : (
        <input
          id={id}
          type="range"
          className="mt-1 w-full accent-rose-500"
          min={field.min ?? 0}
          max={field.max ?? 1}
          step={field.step ?? (field.kind === "share" ? 0.05 : 1)}
          value={Number(value ?? 0)}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-valuetext={formatDna(field, value)}
          onChange={(e) => {
            const n = Number(e.target.value);
            onChange(field.kind === "share" ? Math.round(n * 100) / 100 : Math.round(n));
          }}
        />
      )}
      {field.help && <p className="text-[11px] text-zinc-500">{field.help}</p>}
      {error && (
        <p className="text-xs text-red-400" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}
