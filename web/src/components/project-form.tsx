"use client";

import { useRef, useState, type FormEvent } from "react";
import {
  api,
  EngineError,
  errorMessage,
  type CleanMode,
  type Presets,
  type Project,
  type ProjectInput,
  type StyleGenre,
} from "@/lib/api";
import { HELP, type HelpId } from "@/lib/help";
import { useEngineData } from "@/lib/hooks";
import { InfoTip } from "./info-tip";
import { Modal } from "./modal";
import { LoraPicker } from "./lora-picker";
import { DIRECTIONS, DirectionPicker } from "./reading-direction";
import { SERIES_STATUS } from "./status";
import { useToast } from "./toast";
import { Alert, Button, Field, Input, Select } from "./ui";

const DIRECTION_REQUIRED = "Choisis le sens de lecture : manga (droite → gauche) ou BD (gauche → droite).";
const STYLE_REQUIRED: Record<"style_genre" | "style_rendering" | "style_tone", string> = {
  style_genre: "Choisis le genre de la série dans la liste.",
  style_rendering: "Choisis le rendu dans la liste.",
  style_tone: "Choisis le ton dans la liste.",
};

/** Bulle d'aide d'un réglage fin (`serie.option.<id>` dans lib/help.ts), s'il y en a une. */
function optionHelp(id: string): HelpId | undefined {
  const key = `serie.option.${id}`;
  return key in HELP ? (key as HelpId) : undefined;
}

function toneAllowed(genre: StyleGenre | undefined, tone: string): boolean {
  return !genre?.allowed_tones || genre.allowed_tones.includes(tone);
}

/** Rappelle quel workflow du même palier sert aux cases avec images de référence. */
function WorkflowHint({ presets, workflow }: { presets?: Presets["workflows"]; workflow: string }) {
  const current = presets?.find((w) => w.id === workflow);
  if (!current?.with_references) return null;
  const refs = presets?.find((w) => w.id === current.with_references);
  return (
    <p className="mt-1 text-xs text-zinc-500">
      Cases avec images de référence : {refs?.name ?? `${current.with_references} (preset introuvable)`}
    </p>
  );
}

export function ProjectForm({
  initial,
  submitLabel,
  onSaved,
}: {
  initial?: Project;
  submitLabel: string;
  onSaved: (project: Project) => void;
}) {
  const presets = useEngineData(() => api.presets());
  // Passage au propre par ControlNet : proposé seulement si ComfyUI a le patch et son nœud.
  const control = useEngineData(() => api.controlStatus());
  const [form, setForm] = useState<Partial<ProjectInput>>({
    title: initial?.title ?? "",
    // Genre : choix explicite. Rendu et ton : ceux de la série, sinon ceux par défaut des presets.
    style_genre: initial?.style_genre ?? undefined,
    style_rendering: initial?.style_rendering ?? undefined,
    style_tone: initial?.style_tone ?? undefined,
    style_options: initial?.style_options ?? {},
    status: initial?.status ?? "ongoing",
    // À la création rien n'est présélectionné : le sens de lecture est un choix explicite.
    reading_direction: initial?.reading_direction,
    page_format: initial?.page_format,
    workflow_preset: initial?.workflow_preset,
    style_lora_name: initial?.style_lora_name ?? "",
    style_lora_weight: initial?.style_lora_weight ?? 0.8,
    dialogue_font: initial?.dialogue_font ?? undefined,
    shout_font: initial?.shout_font ?? undefined,
    layout_style: initial?.layout_style,
    sketch_enabled: initial?.sketch_enabled,
    sketch_denoise: initial?.sketch_denoise ?? null,
    clean_mode: initial?.clean_mode ?? "img2img",
    clean_control: initial?.clean_control ?? null,
    upscaler: initial?.upscaler ?? null,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const toast = useToast();

  const defaults = presets.data?.defaults;
  const pageFormat = form.page_format ?? defaults?.page_format ?? "";
  const workflow = form.workflow_preset ?? defaults?.workflow ?? "";
  const styles = presets.data?.layout_styles ?? [];
  const layoutStyle =
    form.layout_style ?? defaults?.layout_style ?? styles.find((s) => s.is_default)?.id ?? "";
  const styleInfo = styles.find((s) => s.id === layoutStyle);
  // Paliers proposés (Turbo, Rapide, Qualité) : workflows qui déclarent un libellé de palier.
  const tiers = (presets.data?.workflows ?? [])
    .filter((w) => w.tier_choice)
    .sort((a, b) => (a.tier_order ?? 0) - (b.tier_order ?? 0));
  const currentWorkflow = presets.data?.workflows.find((w) => w.id === workflow);
  // Palier des nouvelles séries (Rapide) : proposé en un clic à une série restée sur un palier inférieur.
  const recommendedTier = tiers.find((w) => w.id === defaults?.workflow);
  const suggestRecommended =
    recommendedTier !== undefined &&
    currentWorkflow?.tier_order != null &&
    currentWorkflow.tier_order < (recommendedTier.tier_order ?? 0);
  const sketchEnabled = form.sketch_enabled ?? defaults?.sketch_enabled ?? true;
  // Débruitage livré : celui du preset « propre depuis croquis » du palier choisi.
  const cleanPreset = presets.data?.workflows.find((w) => w.id === currentWorkflow?.from_sketch);
  const presetDenoise = cleanPreset?.denoise ?? null;
  const cleanMode: CleanMode = form.clean_mode ?? "img2img";
  const controlAvailable = control.data?.available ?? false;
  const controlTypes = (control.data?.types ?? []).filter((t) => t.available || t.id === form.clean_control);
  const controlDefault = control.data?.types.find((t) => t.id === control.data?.default_type);
  const upscalers = presets.data?.upscalers ?? [];
  const defaultUpscaler = upscalers.find((u) => u.is_default);
  const upscalerInfo = upscalers.find((u) => u.id === form.upscaler) ?? defaultUpscaler;
  // Packs de style : listes fermées des presets.
  const genres = presets.data?.style_genres ?? [];
  const renderings = presets.data?.style_renderings ?? [];
  const tones = presets.data?.style_tones ?? [];
  const styleOptions = presets.data?.style_options ?? [];
  const genre = genres.find((g) => g.id === form.style_genre);
  const renderingId = form.style_rendering ?? renderings.find((r) => r.is_default)?.id ?? "";
  const rendering = renderings.find((r) => r.id === renderingId);
  const toneId = form.style_tone ?? tones.find((t) => t.is_default)?.id ?? "";
  const tone = tones.find((t) => t.id === toneId);
  const toneRefused = Boolean(genre && toneId && !toneAllowed(genre, toneId));
  // Trames & co : réservés aux rendus noir et blanc, masqués en couleur.
  const visibleOptions = styleOptions.filter((o) => !o.monochrome_only || rendering?.monochrome !== false);
  const fonts = presets.data?.fonts ?? [];
  const dialogueFont = form.dialogue_font ?? genre?.fonts.dialogue ?? "";
  const shoutFont = form.shout_font ?? genre?.fonts.shout ?? "";
  const loraName = form.style_lora_name?.trim() ?? "";
  const catalogLora = presets.data?.style_loras.find((l) => l.file === loraName);
  const suggestedLora = presets.data?.style_loras.find((l) => l.file === genre?.style_lora);

  const set = <K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: "" }));
  };

  /** Le genre pré-remplit le sens de lecture et les polices (modifiables ensuite) ; il peut suggérer une
   * mise en page (jamais « sage ») — sans suggestion : celle des nouvelles séries, ou celle déjà choisie. */
  function chooseGenre(id: string) {
    const g = genres.find((x) => x.id === id);
    setForm((f) => ({
      ...f,
      style_genre: id || undefined,
      ...(g && {
        layout_style: g.layout_style ?? (initial ? f.layout_style : undefined),
        reading_direction: g.reading_direction,
        dialogue_font: g.fonts.dialogue,
        shout_font: g.fonts.shout,
      }),
    }));
    setErrors((e) => ({ ...e, style_genre: "", style_tone: "", reading_direction: "", layout_style: "" }));
  }

  function chooseLora(name: string) {
    const entry = presets.data?.style_loras.find((l) => l.file === name.trim());
    setForm((f) => ({ ...f, style_lora_name: name, ...(entry && { style_lora_weight: entry.weight }) }));
    setErrors((e) => ({ ...e, style_lora_name: "" }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const missing = (["style_genre", "style_rendering", "style_tone"] as const).filter(
      (k) => !(k === "style_genre" ? form.style_genre : k === "style_rendering" ? renderingId : toneId),
    );
    if (missing.length) {
      setErrors(Object.fromEntries(missing.map((k) => [k, STYLE_REQUIRED[k]])));
      setFormError(null);
      formRef.current?.querySelector<HTMLSelectElement>(`#${missing[0]}`)?.focus();
      return;
    }
    if (toneRefused) {
      // Message affiché sous la liste des tons ; l'API refuserait aussi (422).
      setFormError("Ce ton n'est pas proposé pour ce genre : choisis-en un autre.");
      formRef.current?.querySelector<HTMLSelectElement>("#style_tone")?.focus();
      return;
    }
    if (!form.reading_direction) {
      setErrors({ reading_direction: DIRECTION_REQUIRED });
      setFormError(null);
      formRef.current?.querySelector<HTMLInputElement>('input[name="reading_direction"]')?.focus();
      return;
    }
    const relayout = initial && form.reading_direction !== initial.reading_direction && initial.laid_out_page_count > 0;
    if (relayout) setConfirming(true);
    else void save();
  }

  async function save() {
    setConfirming(false);
    setSaving(true);
    setFormError(null);
    setErrors({});
    // Réglages fins masqués (trames d'un rendu couleur) : retirés, l'API les refuserait.
    const options = Object.fromEntries(
      Object.entries(form.style_options ?? {}).filter(([k, v]) => v && visibleOptions.some((o) => o.id === k)),
    );
    const body = {
      ...form,
      style_rendering: renderingId,
      style_tone: toneId,
      style_options: options,
      dialogue_font: dialogueFont || undefined,
      shout_font: shoutFont || undefined,
      page_format: pageFormat || undefined,
      workflow_preset: workflow || undefined,
      layout_style: layoutStyle || undefined,
      sketch_enabled: sketchEnabled,
      sketch_denoise: form.sketch_denoise ?? null,
      style_lora_name: loraName || null,
    };
    try {
      const saved = initial ? await api.updateProject(initial.id, body) : await api.createProject(body);
      toast(initial ? "Série enregistrée" : "Série créée");
      onSaved(saved);
    } catch (err) {
      if (err instanceof EngineError && Object.keys(err.fieldErrors).length) setErrors(err.fieldErrors);
      setFormError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className="space-y-5" noValidate>
      {formError && <Alert>{formError}</Alert>}
      <Field label="Titre" htmlFor="title" error={errors.title}>
        <Input
          id="title"
          value={form.title ?? ""}
          onChange={(e) => set("title", e.target.value)}
          placeholder="Les Lames de Kyoto"
          aria-invalid={Boolean(errors.title)}
          required
          maxLength={200}
        />
      </Field>
      {initial && !initial.style_genre && (
        <div
          role="status"
          className="rounded-md border border-amber-800/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200"
          data-testid="legacy-style-banner"
        >
          <p className="font-medium">Style à choisir dans les listes</p>
          <p className="mt-1 text-amber-200/80">
            Le style se choisit désormais par genre, rendu et ton. En attendant, l&apos;ancien texte reste utilisé
            dans les prompts.
          </p>
          {initial.legacy_style && (
            <p className="mt-2 text-xs text-amber-100/70">
              Ancien style (lecture seule) : « {initial.legacy_style} »
            </p>
          )}
        </div>
      )}
      <fieldset className="min-w-0 space-y-4 rounded-lg border border-zinc-800 p-4" data-testid="style-packs">
        <legend className="px-1 text-sm font-medium text-zinc-200">Style de la série</legend>
        <div className="grid gap-5 md:grid-cols-3">
          <Field
            label="Genre"
            htmlFor="style_genre"
            help="serie.genre"
            error={errors.style_genre}
            hint={genre?.description ?? "Pré-remplit la mise en page, le sens de lecture et les polices."}
          >
            <Select
              id="style_genre"
              value={form.style_genre ?? ""}
              onChange={(e) => chooseGenre(e.target.value)}
              aria-invalid={Boolean(errors.style_genre)}
              disabled={!presets.data}
              required
            >
              <option value="">Choisir un genre…</option>
              {genres.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
              {form.style_genre && presets.data && !genre && (
                <option value={form.style_genre}>{form.style_genre} (preset introuvable)</option>
              )}
            </Select>
          </Field>
          <Field label="Rendu" htmlFor="style_rendering" help="serie.rendering" error={errors.style_rendering} hint={rendering?.description}>
            <Select
              id="style_rendering"
              value={renderingId}
              onChange={(e) => set("style_rendering", e.target.value)}
              aria-invalid={Boolean(errors.style_rendering)}
              disabled={!presets.data}
              required
            >
              {!renderingId && <option value="">Choisir un rendu…</option>}
              {renderings.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
              {renderingId && presets.data && !rendering && (
                <option value={renderingId}>{renderingId} (preset introuvable)</option>
              )}
            </Select>
          </Field>
          <Field
            label="Ton"
            htmlFor="style_tone"
            help="serie.tone"
            error={
              errors.style_tone ||
              (toneRefused && genre && tone ? `Le ton « ${tone.name} » n'est pas proposé pour le genre « ${genre.name} ».` : undefined)
            }
            hint={tone?.description}
          >
            <Select
              id="style_tone"
              value={toneId}
              onChange={(e) => set("style_tone", e.target.value)}
              aria-invalid={Boolean(errors.style_tone) || toneRefused}
              disabled={!presets.data}
              required
            >
              {!toneId && <option value="">Choisir un ton…</option>}
              {tones.map((t) => {
                const allowed = toneAllowed(genre, t.id);
                return (
                  <option key={t.id} value={t.id} disabled={!allowed}>
                    {t.name}
                    {allowed ? "" : " (non proposé pour ce genre)"}
                  </option>
                );
              })}
              {toneId && presets.data && !tone && <option value={toneId}>{toneId} (preset introuvable)</option>}
            </Select>
          </Field>
        </div>
        {visibleOptions.length > 0 && (
          <div className="grid gap-5 md:grid-cols-3" data-testid="style-options">
            {visibleOptions.map((o) => (
              <Field
                key={o.id}
                label={o.name}
                htmlFor={`style_option_${o.id}`}
                help={optionHelp(o.id)}
                hint={o.description}
                error={errors.style_options && o.id === visibleOptions[0].id ? errors.style_options : undefined}
              >
                <Select
                  id={`style_option_${o.id}`}
                  value={form.style_options?.[o.id] ?? ""}
                  onChange={(e) => {
                    const next = { ...(form.style_options ?? {}) };
                    if (e.target.value) next[o.id] = e.target.value;
                    else delete next[o.id];
                    set("style_options", next);
                  }}
                  disabled={!presets.data}
                >
                  <option value="">Par défaut</option>
                  {o.choices.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
            ))}
          </div>
        )}
        <LoraPicker
          id="style_lora_name"
          label="LoRA de style (optionnel)"
          help="serie.lora"
          weightHelp="serie.lora_weight"
          hint="Appliqué à toutes les cases de la série."
          placeholder="encre-seinen-v2.safetensors"
          value={form.style_lora_name ?? ""}
          onChange={chooseLora}
          savedValue={initial?.style_lora_name}
          error={errors.style_lora_name}
          weight={String(form.style_lora_weight ?? 0.8)}
          onWeightChange={(v) => set("style_lora_weight", Number(v))}
          weightLabel="Poids du LoRA de style"
          weightError={errors.style_lora_weight}
        />
        {loraName ? (
          catalogLora ? (
            <p className="text-xs text-zinc-500" data-testid="style-lora-catalog">
              Mots déclencheurs (catalogue) : {catalogLora.trigger_words.join(", ") || "aucun"} · poids conseillé{" "}
              {String(catalogLora.weight).replace(".", ",")}
            </p>
          ) : (
            <p className="text-xs text-amber-300" data-testid="style-lora-catalog">
              LoRA hors catalogue (presets/style_loras.yaml) : appliqué sans mots déclencheurs.
            </p>
          )
        ) : (
          suggestedLora && (
            <p className="flex items-center gap-2 text-xs text-zinc-400">
              LoRA conseillé pour ce genre : {suggestedLora.name || suggestedLora.file}
              <button
                type="button"
                className="rounded border border-zinc-700 px-2 py-0.5 text-zinc-300 hover:bg-zinc-800"
                onClick={() => chooseLora(suggestedLora.file)}
              >
                Utiliser
              </button>
            </p>
          )
        )}
        {initial?.style_genre && (
          <p className="text-xs break-words text-zinc-500" data-testid="style-prompt">
            Style envoyé au dessinateur (enregistré) : {initial.style_prompt}
          </p>
        )}
        {initial?.style_genre && initial.legacy_style && (
          <p className="text-xs text-zinc-600">Ancien style libre (lecture seule, plus utilisé) : « {initial.legacy_style} »</p>
        )}
      </fieldset>
      <DirectionPicker
        value={form.reading_direction}
        onChange={(v) => set("reading_direction", v)}
        error={errors.reading_direction}
      />
      <Field
        label="Style de mise en page"
        htmlFor="layout_style"
        help="serie.layout_style"
        error={errors.layout_style}
        hint={
          (styleInfo?.description || "Découpes, biais et gouttières de toutes les pages de la série.") +
          (initial && layoutStyle !== initial.layout_style && initial.relayout_page_count > 0
            ? " Après l'enregistrement, tu pourras remettre en page les pages pas encore générées."
            : "")
        }
      >
        <Select
          id="layout_style"
          value={layoutStyle}
          onChange={(e) => set("layout_style", e.target.value)}
          aria-invalid={Boolean(errors.layout_style)}
          disabled={!presets.data}
        >
          {styles.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
          {layoutStyle && presets.data && !styles.some((s) => s.id === layoutStyle) && (
            <option value={layoutStyle}>{layoutStyle} (preset introuvable)</option>
          )}
        </Select>
      </Field>
      <div className="grid gap-5 md:grid-cols-2">
        {(
          [
            ["dialogue_font", "Police des dialogues", dialogueFont],
            ["shout_font", "Police des cris", shoutFont],
          ] as const
        ).map(([key, label, value]) => (
          <Field key={key} label={label} htmlFor={key} help="serie.fonts" error={errors[key]} hint="Pré-remplie par le genre.">
            <Select
              id={key}
              value={value}
              onChange={(e) => set(key, e.target.value)}
              aria-invalid={Boolean(errors[key])}
              disabled={!presets.data}
            >
              {!value && <option value="">Police du lettreur</option>}
              {fonts.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
              {value && presets.data && !fonts.some((f) => f.id === value) && (
                <option value={value}>{value} (police introuvable)</option>
              )}
            </Select>
          </Field>
        ))}
      </div>
      <div className="grid gap-5 md:grid-cols-3">
        <Field label="Statut de la série" htmlFor="status" error={errors.status}>
          <Select
            id="status"
            value={form.status}
            onChange={(e) => set("status", e.target.value as ProjectInput["status"])}
          >
            {Object.entries(SERIES_STATUS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        <Field label="Format de page" htmlFor="page_format" help="serie.page_format" error={errors.page_format}>
          <Select
            id="page_format"
            value={pageFormat}
            onChange={(e) => set("page_format", e.target.value)}
            aria-invalid={Boolean(errors.page_format)}
            disabled={!presets.data}
          >
            {presets.data?.page_formats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.width_px}×{f.height_px} px)
              </option>
            ))}
            {pageFormat && !presets.data?.page_formats.some((f) => f.id === pageFormat) && (
              <option value={pageFormat}>{pageFormat} (preset introuvable)</option>
            )}
          </Select>
        </Field>
        <Field
          label="Palier de génération"
          htmlFor="workflow_preset"
          help="serie.tier"
          error={errors.workflow_preset}
          hint="Chaque case peut ensuite être régénérée en Qualité depuis l'atelier."
        >
          <Select
            id="workflow_preset"
            value={workflow}
            onChange={(e) => set("workflow_preset", e.target.value)}
            aria-invalid={Boolean(errors.workflow_preset)}
            disabled={!presets.data}
          >
            {tiers.map((w) => (
              <option key={w.id} value={w.id}>
                {w.tier_choice}
              </option>
            ))}
            {/* Série réglée sur un workflow qui n'est pas un palier (ou disparu) : on le garde visible. */}
            {workflow && presets.data && !tiers.some((w) => w.id === workflow) && (
              <option value={workflow}>{currentWorkflow?.name ?? `${workflow} (preset introuvable)`}</option>
            )}
          </Select>
          <WorkflowHint presets={presets.data?.workflows} workflow={workflow} />
          {suggestRecommended && (
            <div
              className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-zinc-800 bg-zinc-900/60 px-3 py-2"
              data-testid="tier-suggestion"
            >
              <Button type="button" variant="secondary" onClick={() => set("workflow_preset", recommendedTier.id)}>
                Passer en {recommendedTier.tier ?? recommendedTier.name}
              </Button>
              <p className="text-xs text-zinc-400">recommandé pour la qualité, ~1 min par case (puis Enregistrer)</p>
            </div>
          )}
        </Field>
      </div>
      <fieldset className="min-w-0 space-y-3 rounded-lg border border-zinc-800 p-4" data-testid="sketch-settings">
        <legend className="flex items-center gap-1.5 px-1 text-sm font-medium text-zinc-200">
          Palier croquis
          <InfoTip help="serie.sketch" label="Palier croquis" />
        </legend>
        <label className="flex items-start gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            className="mt-0.5 accent-rose-500"
            checked={sketchEnabled}
            onChange={(e) => set("sketch_enabled", e.target.checked)}
            data-testid="sketch-enabled"
          />
          <span>
            Croquer les pages avant de les produire
            <span className="block text-xs text-zinc-500">
              Brouillon de chaque case en quelques secondes, tri au clavier, puis « Passer au propre » des seules
              compositions validées.
            </span>
          </span>
        </label>
        <Field
          label="Débruitage du passage au propre"
          htmlFor="sketch_denoise"
          help="serie.sketch_denoise"
          error={errors.sketch_denoise}
          hint={`Part du croquis redessinée : plus bas = composition plus fidèle, plus haut = plus de détails neufs. Vide : valeur du preset${
            presetDenoise !== null ? ` (${String(presetDenoise).replace(".", ",")})` : ""
          }. Chaque case peut avoir la sienne (atelier).`}
        >
          <Input
            id="sketch_denoise"
            type="number"
            min={0.05}
            max={1}
            step={0.05}
            className="!w-32"
            value={form.sketch_denoise ?? ""}
            placeholder={presetDenoise !== null ? String(presetDenoise) : ""}
            disabled={!sketchEnabled || cleanMode === "controlnet"}
            onChange={(e) => set("sketch_denoise", e.target.value === "" ? null : Number(e.target.value))}
            aria-invalid={Boolean(errors.sketch_denoise)}
          />
        </Field>
        <Field
          label="Passage au propre"
          htmlFor="clean_mode"
          help="serie.clean_mode"
          error={errors.clean_mode}
          hint={
            cleanMode === "controlnet"
              ? "Le croquis validé guide la version propre (ControlNet) : cadrage et poses imposés, même graine et même prompt."
              : "Le croquis validé est redessiné en partie (débruitage ci-dessus), même graine et même prompt."
          }
        >
          <Select
            id="clean_mode"
            value={cleanMode}
            disabled={!sketchEnabled}
            onChange={(e) => set("clean_mode", e.target.value as CleanMode)}
            className="!w-auto max-w-full"
          >
            <option value="img2img">Image → image depuis le croquis (débruitage)</option>
            {(controlAvailable || cleanMode === "controlnet") && (
              <option value="controlnet">ControlNet : composition verrouillée sur le croquis</option>
            )}
          </Select>
        </Field>
        {control.data && !controlAvailable && (
          <p className="text-xs text-amber-300" data-testid="clean-controlnet-unavailable">
            {control.data.message ?? "Verrouillage de composition indisponible."} Passage au propre par ControlNet masqué.
          </p>
        )}
        {cleanMode === "controlnet" && controlTypes.length > 0 && (
          <Field label="Type de contrôle du passage au propre" htmlFor="clean_control" help="serie.clean_control" error={errors.clean_control}>
            <Select
              id="clean_control"
              value={form.clean_control ?? ""}
              disabled={!sketchEnabled}
              onChange={(e) => set("clean_control", e.target.value || null)}
              className="!w-auto max-w-full"
            >
              <option value="">Par défaut{controlDefault ? ` (${controlDefault.name})` : ""}</option>
              {controlTypes.map((t) => (
                <option key={t.id} value={t.id} title={t.description}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </fieldset>
      <Field
        label="Agrandisseur (finition d'impression)"
        htmlFor="upscaler"
        help="serie.upscaler"
        error={errors.upscaler}
        hint={
          upscalerInfo?.description ||
          "Agrandit la version retenue de chaque case jusqu'au dpi du format avant l'assemblage (« Finaliser la page »)."
        }
      >
        <Select
          id="upscaler"
          value={form.upscaler ?? ""}
          onChange={(e) => set("upscaler", e.target.value || null)}
          aria-invalid={Boolean(errors.upscaler)}
          disabled={!presets.data}
        >
          <option value="">Par défaut{defaultUpscaler ? ` — ${defaultUpscaler.name}` : ""}</option>
          {upscalers.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
              {u.high_fidelity ? " (lent)" : ""}
            </option>
          ))}
          {form.upscaler && presets.data && !upscalers.some((u) => u.id === form.upscaler) && (
            <option value={form.upscaler}>{form.upscaler} (preset introuvable)</option>
          )}
        </Select>
      </Field>
      <div className="flex justify-end">
        <Button type="submit" disabled={saving}>
          {saving ? "Enregistrement…" : submitLabel}
        </Button>
      </div>
      {initial && form.reading_direction && (
        <Modal
          open={confirming}
          onClose={() => setConfirming(false)}
          title="Changer le sens de lecture ?"
          footer={
            <>
              <Button type="button" variant="secondary" onClick={() => setConfirming(false)}>
                Annuler
              </Button>
              <Button type="button" onClick={() => void save()}>
                Changer et recalculer
              </Button>
            </>
          }
        >
          <div className="space-y-3 text-sm text-zinc-300">
            <p>
              La série passe en <strong className="text-zinc-100">{DIRECTIONS[form.reading_direction]}</strong>.
            </p>
            <p>
              {initial.laid_out_page_count === 1
                ? "La page déjà mise en page va être mise en miroir et recalculée"
                : `Les ${initial.laid_out_page_count} pages déjà mises en page vont être mises en miroir et recalculées`}{" "}
              : ordre de lecture des cases, gouttières et bulles placées à la main passent de l&apos;autre côté.
            </p>
            <p>
              Les images de cases déjà générées sont conservées telles quelles (elles ne sont pas retournées) : regénère
              celles dont la composition ne colle plus au nouveau sens.
            </p>
          </div>
        </Modal>
      )}
    </form>
  );
}
