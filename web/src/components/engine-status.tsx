"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type ActiveProvider, type ActiveProviders, type Health } from "@/lib/api";

type Status = { state: "loading" } | { state: "online"; health: Health } | { state: "offline" };

const EngineStatusContext = createContext<Status>({ state: "loading" });
const POLL_MS = 5000;

export function EngineStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const health = await api.health();
        if (!cancelled) setStatus({ state: "online", health });
      } catch {
        if (!cancelled) setStatus({ state: "offline" });
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return <EngineStatusContext.Provider value={status}>{children}</EngineStatusContext.Provider>;
}

export const useEngineStatus = () => useContext(EngineStatusContext);

export function OfflineBanner() {
  const status = useEngineStatus();
  if (status.state !== "offline") return null;
  return (
    <div role="alert" className="border-b border-red-900/60 bg-red-950/60 px-6 py-3 text-sm text-red-200">
      <strong className="font-semibold">Moteur hors ligne.</strong> L&apos;interface ne peut pas joindre le moteur
      Python. Vérifie le terminal de <code className="rounded bg-red-900/50 px-1">npm run dev</code> ; la
      reconnexion est automatique.
    </div>
  );
}

type Tone = "ok" | "warn" | "off" | "idle";

const TONES: Record<Tone, string> = {
  ok: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  warn: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  off: "bg-red-500/15 text-red-300 ring-red-500/30",
  idle: "bg-zinc-500/15 text-zinc-400 ring-zinc-500/30",
};
const DOTS: Record<Tone, string> = {
  ok: "bg-emerald-400",
  warn: "bg-amber-400",
  off: "bg-red-400",
  idle: "bg-zinc-500",
};

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOTS[tone]}`} />
      {children}
    </span>
  );
}

export function EngineBadge() {
  const status = useEngineStatus();
  if (status.state === "loading") return <Badge tone="idle">Moteur…</Badge>;
  if (status.state === "offline") return <Badge tone="off">Moteur hors ligne</Badge>;
  return <Badge tone="ok">Moteur OK</Badge>;
}

export function ComfyBadge() {
  const status = useEngineStatus();
  if (status.state === "loading") return <Badge tone="idle">ComfyUI…</Badge>;
  if (status.state === "offline") return <Badge tone="idle">ComfyUI inconnu</Badge>;
  const { comfyui } = status.health;
  const mock = comfyui.provider === "mock";
  if (!comfyui.online) {
    return (
      <Badge tone="off" title={comfyui.detail ?? undefined}>
        ComfyUI hors ligne
      </Badge>
    );
  }
  const queue = comfyui.queue_running + comfyui.queue_pending;
  return (
    <Badge tone={mock ? "warn" : "ok"} title={comfyui.url ?? comfyui.detail ?? undefined}>
      {mock ? "ComfyUI simulé" : "ComfyUI OK"}
      {queue > 0 ? ` · file ${queue}` : ""}
    </Badge>
  );
}

const KIND_LABEL: Record<keyof ActiveProviders, string> = { llm: "LLM", vision: "Vision", comfyui: "ComfyUI" };

const MOCK_HINT: Record<keyof ActiveProviders, string> = {
  llm: "le scénario et la direction artistique sont des textes factices. Pour un vrai LLM : LLM_PROVIDER=deepseek dans .env, avec DEEPSEEK_API_KEY (clé requise), puis relance le moteur.",
  vision: "le contrôle qualité visuel donne un score factice. Pour la vraie vision : VISION_PROVIDER=ollama dans .env, puis relance le moteur.",
  comfyui: "images factices, aucun GPU sollicité. Pour le vrai ComfyUI : COMFYUI_PROVIDER=http (et COMFYUI_URL) dans .env, puis relance le moteur.",
};

/** Texte du badge et de son infobulle pour un fournisseur actif. */
export function providerBadge(kind: keyof ActiveProviders, p: ActiveProvider): { tone: Tone; text: string; tip: string } {
  const label = KIND_LABEL[kind];
  // « Vision simulée » : accord au féminin.
  const name = p.mock && kind === "vision" ? "simulée" : p.label;
  if (p.mock) return { tone: "warn", text: `${label} ${name}`, tip: `${label} ${name} : ${MOCK_HINT[kind]}` };
  if (!p.ok) {
    const key = p.key_env && p.key_set === false ? ` Renseigne ${p.key_env} dans .env (clé requise).` : "";
    return {
      tone: "off",
      text: `${label} ${name} indisponible`,
      tip: `${label} ${name} (${p.env}) : ${p.detail ?? "configuration invalide"}.${key}`,
    };
  }
  const where = p.url ? ` — ${p.url}` : "";
  return { tone: "ok", text: `${label} ${name}`, tip: `${label} ${name} actif (${p.env}=${p.name})${where}` };
}

/** Badges des fournisseurs actifs dans l'en-tête : orange dès qu'un fournisseur est simulé. */
export function ProvidersBadge() {
  const status = useEngineStatus();
  if (status.state !== "online" || !status.health.active) return null;
  const active = status.health.active;
  return (
    <ul className="flex flex-wrap items-center gap-1.5" aria-label="Fournisseurs actifs" data-testid="providers-badge">
      {(Object.keys(KIND_LABEL) as (keyof ActiveProviders)[]).map((kind) => {
        const p = active[kind];
        if (!p) return null;
        const b = providerBadge(kind, p);
        return (
          <li key={kind} tabIndex={0} aria-label={b.tip} className="rounded-full focus-visible:outline-2 focus-visible:outline-rose-400" data-kind={kind} data-mock={p.mock ? "true" : undefined}>
            <Badge tone={b.tone} title={b.tip}>
              {b.text}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}
