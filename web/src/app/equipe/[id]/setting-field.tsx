"use client";

import { useRef } from "react";
import { Input, Select, Textarea } from "@/components/ui";
import type { AgentSetting } from "@/lib/api";
import { ORIGIN_LABEL, checkTemplate, displayValue, toFormValue } from "@/lib/agents";

const ORIGIN_TONE = {
  preset: "text-zinc-500 ring-zinc-700",
  global: "text-sky-300 ring-sky-500/40",
  series: "text-rose-300 ring-rose-500/40",
};

/** Un réglage : champ adapté à son type, origine de la valeur, retour à la valeur héritée. */
export function SettingField({
  setting,
  value,
  onChange,
  error,
  modified,
  locked,
}: {
  setting: AgentSetting;
  value: unknown;
  onChange: (value: unknown) => void;
  error?: string;
  /** La valeur du formulaire diffère de l'enregistrée. */
  modified: boolean;
  /** Réglage commun à toutes les séries, affiché en lecture seule dans une surcharge de série. */
  locked: boolean;
}) {
  const id = `setting-${setting.key}`;
  const inherited = toFormValue(setting, setting.inherited);
  const differsFromInherited = JSON.stringify(value) !== JSON.stringify(inherited);
  const isPrompt = setting.type === "prompt" || setting.type === "prompt_list";
  const localError = isPrompt && typeof value === "string" ? promptError(setting, value) : null;
  const raw = error ?? localError;
  const shown = raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : undefined;

  return (
    <div className={isPrompt || setting.type === "yaml" || setting.type === "longtext" ? "md:col-span-2" : ""}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium text-zinc-300">
          {setting.label}
        </label>
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${ORIGIN_TONE[setting.origin]}`}
          title={`Valeur livrée : ${setting.source}`}
        >
          {ORIGIN_LABEL[setting.origin]}
        </span>
        {modified && <span className="text-[10px] font-medium text-amber-300">modifié</span>}
        {differsFromInherited && !locked && (
          <button
            type="button"
            onClick={() => onChange(inherited)}
            className="ml-auto text-xs text-zinc-500 hover:text-zinc-200"
            title={`Valeur héritée : ${displayValue(setting.inherited, 300)}`}
          >
            ↺ valeur héritée
          </button>
        )}
      </div>
      <Control setting={setting} id={id} value={value} onChange={onChange} invalid={Boolean(shown)} disabled={locked} />
      {shown ? (
        <p className="mt-1 text-xs text-red-400" role="alert">
          {shown}
        </p>
      ) : (
        <p className="mt-1 text-xs text-zinc-500">
          {locked ? "Commun à toutes les séries : se règle dans le profil global. " : ""}
          {setting.help}
          {setting.help ? " " : ""}
          <span className="text-zinc-600">({setting.source})</span>
        </p>
      )}
    </div>
  );
}

function promptError(setting: AgentSetting, text: string): string | null {
  if (setting.type === "prompt") return checkTemplate(text, setting.variables);
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const problem = checkTemplate(lines[i], setting.variables);
    if (problem) return `Ligne ${i + 1} : ${problem.charAt(0).toLowerCase()}${problem.slice(1)}`;
  }
  return null;
}

function Control({
  setting,
  id,
  value,
  onChange,
  invalid,
  disabled,
}: {
  setting: AgentSetting;
  id: string;
  value: unknown;
  onChange: (value: unknown) => void;
  invalid: boolean;
  disabled: boolean;
}) {
  const common = { id, "aria-invalid": invalid || undefined, disabled };
  switch (setting.type) {
    case "boolean":
      return (
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            {...common}
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 accent-rose-500"
          />
          {value ? "Oui" : "Non"}
        </label>
      );
    case "choice":
      return (
        <Select {...common} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {setting.nullable && <option value="">Aucun</option>}
          {setting.choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </Select>
      );
    case "number":
    case "integer":
      return (
        <Input
          {...common}
          inputMode="decimal"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          placeholder={[setting.min, setting.max].some((v) => v !== null) ? `${setting.min ?? "…"} à ${setting.max ?? "…"}` : undefined}
        />
      );
    case "prompt":
    case "prompt_list":
      return <PromptEditor {...common} setting={setting} value={String(value ?? "")} onChange={onChange} />;
    case "yaml":
      return (
        <Textarea
          {...common}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="min-h-72 font-mono text-xs"
          spellCheck={false}
        />
      );
    case "longtext":
    case "list":
      return (
        <Textarea
          {...common}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={setting.type === "list" ? "min-h-28" : "min-h-20"}
          placeholder={setting.type === "list" ? "Un élément par ligne" : undefined}
        />
      );
    default:
      return <Input {...common} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  }
}

/** Grand éditeur de prompt : variables `$…` disponibles, insérées au curseur d'un clic. */
function PromptEditor({
  setting,
  value,
  onChange,
  ...props
}: {
  setting: AgentSetting;
  value: string;
  onChange: (value: unknown) => void;
  id: string;
  disabled: boolean;
  "aria-invalid"?: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  function insert(variable: string) {
    const el = ref.current;
    const token = `$${variable}`;
    if (!el) return onChange(value + token);
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    onChange(value.slice(0, start) + token + value.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  }

  return (
    <div className="space-y-2">
      <Textarea
        {...props}
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`font-mono text-xs leading-relaxed ${setting.type === "prompt_list" ? "min-h-36" : "min-h-64"}`}
        spellCheck={false}
      />
      {setting.variables.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Variables disponibles">
          <span className="text-zinc-500">Variables :</span>
          {setting.variables.map((v) => (
            <button
              key={v}
              type="button"
              disabled={props.disabled}
              onClick={() => insert(v)}
              className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-zinc-300 hover:bg-zinc-700 disabled:opacity-50"
              title="Insérer au curseur"
            >
              ${v}
            </button>
          ))}
          <span className="text-zinc-600">· « $$ » pour un dollar</span>
        </div>
      )}
    </div>
  );
}
