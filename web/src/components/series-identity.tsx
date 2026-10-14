"use client";

import { useEffect, useState } from "react";
import { useToast } from "./toast";
import { Alert, Button, Card, Input, Loading, Select } from "./ui";
import {
  api,
  engineUrl,
  fullErrorMessage,
  type LogoColorSlot,
  type LogoPreview,
  type LogoSpec,
  type Palette,
  type RenderedLogo,
  type SeriesIdentity,
} from "@/lib/api";
import { useEngineData } from "@/lib/hooks";

const SLOT_LABELS: Record<LogoColorSlot, string> = {
  fill: "Lettres",
  fill_end: "Fin du dégradé",
  outline: "Contour",
  outer: "Second contour",
  shadow: "Ombre",
  subtitle: "Sous-titre",
};

/** SVG du moteur affiché en image : chaque logo garde sa police embarquée, sans fuite de style dans la page. */
function svgSrc(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function LogoImage({ svg, alt, background }: { svg: string; alt: string; background: string }) {
  return (
    <div className="flex h-28 items-center justify-center rounded-md p-2" style={{ background }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={svgSrc(svg)} alt={alt} className="max-h-full max-w-full object-contain" />
    </div>
  );
}

/** Concept ou logo sur fond clair et sur fond sombre, côte à côte. */
function LogoPair({ svg, alt, backgrounds }: { svg: string; alt: string; backgrounds: Record<string, string> }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <LogoImage svg={svg} alt={`${alt} — fond clair`} background={backgrounds.light ?? "#f4f4f5"} />
      <LogoImage svg={svg} alt={`${alt} — fond sombre`} background={backgrounds.dark ?? "#18181b"} />
    </div>
  );
}

function Swatches({ palette, roles }: { palette: Palette; roles: Record<string, string> }) {
  return (
    <div className="flex overflow-hidden rounded-md border border-zinc-800">
      {palette.colors.map((c) => (
        <div key={c.role} className="h-10 flex-1" style={{ background: c.hex }} title={`${roles[c.role] ?? c.role} : ${c.hex}`} />
      ))}
    </div>
  );
}

/**
 * « Identité visuelle » de la série (fiche série) : palette de couleurs proposée par l'IA, logo du titre
 * typographique (concepts de l'IA, réglage à la main avec aperçu, versions, téléchargement SVG / PNG).
 * Palette et logo restent les mêmes d'un tome à l'autre.
 */
export function SeriesIdentityCard({ projectId }: { projectId: number }) {
  const identity = useEngineData(() => api.identity(projectId), [projectId]);
  const [busy, setBusy] = useState<"palettes" | "logos" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<LogoSpec | null>(null);
  const toast = useToast();
  const data = identity.data;

  async function run(kind: "palettes" | "logos", more: boolean) {
    setBusy(kind);
    setError(null);
    try {
      const out = kind === "palettes" ? await api.proposePalettes(projectId, more) : await api.proposeLogos(projectId, more);
      identity.setData(out);
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card data-testid="series-identity">
      <h2 className="mb-1 font-semibold text-zinc-100">Identité visuelle</h2>
      <p className="mb-4 text-sm text-zinc-400">
        Palette et logo du titre de la série : l&apos;IA propose, tu choisis et ajustes. Ils restent les mêmes d&apos;un tome à
        l&apos;autre (couvertures).
      </p>
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      {identity.loading && !data ? (
        <Loading />
      ) : identity.error || !data ? (
        <Alert>{identity.error ?? "Identité visuelle indisponible"}</Alert>
      ) : (
        <div className="space-y-8">
          <PaletteSection
            key={JSON.stringify(data.palette)}
            projectId={projectId}
            data={data}
            busy={busy === "palettes"}
            disabled={busy !== null}
            onPropose={(more) => run("palettes", more)}
            onSaved={(out) => {
              identity.setData(out);
              toast("Palette enregistrée");
            }}
            onError={setError}
          />
          <LogoSection
            data={data}
            busy={busy === "logos"}
            disabled={busy !== null}
            onPropose={(more) => run("logos", more)}
            onEdit={setEditing}
          />
          {editing && (
            <LogoEditor
              key={JSON.stringify(editing)}
              projectId={projectId}
              data={data}
              initial={editing}
              onCancel={() => setEditing(null)}
              onSaved={(out) => {
                identity.setData(out);
                setEditing(null);
                toast("Logo enregistré");
              }}
            />
          )}
        </div>
      )}
    </Card>
  );
}

// --- palette ------------------------------------------------------------------------------------
function PaletteSection({
  projectId,
  data,
  busy,
  disabled,
  onPropose,
  onSaved,
  onError,
}: {
  projectId: number;
  data: SeriesIdentity;
  busy: boolean;
  disabled: boolean;
  onPropose: (more: boolean) => void;
  onSaved: (out: SeriesIdentity) => void;
  onError: (message: string | null) => void;
}) {
  const [draft, setDraft] = useState<Palette | null>(data.palette);
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.palette);

  async function save(palette: Palette) {
    setSaving(true);
    onError(null);
    try {
      onSaved(await api.savePalette(projectId, palette));
    } catch (err) {
      onError(fullErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  function setColor(index: number, hex: string) {
    if (!draft) return;
    setDraft({ ...draft, colors: draft.colors.map((c, i) => (i === index ? { ...c, hex: hex.toLowerCase() } : c)) });
  }

  const hasProposals = data.palette_proposals.length > 0;
  return (
    <section aria-labelledby="identite-palette">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 id="identite-palette" className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          Palette
        </h3>
        <Button variant="secondary" onClick={() => onPropose(hasProposals)} disabled={disabled}>
          {busy ? "L'IA propose des palettes…" : hasProposals ? "Proposer d'autres palettes" : "Proposer des palettes"}
        </Button>
      </div>

      {draft ? (
        <div className="mb-4 rounded-lg border border-zinc-800 p-3" data-testid="palette-retenue">
          <p className="mb-2 text-sm text-zinc-200">
            Palette retenue : <span className="font-medium">{draft.name}</span>
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            {draft.colors.map((c, i) => (
              <label key={c.role} className="flex flex-col gap-1 text-xs text-zinc-400">
                <input
                  type="color"
                  value={c.hex}
                  onChange={(e) => setColor(i, e.target.value)}
                  aria-label={`Couleur ${data.roles[c.role] ?? c.role}`}
                  className="h-10 w-full cursor-pointer rounded border border-zinc-700 bg-transparent"
                />
                <span>{data.roles[c.role] ?? c.role}</span>
                <span className="font-mono text-zinc-500">{c.hex}</span>
              </label>
            ))}
          </div>
          {draft.explanation && <p className="mt-2 text-xs text-zinc-500">{draft.explanation}</p>}
          {dirty && (
            <div className="mt-3 flex gap-2">
              <Button onClick={() => save(draft)} disabled={saving}>
                {saving ? "Enregistrement…" : "Enregistrer la palette"}
              </Button>
              <Button variant="ghost" onClick={() => setDraft(data.palette)}>
                Annuler
              </Button>
            </div>
          )}
        </div>
      ) : (
        !hasProposals && !busy && <p className="mb-3 text-sm text-zinc-500">Aucune palette : demande des propositions à l&apos;IA.</p>
      )}

      {busy && <p className="mb-3 text-sm text-zinc-400" role="status">L&apos;IA lit la bible, le style et les personnages…</p>}
      {hasProposals && (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Palettes proposées">
          {data.palette_proposals.map((p) => {
            const chosen = data.palette?.name === p.name;
            return (
              <li key={p.name} className="space-y-2 rounded-lg border border-zinc-800 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-zinc-100">{p.name}</span>
                  {chosen && <span className="text-xs text-rose-300">retenue</span>}
                </div>
                <Swatches palette={p} roles={data.roles} />
                <p className="text-xs text-zinc-400">{p.explanation}</p>
                <Button variant="secondary" onClick={() => save(p)} disabled={saving} aria-label={`Retenir la palette ${p.name}`}>
                  Retenir
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// --- logo ---------------------------------------------------------------------------------------
function LogoSection({
  data,
  busy,
  disabled,
  onPropose,
  onEdit,
}: {
  data: SeriesIdentity;
  busy: boolean;
  disabled: boolean;
  onPropose: (more: boolean) => void;
  onEdit: (spec: LogoSpec) => void;
}) {
  const fontName = (id: string) => data.fonts.find((f) => f.id === id)?.name ?? id;
  const styleName = (id: string) => data.styles.find((s) => s.id === id)?.name ?? id;
  const hasProposals = data.logo_proposals.length > 0;
  const bg = data.limits.backgrounds;
  return (
    <section aria-labelledby="identite-logo">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 id="identite-logo" className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
          Logo du titre
        </h3>
        <Button variant="secondary" onClick={() => onPropose(hasProposals)} disabled={disabled || !data.palette}>
          {busy ? "L'IA propose des logos…" : hasProposals ? "Proposer d'autres logos" : "Proposer des logos"}
        </Button>
      </div>
      {!data.palette && <p className="mb-3 text-sm text-zinc-500">Retiens d&apos;abord une palette : les logos en tirent leurs couleurs.</p>}

      {data.logo ? (
        <div className="mb-4 space-y-2 rounded-lg border border-zinc-800 p-3" data-testid="logo-retenu">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-zinc-200">
              Logo de la série — version {data.logo.version} · {fontName(data.logo.spec.font)} · {styleName(data.logo.spec.style)}
            </p>
            <div className="flex flex-wrap gap-2">
              <a className="text-sm text-rose-300 hover:underline" href={engineUrl(data.logo.svg_url)} download>
                Télécharger le SVG
              </a>
              <a className="text-sm text-rose-300 hover:underline" href={engineUrl(data.logo.png_url)} download>
                Télécharger le PNG transparent
              </a>
              <Button variant="ghost" onClick={() => onEdit(data.logo!.spec)}>
                Ajuster
              </Button>
            </div>
          </div>
          <LogoPair svg={data.logo.svg} alt={`Logo version ${data.logo.version}`} backgrounds={bg} />
          {data.logo_versions.length > 1 && (
            <details className="text-sm text-zinc-400">
              <summary className="cursor-pointer">Versions précédentes ({data.logo_versions.length - 1})</summary>
              <ul className="mt-2 space-y-2">
                {data.logo_versions.slice(1).map((v) => (
                  <li key={v.id} className="flex items-center gap-3">
                    <div className="w-40">
                      <LogoImage svg={v.svg} alt={`Logo version ${v.version}`} background={bg.light ?? "#f4f4f5"} />
                    </div>
                    <span>Version {v.version}</span>
                    <a className="text-rose-300 hover:underline" href={engineUrl(v.svg_url)} download>
                      SVG
                    </a>
                    <a className="text-rose-300 hover:underline" href={engineUrl(v.png_url)} download>
                      PNG
                    </a>
                    <Button variant="ghost" onClick={() => onEdit(v.spec)}>
                      Reprendre
                    </Button>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      ) : (
        data.palette && !hasProposals && !busy && <p className="mb-3 text-sm text-zinc-500">Pas encore de logo : demande des concepts à l&apos;IA.</p>
      )}

      {busy && <p className="mb-3 text-sm text-zinc-400" role="status">L&apos;IA compose des concepts de logo…</p>}
      {hasProposals && (
        <ul className="grid gap-3 md:grid-cols-2" aria-label="Concepts de logo">
          {data.logo_proposals.map((c: RenderedLogo, i) => (
            <li key={i} className="space-y-2 rounded-lg border border-zinc-800 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-zinc-100">{c.spec.name || `Concept ${i + 1}`}</span>
                <span className="text-xs text-zinc-500">
                  {fontName(c.spec.font)} · {styleName(c.spec.style)}
                </span>
              </div>
              <LogoPair svg={c.svg} alt={c.spec.name || `Concept ${i + 1}`} backgrounds={bg} />
              {c.spec.explanation && <p className="text-xs text-zinc-400">{c.spec.explanation}</p>}
              {c.notes.map((n) => (
                <p key={n} className="text-xs text-amber-300">
                  {n}
                </p>
              ))}
              <Button variant="secondary" onClick={() => onEdit(c.spec)} aria-label={`Choisir le concept ${c.spec.name || i + 1}`}>
                Choisir et ajuster
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = (v) => String(v),
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-400">
      <span>
        {label} : <span className="text-zinc-200">{format(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

/** Réglage d'un logo avec aperçu en direct (rendu par le moteur), puis « Enregistrer comme logo de la série ». */
function LogoEditor({
  projectId,
  data,
  initial,
  onCancel,
  onSaved,
}: {
  projectId: number;
  data: SeriesIdentity;
  initial: LogoSpec;
  onCancel: () => void;
  onSaved: (out: SeriesIdentity) => void;
}) {
  const [spec, setSpec] = useState<LogoSpec>(initial);
  const [preview, setPreview] = useState<LogoPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const limits = data.limits;
  const style = data.styles.find((s) => s.id === spec.style);
  const slots = (style?.slots ?? ["fill"]).filter((s) => s !== "subtitle" || spec.subtitle);
  const palette = data.palette?.colors ?? [];

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .previewLogo(projectId, spec)
        .then((p) => {
          if (cancelled) return;
          setPreview(p);
          setPreviewError(null);
        })
        .catch((err) => {
          if (!cancelled) setPreviewError(fullErrorMessage(err));
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [projectId, spec]);

  function update(patch: Partial<LogoSpec>) {
    setSpec((s) => ({ ...s, ...patch }));
  }

  function setColor(slot: LogoColorSlot, hex: string) {
    setSpec((s) => ({ ...s, colors: { ...s.colors, [slot]: hex.toLowerCase() } }));
  }

  function setLine(index: number, patch: Partial<{ text: string; scale: number }>) {
    setSpec((s) => ({ ...s, lines: s.lines.map((l, i) => (i === index ? { ...l, ...patch } : l)) }));
  }

  function setLayout(count: number) {
    const words = spec.lines.map((l) => l.text).join(" ").split(/\s+/).filter(Boolean);
    if (count === 1 || words.length < 2) {
      update({ lines: [{ text: words.join(" "), scale: 1 }] });
    } else {
      const cut = Math.ceil(words.length / 2);
      update({
        lines: [
          { text: words.slice(0, cut).join(" "), scale: 0.6 },
          { text: words.slice(cut).join(" "), scale: 1 },
        ],
      });
    }
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.saveLogo(projectId, spec));
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="identite-reglage" className="rounded-lg border border-rose-500/30 p-4" data-testid="logo-editor">
      <h3 id="identite-reglage" className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-300">
        Ajuster le logo {spec.name ? `« ${spec.name} »` : ""}
      </h3>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-2">
          {preview ? (
            <LogoPair svg={preview.svg} alt="Aperçu du logo" backgrounds={limits.backgrounds} />
          ) : (
            <Loading />
          )}
          {previewError && <Alert>{previewError}</Alert>}
          {preview && preview.contrast !== null && (
            <p className={`text-xs ${preview.contrast_ok ? "text-zinc-500" : "text-amber-300"}`} role="status">
              Contraste texte / contour : {preview.contrast.toFixed(1)}
              {preview.contrast_ok ? "" : ` — trop faible (minimum ${limits.min_contrast}) : éclaircis ou fonce le contour`}
            </p>
          )}
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-xs text-zinc-400">
              Police
              <Select value={spec.font} onChange={(e) => update({ font: e.target.value })}>
                {data.fonts.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-zinc-400">
              Effet
              <Select value={spec.style} onChange={(e) => update({ style: e.target.value })}>
                {data.styles.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </label>
          </div>
          {limits.max_lines > 1 && (
            <div className="flex gap-2 text-xs">
              <Button variant={spec.lines.length === 1 ? "primary" : "secondary"} onClick={() => setLayout(1)}>
                Une ligne
              </Button>
              <Button variant={spec.lines.length === 2 ? "primary" : "secondary"} onClick={() => setLayout(2)}>
                Deux lignes
              </Button>
            </div>
          )}
          {spec.lines.map((line, i) => (
            <div key={i} className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] items-end gap-2">
              <label className="flex flex-col gap-1 text-xs text-zinc-400">
                Ligne {i + 1}
                <Input value={line.text} onChange={(e) => setLine(i, { text: e.target.value })} />
              </label>
              <Slider
                label="Taille"
                value={line.scale}
                min={limits.word_scale.min}
                max={limits.word_scale.max}
                step={0.05}
                onChange={(v) => setLine(i, { scale: v })}
                format={(v) => `${Math.round(v * 100)} %`}
              />
            </div>
          ))}
          <label className="flex flex-col gap-1 text-xs text-zinc-400">
            Sous-titre (facultatif)
            <Input value={spec.subtitle ?? ""} onChange={(e) => update({ subtitle: e.target.value || null })} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <Slider
              label="Interlettrage"
              value={spec.letter_spacing}
              min={limits.letter_spacing.min}
              max={limits.letter_spacing.max}
              step={0.01}
              onChange={(v) => update({ letter_spacing: v })}
              format={(v) => `${v.toFixed(2)} em`}
            />
            <Slider
              label="Inclinaison"
              value={spec.slant}
              min={-limits.slant_max_deg}
              max={limits.slant_max_deg}
              step={1}
              onChange={(v) => update({ slant: v })}
              format={(v) => `${v}°`}
            />
            <Slider
              label="Épaisseur des contours"
              value={spec.outline_scale}
              min={limits.outline_scale.min}
              max={limits.outline_scale.max}
              step={0.1}
              onChange={(v) => update({ outline_scale: v })}
              format={(v) => `× ${v.toFixed(1)}`}
            />
          </div>
          <div className="space-y-2">
            {slots.map((slot) => (
              <div key={slot} className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
                <span className="w-28">{SLOT_LABELS[slot]}</span>
                <input
                  type="color"
                  value={spec.colors[slot] ?? "#000000"}
                  onChange={(e) => setColor(slot, e.target.value)}
                  aria-label={`Couleur : ${SLOT_LABELS[slot]}`}
                  className="h-7 w-10 cursor-pointer rounded border border-zinc-700 bg-transparent"
                />
                {palette.map((c) => (
                  <button
                    key={c.role}
                    type="button"
                    onClick={() => setColor(slot, c.hex)}
                    title={`${data.roles[c.role] ?? c.role} (${c.hex})`}
                    aria-label={`${SLOT_LABELS[slot]} : ${data.roles[c.role] ?? c.role}`}
                    className={`h-6 w-6 rounded-full border ${spec.colors[slot] === c.hex ? "border-rose-400 ring-2 ring-rose-400" : "border-zinc-700"}`}
                    style={{ background: c.hex }}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
      {error && (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-4 flex gap-2">
        <Button onClick={save} disabled={saving || Boolean(previewError)}>
          {saving ? "Enregistrement…" : "Enregistrer comme logo de la série"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Fermer
        </Button>
      </div>
    </section>
  );
}
