"use client";

import { useRef, useState, type DragEvent } from "react";

const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];

/** Zone de glisser-déposer d'images (clic = sélecteur de fichiers). */
export function ImageDropzone({
  onFiles,
  disabled,
  label = "Glisse tes images de référence ici",
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  label?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [rejected, setRejected] = useState<string[]>([]);

  function accept(list: FileList | null) {
    if (!list) return;
    const files = Array.from(list);
    const ok = files.filter((f) => ACCEPTED.includes(f.type));
    setRejected(files.filter((f) => !ACCEPTED.includes(f.type)).map((f) => f.name));
    if (ok.length) onFiles(ok);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    if (!disabled) accept(e.dataTransfer.files);
  }

  return (
    <div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        data-testid="dropzone"
        className={`flex w-full flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
          over ? "border-rose-400 bg-rose-500/10" : "border-zinc-700 hover:border-zinc-500 hover:bg-zinc-900"
        }`}
      >
        <span className="text-sm font-medium text-zinc-200">{label}</span>
        <span className="text-xs text-zinc-500">ou clique pour parcourir · PNG, JPEG, WebP · 20 Mo max</span>
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED.join(",")}
        className="hidden"
        aria-label="Ajouter des images de référence"
        onChange={(e) => {
          accept(e.target.files);
          e.target.value = "";
        }}
      />
      {rejected.length > 0 && (
        <p className="mt-2 text-xs text-amber-400" role="alert">
          Ignoré (format non accepté) : {rejected.join(", ")}
        </p>
      )}
    </div>
  );
}
