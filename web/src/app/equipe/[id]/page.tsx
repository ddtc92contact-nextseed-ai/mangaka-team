"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { Alert, Button, Card, Field, Input, Loading, PageHeader, Select } from "@/components/ui";
import {
  api,
  EngineError,
  fullErrorMessage,
  type AgentDetail,
  type AgentSetting,
  type AgentVersion,
  type Knowledge,
  type TrialResult,
} from "@/lib/api";
import { STATE_TONE, displayValue, formatDateTime, fromFormValue, toFormValue } from "@/lib/agents";
import { useEngineData } from "@/lib/hooks";
import { formatMs } from "@/lib/qc";
import { SettingField } from "./setting-field";
import { TrialView } from "./trial-view";

export default function AgentRoute() {
  return (
    <Suspense fallback={<Loading />}>
      <AgentPage />
    </Suspense>
  );
}

function AgentPage() {
  const id = useParams<{ id: string }>().id;
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const projectId = Number(params.get("serie")) || null;

  const agent = useEngineData(() => api.getAgent(id, projectId), [id, projectId]);
  const versions = useEngineData(() => api.agentVersions(id, projectId), [id, projectId]);
  const projects = useEngineData(() => api.listProjects());
  const [notice, setNotice] = useState<string | null>(null);

  function setScope(value: string) {
    setNotice(null);
    router.replace(value ? `${pathname}?serie=${value}` : pathname, { scroll: false });
  }

  if (agent.loading && !agent.data) return <Loading />;
  if (agent.error || !agent.data) return <Alert>{agent.error ?? "Agent introuvable"}</Alert>;
  const a = agent.data;

  return (
    <>
      <PageHeader
        title={`${a.icon} ${a.name}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-3">
            <Link href="/equipe" className="hover:text-zinc-200">
              ← L&apos;équipe
            </Link>
            <span>
              Étape {a.step} · {a.step_label}
            </span>
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATE_TONE[a.status.state]}`}
              title={a.status.detail ?? undefined}
            >
              {a.status.label}
            </span>
          </span>
        }
      />
      <p className="-mt-4 mb-6 max-w-3xl text-sm text-zinc-400">{a.role}</p>

      <Card className="mb-6 flex flex-wrap items-end gap-4">
        <div className="w-full max-w-xs">
          <Field label="Réglages de" htmlFor="scope">
            <Select id="scope" value={projectId ?? ""} onChange={(e) => setScope(e.target.value)}>
              <option value="">Profil global (toutes les séries)</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  Pour la série « {p.title} » seulement
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <p className="flex-1 text-xs text-zinc-500">
          {projectId
            ? `Une valeur modifiée ici ne vaut que pour « ${a.scope.project_title} » ; le reste suit le profil global (v${a.global_version}).`
            : "Ordre appliqué par le pipeline : réglages d'une série > profil global > presets livrés."}
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-zinc-500">Modèle</dt>
          <dd className="text-zinc-200">{a.model}</dd>
          <dt className="text-zinc-500">Dernier passage</dt>
          <dd className="text-zinc-300">
            {a.last_run ? `${formatDateTime(a.last_run.finished_at)} · ${formatMs(a.last_run.duration_ms)}` : "jamais lancé"}
          </dd>
        </dl>
      </Card>

      {a.status.state !== "ready" && a.status.detail && (
        <div className="mb-4">
          <Alert>{a.status.detail}</Alert>
        </div>
      )}
      {a.problem && (
        <div className="mb-4">
          <Alert>{a.problem}</Alert>
        </div>
      )}

      {notice && (
        <div className="mb-4">
          <Alert tone="info">{notice}</Alert>
        </div>
      )}

      <AgentForm
        key={`${a.id}-${projectId}-${a.version}`}
        agent={a}
        projectId={projectId}
        onSaved={(d, text) => {
          agent.setData(d);
          versions.reload();
          setNotice(text);
        }}
      />

      <History
        agent={a}
        versions={versions.data ?? []}
        projectId={projectId}
        onRestored={(d, text) => {
          agent.setData(d);
          versions.reload();
          setNotice(text);
        }}
      />
    </>
  );
}

type FormValues = Record<string, unknown>;

function initialValues(settings: AgentSetting[]): FormValues {
  return Object.fromEntries(settings.map((s) => [s.key, toFormValue(s, s.value)]));
}

function AgentForm({
  agent,
  projectId,
  onSaved,
}: {
  agent: AgentDetail;
  projectId: number | null;
  onSaved: (d: AgentDetail, notice: string) => void;
}) {
  const initial = useMemo(() => initialValues(agent.settings), [agent.settings]);
  const [values, setValues] = useState<FormValues>(initial);
  const [knowledge, setKnowledge] = useState({
    collections: agent.knowledge.value.collections.join(", "),
    top_k: String(agent.knowledge.value.top_k),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState<"save" | "trial" | "reset" | null>(null);
  const [trial, setTrial] = useState<TrialResult | null>(null);

  const dirty = agent.settings.some((s) => JSON.stringify(values[s.key]) !== JSON.stringify(initial[s.key]));
  const knowledgeValue: Knowledge = {
    collections: knowledge.collections
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean),
    top_k: Number(knowledge.top_k),
  };
  const knowledgeDirty = JSON.stringify(knowledgeValue) !== JSON.stringify(agent.knowledge.value);

  function payload() {
    return {
      values: Object.fromEntries(agent.settings.map((s) => [s.key, fromFormValue(s, values[s.key])])),
      knowledge: knowledgeValue,
    };
  }

  function fail(err: unknown) {
    if (err instanceof EngineError && Object.keys(err.fieldErrors).length) {
      setErrors(err.fieldErrors);
      setMessage({ tone: "error", text: "Réglages invalides : corrige les champs signalés." });
    } else {
      setMessage({ tone: "error", text: fullErrorMessage(err) });
    }
  }

  async function save() {
    setBusy("save");
    setErrors({});
    setMessage(null);
    try {
      const d = await api.saveAgent(agent.id, projectId, payload());
      onSaved(
        d,
        d.saved_version
          ? `Réglages enregistrés : version ${d.saved_version}.`
          : "Aucun changement : les valeurs sont identiques à celles héritées.",
      );
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function runTrial() {
    setBusy("trial");
    setErrors({});
    setMessage(null);
    setTrial(null);
    try {
      setTrial(await api.tryAgent(agent.id, projectId, payload()));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    const what = projectId
      ? `Supprimer les réglages propres à « ${agent.scope.project_title} » ? La série suivra le profil global.`
      : "Revenir aux réglages d'origine (presets livrés) pour toutes les séries sans réglages propres ?";
    if (!window.confirm(what)) return;
    setBusy("reset");
    setMessage(null);
    try {
      const d = await api.resetAgent(agent.id, projectId);
      onSaved(
        d,
        projectId
          ? `Réglages de la série supprimés (version ${d.saved_version ?? d.version}) : elle suit le profil global.`
          : `Réglages d'origine rétablis (version ${d.saved_version ?? d.version}).`,
      );
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  const groups = [...new Set(agent.settings.map((s) => s.group || "Réglages"))];

  return (
    <>
      <Card className="mb-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
          noValidate
        >
          {groups.map((g) => (
            <fieldset key={g} className="mb-6 border-b border-zinc-800 pb-6">
              <legend className="mb-4 text-sm font-semibold text-zinc-100">{g}</legend>
              <div className="grid gap-5 md:grid-cols-2">
                {agent.settings
                  .filter((s) => (s.group || "Réglages") === g)
                  .map((s) => (
                    <SettingField
                      key={s.key}
                      setting={s}
                      value={values[s.key]}
                      onChange={(v) => setValues((cur) => ({ ...cur, [s.key]: v }))}
                      error={errors[s.key]}
                      modified={JSON.stringify(values[s.key]) !== JSON.stringify(initial[s.key])}
                      locked={Boolean(projectId) && s.global_only}
                    />
                  ))}
              </div>
            </fieldset>
          ))}

          <fieldset className="mb-6 border-b border-zinc-800 pb-6">
            <legend className="mb-1 text-sm font-semibold text-zinc-100">Savoir-faire</legend>
            <p className="mb-4 text-xs text-zinc-500">
              Collections de la base de connaissances consultées par l&apos;agent. La base n&apos;existe pas encore :
              ces réglages sont conservés et serviront dès qu&apos;elle sera disponible.
            </p>
            <div className="grid gap-5 md:grid-cols-[2fr_1fr]">
              <Field
                label="Collections (identifiants, séparés par des virgules)"
                htmlFor="knowledge-collections"
                error={errors["knowledge.collections"]}
              >
                <Input
                  id="knowledge-collections"
                  value={knowledge.collections}
                  onChange={(e) => setKnowledge((k) => ({ ...k, collections: e.target.value }))}
                  placeholder="ex. style-shonen, anatomie"
                />
              </Field>
              <Field label="Extraits par requête (top-k)" htmlFor="knowledge-top-k" error={errors["knowledge.top_k"]}>
                <Input
                  id="knowledge-top-k"
                  inputMode="numeric"
                  value={knowledge.top_k}
                  onChange={(e) => setKnowledge((k) => ({ ...k, top_k: e.target.value }))}
                />
              </Field>
            </div>
          </fieldset>

          {agent.secrets.length > 0 && (
            <div className="mb-6 border-b border-zinc-800 pb-6">
              <h3 className="mb-2 text-sm font-semibold text-zinc-100">Clés d&apos;API</h3>
              <ul className="space-y-1 text-sm">
                {agent.secrets.map((s) => (
                  <li key={s.env} className="flex items-center gap-2">
                    <span className={s.present ? "text-emerald-300" : "text-amber-300"}>
                      {s.present ? "● clé présente" : "○ clé absente"}
                    </span>
                    <span className="text-zinc-300">{s.label}</span>
                    <span className="font-mono text-xs text-zinc-500">({s.env} dans .env)</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-zinc-500">Les clés ne s&apos;affichent ni ne se modifient ici : elles restent dans .env.</p>
            </div>
          )}

          {message && (
            <div className="mb-4">
              <Alert tone={message.tone}>{message.text}</Alert>
            </div>
          )}
          {errors._general && (
            <div className="mb-4">
              <Alert>{errors._general}</Alert>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={busy !== null || (!dirty && !knowledgeDirty)}>
              {busy === "save" ? "Enregistrement…" : "Enregistrer"}
            </Button>
            {agent.trial && (
              <Button type="button" variant="secondary" disabled={busy !== null} onClick={() => void runTrial()}>
                {busy === "trial" ? "Essai en cours…" : "Essayer"}
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              disabled={busy !== null || (!dirty && !knowledgeDirty)}
              onClick={() => {
                setValues(initial);
                setKnowledge({
                  collections: agent.knowledge.value.collections.join(", "),
                  top_k: String(agent.knowledge.value.top_k),
                });
                setErrors({});
              }}
            >
              Annuler les modifications
            </Button>
            <a
              href={api.agentExportUrl(agent.id, projectId)}
              download
              className="inline-flex items-center rounded-md px-3.5 py-2 text-sm font-medium text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
            >
              Exporter en YAML
            </a>
            <Button type="button" variant="danger" className="ml-auto" disabled={busy !== null || agent.version === 0} onClick={() => void reset()}>
              {projectId ? "Supprimer les réglages de la série" : "Revenir aux réglages d'origine"}
            </Button>
          </div>
        </form>
      </Card>

      {agent.trial && (
        <Card className="mb-6">
          <h2 className="mb-1 font-semibold text-zinc-100">Essayer</h2>
          <p className="mb-4 text-sm text-zinc-400">
            {agent.trial_description} Les réglages du formulaire sont utilisés tels quels, même non enregistrés.
          </p>
          {busy === "trial" && <Loading />}
          {trial ? <TrialView result={trial} /> : busy !== "trial" && <p className="text-sm text-zinc-500">Aucun essai pour l&apos;instant.</p>}
        </Card>
      )}
    </>
  );
}

function History({
  agent,
  versions,
  projectId,
  onRestored,
}: {
  agent: AgentDetail;
  versions: AgentVersion[];
  projectId: number | null;
  onRestored: (d: AgentDetail, notice: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  async function restore(v: number) {
    setBusy(v);
    setError(null);
    try {
      const d = await api.restoreAgentVersion(agent.id, v, projectId);
      onRestored(
        d,
        d.saved_version
          ? `Retour à la version ${v} : version ${d.saved_version} créée.`
          : `La version ${v} est identique aux réglages en cours.`,
      );
    } catch (err) {
      setError(fullErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <h2 className="mb-1 font-semibold text-zinc-100">Historique des versions</h2>
      <p className="mb-4 text-sm text-zinc-400">
        {projectId ? `Réglages propres à « ${agent.scope.project_title} ».` : "Profil global."} Chaque enregistrement crée une
        version ; revenir à une version en crée une nouvelle.
      </p>
      {error && (
        <div className="mb-3">
          <Alert>{error}</Alert>
        </div>
      )}
      {versions.length === 0 ? (
        <p className="text-sm text-zinc-500">Aucune version : les réglages d&apos;origine s&apos;appliquent.</p>
      ) : (
        <ol className="divide-y divide-zinc-800" data-testid="versions">
          {versions.map((v) => (
            <li key={v.version} className="flex flex-wrap items-start gap-3 py-3">
              <span className="w-10 shrink-0 font-mono text-sm text-zinc-300">v{v.version}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-zinc-200">
                  {v.action_label}
                  <span className="text-zinc-500">
                    {" "}
                    · {formatDateTime(v.created_at)} · {v.author}
                  </span>
                </p>
                {v.diff.length > 0 ? (
                  <ul className="mt-1 space-y-0.5 text-xs text-zinc-400">
                    {v.diff.map((d) => (
                      <li key={d.key}>
                        <span className="text-zinc-300">{d.label}</span> : {displayValue(d.before, 60)} →{" "}
                        <span className="text-zinc-200">{displayValue(d.after, 60)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-zinc-500">Aucune différence de valeur.</p>
                )}
              </div>
              {v.version === agent.version ? (
                <span className="text-xs text-emerald-300">version en cours</span>
              ) : (
                <Button variant="secondary" className="text-xs" disabled={busy !== null} onClick={() => void restore(v.version)}>
                  {busy === v.version ? "…" : "Revenir à cette version"}
                </Button>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
