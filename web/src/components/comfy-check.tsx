"use client";

import { useState } from "react";
import { api, engineUrl, errorMessage, fullErrorMessage, type ComfyCheck, type Job } from "@/lib/api";
import { useEngineData } from "@/lib/hooks";
import { isFinished, useJob } from "@/lib/jobs";
import { Badge, useEngineStatus } from "./engine-status";
import { useQueue } from "./queue";
import { Alert, Button, Card, ProgressBar, Select } from "./ui";

const GIB = 1024 ** 3;

function gib(bytes: number | null | undefined): string {
  return typeof bytes === "number" ? `${(bytes / GIB).toFixed(1).replace(".", ",")} Go` : "—";
}

function seconds(value: unknown): string {
  return typeof value === "number" ? `${value.toFixed(1).replace(".", ",")} s` : "—";
}

/** Rapport du test de connexion : machine, puis problèmes par preset et LoRA. */
function CheckReport({ report }: { report: ComfyCheck }) {
  if (report.simulated) {
    return (
      <Alert tone="info">
        ComfyUI simulé (mode mock) : aucun serveur à tester, les images sont factices. Pour brancher le vrai
        ComfyUI, mets <code className="text-xs">COMFYUI_PROVIDER=http</code> dans <code className="text-xs">.env</code>{" "}
        puis relance le moteur.
      </Alert>
    );
  }
  if (!report.online) {
    return <Alert>Connexion impossible : {report.error}</Alert>;
  }
  const system = report.system;
  return (
    <div className="space-y-3" data-testid="comfy-report">
      {system && (
        <p className="text-xs text-zinc-400">
          ComfyUI {system.comfyui_version ?? "?"} · PyTorch {system.pytorch_version ?? "?"}
          {system.devices.map((d) => (
            <span key={d.name} className="block">
              {d.name} ({d.type}) — VRAM libre {gib(d.vram_free)} / {gib(d.vram_total)}
            </span>
          ))}
        </p>
      )}
      {report.error && <Alert>{report.error}</Alert>}
      <ul className="space-y-2 text-sm">
        {report.presets.map((p) => (
          <li key={p.id}>
            <span className={p.ok ? "text-emerald-300" : "text-red-300"}>{p.ok ? "✓" : "✗"}</span>{" "}
            <span className="text-zinc-200">{p.name}</span>
            {p.problems.length > 0 && (
              <ul className="ml-5 mt-1 list-disc text-xs text-red-300">
                {p.problems.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
        <li>
          <span className={report.loras.problems.length ? "text-red-300" : "text-emerald-300"}>
            {report.loras.problems.length ? "✗" : "✓"}
          </span>{" "}
          <span className="text-zinc-200">
            LoRA des séries et des personnages ({report.loras.checked} vérifié{report.loras.checked > 1 ? "s" : ""})
          </span>
          {report.loras.problems.length > 0 && (
            <ul className="ml-5 mt-1 list-disc text-xs text-red-300">
              {report.loras.problems.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </li>
      </ul>
    </div>
  );
}

/** Suivi d'une case d'essai : progression, puis image et durée (ou l'erreur en clair). */
function TrialResult({ job, simulated }: { job: Job; simulated: boolean }) {
  const params = job.params ?? {};
  if (!isFinished(job)) {
    return (
      <div className="space-y-2" aria-live="polite">
        <ProgressBar value={job.progress} label="Case d'essai" />
        <p className="text-xs text-zinc-400">{job.message || "En attente…"}</p>
        <Button variant="ghost" onClick={() => api.cancelJob(job.id).catch(() => {})}>
          Annuler
        </Button>
      </div>
    );
  }
  if (job.status === "failed") return <Alert>Échec de la case d&apos;essai : {job.error}</Alert>;
  if (job.status === "cancelled") return <Alert tone="info">Case d&apos;essai annulée.</Alert>;
  return (
    <figure className="space-y-2" data-testid="comfy-trial">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={engineUrl(`/comfyui/trial/${job.id}/image`)}
        alt="Case d'essai générée par ComfyUI"
        className="max-h-80 rounded-md border border-zinc-800"
      />
      <figcaption className="text-xs text-zinc-400">
        {String(params.preset_name ?? params.preset ?? "")} · {String(params.image_width)}×{String(params.image_height)}{" "}
        px · {String(params.steps ?? "?")} étapes · <strong className="text-zinc-200">{seconds(params.duration_s)}</strong>
        {simulated && " · image factice (ComfyUI simulé)"}
      </figcaption>
    </figure>
  );
}

/** Carte « Connexion ComfyUI » du tableau de bord : test de connexion et case d'essai. */
export function ComfyConnection() {
  const status = useEngineStatus();
  const online = status.state === "online";
  const presets = useEngineData(() => api.workflowPresets(), [online]);
  const { refresh } = useQueue();
  const [preset, setPreset] = useState("");
  const [report, setReport] = useState<ComfyCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [trial, setTrial] = useState<Job | null>(null);
  const [trialError, setTrialError] = useState<string | null>(null);

  const liveTrial = useJob(trial, () => refresh());

  const trialPresets = (presets.data ?? []).filter((p) => p.has_trial);
  // Choix de l'utilisateur, sinon le workflow par défaut des séries.
  const chosen = preset || (trialPresets.find((p) => p.is_default) ?? trialPresets[0])?.id || "";

  if (!online) return null;
  const comfy = status.health.comfyui;
  const simulated = comfy.provider === "mock";
  const trialRunning = liveTrial !== null && !isFinished(liveTrial);

  async function check() {
    setChecking(true);
    setCheckError(null);
    try {
      setReport(await api.checkComfy());
    } catch (err) {
      setReport(null);
      setCheckError(`Test impossible : ${errorMessage(err)} (le moteur n'a pas répondu ou ComfyUI met plus de 90 s)`);
    } finally {
      setChecking(false);
    }
  }

  async function startTrial() {
    setTrialError(null);
    try {
      setTrial(await api.startComfyTrial(chosen));
      refresh();
    } catch (err) {
      setTrialError(fullErrorMessage(err));
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-semibold text-zinc-100">Connexion ComfyUI</h2>
          {simulated ? (
            <Badge tone="warn">ComfyUI simulé</Badge>
          ) : comfy.online ? (
            <Badge tone="ok">ComfyUI connecté</Badge>
          ) : (
            <Badge tone="off" title={comfy.detail ?? undefined}>
              ComfyUI non connecté
            </Badge>
          )}
        </div>
        <p className="text-xs text-zinc-500">{simulated ? "COMFYUI_PROVIDER=mock" : comfy.url}</p>
      </div>
      {!simulated && !comfy.online && comfy.detail && <p className="mt-2 text-xs text-red-300">{comfy.detail}</p>}

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <section aria-label="Test de connexion" className="space-y-3">
          <Button variant="secondary" onClick={check} disabled={checking}>
            {checking ? "Test en cours…" : "Tester la connexion"}
          </Button>
          <p className="text-xs text-zinc-500">
            Vérifie que les nœuds, modèles, encodeurs, VAE et LoRA de chaque preset existent dans ComfyUI.
          </p>
          {checkError && <Alert>{checkError}</Alert>}
          {report && <CheckReport report={report} />}
        </section>

        <section aria-label="Case d'essai" className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select
              aria-label="Preset de la case d'essai"
              value={chosen}
              onChange={(e) => setPreset(e.target.value)}
              disabled={!trialPresets.length || trialRunning}
              className="w-auto min-w-0 flex-1"
            >
              {trialPresets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
            <Button onClick={startTrial} disabled={!chosen || trialRunning}>
              Générer une case d&apos;essai
            </Button>
          </div>
          <p className="text-xs text-zinc-500">
            Une vraie génération, petite et rapide, sur le preset choisi (passe par la file ComfyUI).
          </p>
          {presets.error && <Alert>Presets indisponibles : {presets.error}</Alert>}
          {trialError && <Alert>{trialError}</Alert>}
          {liveTrial && <TrialResult job={liveTrial} simulated={simulated} />}
        </section>
      </div>
    </Card>
  );
}
