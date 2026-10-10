"use client";

import { useEffect, useRef, useState } from "react";
import { InfoTip } from "@/components/info-tip";
import { modalOpen } from "@/components/modal";
import { api, fullErrorMessage, type Annotation, type AnnotationLabel, type DefectId, type PanelImage } from "@/lib/api";
import { ANNOTATION_LABEL, DEFECTS } from "@/lib/qc";

/** Vrai si la touche vient d'un champ de saisie (on ne détourne pas la frappe). */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** Petit badge « bonne » / « mauvaise » d'une version annotée. */
export function AnnotationBadge({ annotation }: { annotation: Annotation | null }) {
  if (!annotation) return null;
  const good = annotation.label === "good";
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${good ? "bg-emerald-500/90 text-emerald-950" : "bg-amber-400/90 text-amber-950"}`}
      title={`Annotée ${ANNOTATION_LABEL[annotation.label].toLowerCase()}${annotation.defects.length ? ` : ${annotation.defects.map((d) => DEFECTS.find((x) => x.id === d)?.label ?? d).join(", ")}` : ""}`}
      data-testid="annotation-badge"
    >
      {good ? "Bonne" : "Mauvaise"}
    </span>
  );
}

/**
 * Annotation humaine d'une version pour le banc d'essai du QC : bonne / mauvaise, défauts, note.
 * Avec `keyboard` : B = bonne, M = mauvaise, ← / → = précédente / suivante (hors champs de saisie).
 */
export function AnnotationBar({
  image,
  onChange,
  keyboard = false,
  inModal = false,
  onPrev,
  onNext,
  navLabel = "case",
}: {
  image: PanelImage;
  onChange: (imageId: number, annotation: Annotation | null) => void;
  keyboard?: boolean;
  /** Raccourcis actifs dans une fenêtre modale (sinon ils s'effacent quand une modale est ouverte). */
  inModal?: boolean;
  onPrev?: () => void;
  onNext?: () => void;
  navLabel?: string;
}) {
  const ann = image.annotation;
  const [note, setNote] = useState(ann?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  // Nouvelle version affichée : la note repart de celle enregistrée.
  const [shownId, setShownId] = useState(image.id);
  if (shownId !== image.id) {
    setShownId(image.id);
    setNote(ann?.note ?? "");
    setError(null);
    setSaved(null);
  }

  async function save(label: AnnotationLabel, defects: DefectId[]) {
    setBusy(true);
    setError(null);
    try {
      const out = await api.annotate(image.id, { label, defects: label === "bad" ? defects : [], note: note.trim() });
      onChange(image.id, out);
      setSaved(`Version ${image.version} annotée « ${ANNOTATION_LABEL[label].toLowerCase()} ».`);
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteAnnotation(image.id);
      onChange(image.id, null);
      setNote("");
      setSaved("Annotation effacée.");
    } catch (e) {
      setError(fullErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const mark = (label: AnnotationLabel) => save(label, label === "bad" ? (ann?.defects ?? []) : []);
  const toggleDefect = (d: DefectId) => {
    const current = ann?.label === "bad" ? ann.defects : [];
    save("bad", current.includes(d) ? current.filter((x) => x !== d) : [...current, d]);
  };
  const saveNote = () => {
    if (ann && note.trim() !== ann.note) save(ann.label, ann.defects);
  };

  // Raccourcis clavier (référence stable sur la dernière version des actions).
  const actions = useRef({ mark, onPrev, onNext, busy });
  useEffect(() => {
    actions.current = { mark, onPrev, onNext, busy };
  });
  useEffect(() => {
    if (!keyboard) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || typing(e.target)) return;
      if (!inModal && modalOpen()) return;
      const a = actions.current;
      const key = e.key.toLowerCase();
      if ((key === "b" || key === "m") && !a.busy) {
        e.preventDefault();
        a.mark(key === "b" ? "good" : "bad");
      } else if (e.key === "ArrowRight" && a.onNext) {
        e.preventDefault();
        a.onNext();
      } else if (e.key === "ArrowLeft" && a.onPrev) {
        e.preventDefault();
        a.onPrev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keyboard, inModal]);

  const pill = (active: boolean, tone: "good" | "bad") =>
    `inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-400 disabled:opacity-50 ${
      active
        ? tone === "good"
          ? "bg-emerald-500 text-emerald-950"
          : "bg-amber-400 text-amber-950"
        : "bg-zinc-800 text-zinc-200 hover:bg-zinc-700"
    }`;

  return (
    <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3" data-testid="annotation-bar">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-medium text-zinc-300">
          <span>
            Annotation <span className="font-normal text-zinc-500">· v{image.version} · banc d&apos;essai QC</span>
          </span>
          <InfoTip help="atelier.annotation" label="Annotation" />
        </h3>
        <div className="flex gap-1.5" role="group" aria-label="Jugement de la version">
          <button type="button" className={pill(ann?.label === "good", "good")} aria-pressed={ann?.label === "good"} onClick={() => mark("good")} disabled={busy} data-testid="annotate-good">
            Bonne <kbd className="rounded bg-black/20 px-1 text-[10px]">B</kbd>
          </button>
          <button type="button" className={pill(ann?.label === "bad", "bad")} aria-pressed={ann?.label === "bad"} onClick={() => mark("bad")} disabled={busy} data-testid="annotate-bad">
            Mauvaise <kbd className="rounded bg-black/20 px-1 text-[10px]">M</kbd>
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1" role="group" aria-label="Défauts (facultatif)">
        {DEFECTS.map((d) => {
          const on = ann?.label === "bad" && ann.defects.includes(d.id);
          return (
            <button
              key={d.id}
              type="button"
              aria-pressed={on}
              onClick={() => toggleDefect(d.id)}
              disabled={busy}
              title={ann?.label === "bad" ? undefined : "Marque aussi la version « mauvaise »"}
              className={`rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset focus-visible:outline-2 focus-visible:outline-rose-400 disabled:opacity-50 ${
                on ? "bg-amber-400/20 text-amber-200 ring-amber-400/60" : "text-zinc-400 ring-zinc-700 hover:text-zinc-200"
              }`}
            >
              {d.label}
            </button>
          );
        })}
      </div>

      <div className="flex gap-1.5">
        <label htmlFor={`annotation-note-${image.id}`} className="sr-only">
          Note libre
        </label>
        <input
          id={`annotation-note-${image.id}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={saveNote}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          maxLength={1000}
          placeholder={ann ? "Note libre (Entrée pour enregistrer)" : "Note libre (enregistrée avec le jugement)"}
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-rose-400 focus:outline-none focus:ring-1 focus:ring-rose-400"
        />
        {ann && (
          <button type="button" onClick={clear} disabled={busy} className="rounded-md px-2 text-xs text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 disabled:opacity-50">
            Effacer
          </button>
        )}
      </div>

      {error ? (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      ) : (
        <p aria-live="polite" className="text-[11px] text-zinc-500" data-testid="annotation-status">
          {saved ?? (ann ? `Annotée « ${ANNOTATION_LABEL[ann.label].toLowerCase()} » · indépendant du verdict QC.` : "Pas encore annotée.")}
          {keyboard && (onPrev || onNext) && ` ← / → : ${navLabel} précédente / suivante.`}
        </p>
      )}
    </div>
  );
}
