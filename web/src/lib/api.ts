// Client de l'API du moteur (via le proxy Next.js /api/engine).

export const ENGINE_BASE = "/api/engine";

export type ReadingDirection = "ltr" | "rtl";
export type SeriesStatus = "ongoing" | "paused" | "completed" | "cancelled";
export type ChapterStatus = "draft" | "script" | "layout" | "generation" | "lettering" | "ready" | "published";
export type PageKind = "story" | "bonus" | "chapter_cover";
export type BubbleKind = "speech" | "thought" | "shout" | "narration" | "off";

/** Une série (« projet » côté moteur). */
export interface Project {
  id: number;
  title: string;
  style: string;
  status: SeriesStatus;
  reading_direction: ReadingDirection;
  page_format: string;
  workflow_preset: string;
  style_lora_name: string | null;
  style_lora_weight: number;
  character_count: number;
  chapter_count: number;
  /** Pages déjà mises en page : changer le sens de lecture les met en miroir. */
  laid_out_page_count: number;
  created_at: string;
  updated_at: string;
}

export type ProjectInput = Pick<
  Project,
  | "title"
  | "style"
  | "status"
  | "reading_direction"
  | "page_format"
  | "workflow_preset"
  | "style_lora_name"
  | "style_lora_weight"
>;

export interface Chapter {
  id: number;
  project_id: number;
  series_title: string;
  number: number;
  title: string;
  synopsis: string;
  summary: string;
  target_page_count: number;
  status: ChapterStatus;
  planned_date: string | null;
  page_count: number;
  panel_count: number;
  created_at: string;
  updated_at: string;
}

export type ChapterInput = Pick<Chapter, "title" | "synopsis" | "target_page_count" | "status" | "planned_date"> & {
  summary?: string;
};

export interface Dialogue {
  id?: number;
  speaker: string;
  text: string;
  kind: BubbleKind;
}

export interface Rect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface PanelData {
  id: number;
  index: number;
  description: string;
  characters: string[];
  shot_type: string | null;
  importance: number;
  dialogues: Dialogue[];
  bbox: Rect | null;
  bubble_zone: Rect | null;
  state: PanelState;
  final_prompt: string | null;
  final_prompt_manual: boolean;
  generation_preset: string | null;
  image_count: number;
  selected_image_id: number | null;
  selected_image_url: string | null;
  /** QC de la version choisie (null : pas encore contrôlée). */
  qc_verdict: QCVerdict | null;
  qc_score: number | null;
  qc_reasons: string[];
  qc_override: boolean;
  detections: Detections | null;
}

export type QCVerdict = "ok" | "review" | "reject";
export type QCLayerName = "detectors" | "identity" | "vision";

/** Boîte détectée, en px de l'image générée. */
export interface DetectionBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  score: number;
  label: string;
}

export interface Detections {
  width: number;
  height: number;
  faces: DetectionBox[];
  hands: DetectionBox[];
  text: DetectionBox[];
  provider?: string | null;
}

export interface QCLayer {
  status: "done" | "skipped" | "unavailable" | "error";
  score: number | null;
  reasons: string[];
  at_least: QCVerdict | null;
  message: string | null;
  duration_ms: number;
  provider: string | null;
  characters?: { name: string; similarity: number; score: number; ok: boolean }[];
  without_references?: string[];
  counts?: { faces: number; hands: number; text: number };
  expected_faces?: number;
  attempts?: number;
  why?: string;
}

/** Détail du dernier QC d'une version. */
export interface QCDetails {
  verdict?: QCVerdict;
  score?: number;
  computed_verdict?: QCVerdict;
  source?: "auto" | "manual" | "human";
  attempt?: number;
  at?: string;
  duration_ms?: number;
  layers?: Partial<Record<QCLayerName, QCLayer>>;
  override?: { verdict: "ok"; by: string; at: string; previous_verdict: QCVerdict | null; previous_score: number | null; note: string | null } | null;
  history?: { verdict: QCVerdict | null; score: number | null; source: string | null; at: string | null; override?: boolean }[];
  auto_retry?: { attempt: number; job_id?: number; error?: string };
}

export interface QCStatus {
  available: boolean;
  detail: string | null;
  auto_after_generation: boolean;
  max_auto_retries: number;
  ok_min: number | null;
  reject_below: number | null;
  vision_mode: string | null;
  layers: Record<QCLayerName, { provider: string | null; available: boolean; detail: string | null }>;
}

export interface QCSummary {
  ok: number;
  review: number;
  reject: number;
  unchecked: number;
  no_image: number;
  total: number;
}

export interface ChapterQCResult {
  job: Job | null;
  panel_ids: number[];
  skipped: number;
  summary: QCSummary;
}

export type VisionMode = "auto" | "force" | "skip";

export type PanelState = "draft" | "queued" | "generating" | "review" | "qc" | "flagged" | "approved";

export interface LayoutPanel extends Rect {
  index: number;
  reading_order: number;
  panel_id: number | null;
  width: number;
  height: number;
  ratio: number;
  target: { width: number; height: number };
  bubble_zone: Rect | null;
}

export interface LayoutGutter extends Rect {
  path: number[];
  index: number;
  orientation: "horizontal" | "vertical";
  position: number;
  min: number;
  max: number;
}

export interface PageLayout {
  version: number;
  template_id: string;
  page_format: string;
  dpi: number;
  direction: ReadingDirection;
  page_number: number;
  page: { width: number; height: number };
  live_area: Rect;
  inner_side: "left" | "right";
  gutters_px: { horizontal: number; vertical: number };
  panels: LayoutPanel[];
  gutters: LayoutGutter[];
}

export interface PageData {
  id: number;
  chapter_id: number;
  number: number;
  kind: PageKind;
  grid_template: string | null;
  state: string;
  layout: PageLayout | null;
  layout_stale: boolean;
  panels: PanelData[];
}

/** Découpage envoyé au moteur : `id` absent = nouvel élément. */
export interface PanelInput {
  id?: number;
  description: string;
  characters: string[];
  shot_type: string | null;
  importance: number;
  dialogues: Dialogue[];
}

export interface PageInput {
  id?: number;
  kind: PageKind;
  panels: PanelInput[];
}

export type JobStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: number;
  step: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  project_id: number | null;
  chapter_id: number | null;
  panel_id?: number | null;
  params?: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

/** Une version générée d'une case. */
export interface PanelImage {
  id: number;
  panel_id: number;
  version: number;
  url: string;
  seed: Seed | null;
  selected: boolean;
  width: number | null;
  height: number | null;
  preset: string | null;
  params: {
    prompt?: string;
    negative_prompt?: string;
    duration_ms?: number;
    loras?: unknown[];
    references?: unknown[];
    [key: string]: unknown;
  };
  qc_score: number | null;
  qc_reasons: string[];
  qc_verdict: QCVerdict | null;
  qc: QCDetails;
  detections: Detections | null;
  /** Jugement humain bonne / mauvaise (banc d'essai du QC), indépendant du verdict QC. */
  annotation: Annotation | null;
  created_at: string;
}

export type AnnotationLabel = "good" | "bad";
export type DefectId = "face" | "hands" | "identity" | "description" | "text" | "other";

export interface Annotation {
  label: AnnotationLabel;
  defects: DefectId[];
  note: string;
  updated_at: string;
}

export type AnnotationInput = Pick<Annotation, "label" | "defects" | "note">;

export type BenchLayerName = QCLayerName | "combined";

export interface BenchDataset {
  good: number;
  bad: number;
  total: number;
  by_defect: Record<DefectId, number>;
  goal_min: number | null;
  goal_max: number | null;
  target_recall: number | null;
}

export interface BenchConfusion {
  tp: number;
  fp: number;
  fn: number;
  tn: number;
}

export interface BenchPoint extends BenchConfusion {
  threshold: number;
  precision: number | null;
  recall: number | null;
}

export interface BenchLayerMetrics {
  label: string;
  evaluated: number;
  missing: number;
  good: number;
  bad: number;
  confusion: BenchConfusion;
  precision: number | null;
  recall: number | null;
  current_threshold: number | null;
  threshold_key: string | null;
  sweep: BenchPoint[];
  suggested: BenchPoint | null;
  suggestion_note: string | null;
  mean_ms: number | null;
}

export interface BenchMetrics {
  target_recall: number;
  samples: number;
  good: number;
  bad: number;
  errors: number;
  mean_ms_per_case: number | null;
  layers: Record<BenchLayerName, BenchLayerMetrics>;
}

export interface BenchItemLayer {
  status: QCLayer["status"];
  score: number | null;
  value: number | null;
  floor: boolean;
  flagged: boolean | null;
  duration_ms: number;
  message: string | null;
  reasons: string[];
  verdict?: QCVerdict | null;
  vision_used?: boolean;
}

export interface BenchItem {
  image_id: number;
  panel_id: number;
  page_id: number;
  chapter_id: number;
  project_id: number;
  label: string;
  bad: boolean;
  defects: DefectId[];
  note: string;
  layers: Partial<Record<BenchLayerName, BenchItemLayer>>;
  error: string | null;
}

export interface BenchRunSummary {
  id: number;
  job: Job | null;
  status: JobStatus;
  error: string | null;
  project_id: number | null;
  chapter_id: number | null;
  scope: string;
  vision: boolean;
  preset_hash: string | null;
  sample_count: number;
  good: number | null;
  bad: number | null;
  created_at: string;
  finished_at: string | null;
  applied_at: string | null;
  layers: Partial<
    Record<BenchLayerName, { label: string; precision: number | null; recall: number | null; fp: number; fn: number; evaluated: number; mean_ms: number | null }>
  >;
}

export interface BenchRun extends BenchRunSummary {
  metrics: BenchMetrics | null;
  items: BenchItem[];
  preset: Record<string, unknown>;
  previous: BenchRunSummary | null;
  current_preset_hash: string | null;
}

export interface BenchChange {
  key: string;
  label: string;
  before: number;
  after: number;
}

export interface BenchApplyResult {
  applied: boolean;
  changes: BenchChange[];
  preset_changed: boolean;
  message: string;
}

/** Détail d'une case pour l'atelier. */
export interface PanelDetail {
  id: number;
  page_id: number;
  page_number: number;
  chapter_id: number;
  project_id: number;
  index: number;
  label: string;
  description: string;
  characters: string[];
  character_ids: number[];
  shot_type: string | null;
  state: PanelState;
  bbox: Rect | null;
  final_prompt: string | null;
  final_prompt_manual: boolean;
  generation_preset: string | null;
  resolved_preset: string | null;
  target: { width: number; height: number } | null;
  images: PanelImage[];
  active_jobs: Job[];
}

export interface GenerateInput {
  count?: number;
  seed?: Seed | null;
  preset?: string | null;
  prompt_override?: string | null;
}

export interface BatchGenerateResult {
  jobs: Job[];
  panel_ids: number[];
  skipped: number;
}

export interface QueueItem {
  job: Job;
  position: number;
  label: string;
  panel_id: number | null;
  panel_index: number | null;
  page_id: number | null;
  page_number: number | null;
  chapter_id: number | null;
  chapter_number: number | null;
  chapter_title: string | null;
  project_id: number | null;
  series_title: string | null;
  preset: string | null;
  variant: number | null;
  count: number | null;
  estimated_duration_s: number | null;
  eta_s: number | null;
}

export interface Queue {
  running: QueueItem | null;
  pending: QueueItem[];
  total_eta_s: number | null;
  comfyui: string | null;
}

export interface WorkflowPreset {
  id: string;
  name: string;
  description: string;
  params: string[];
  reference_slots: number;
  supports_lora: boolean;
  lora_loader: string | null;
  timeout_s: number;
  is_default: boolean;
  is_reference_default: boolean;
}

export interface LayoutTemplate {
  id: string;
  name: string;
  panel_count: number;
}

export interface ReferenceImage {
  id: number;
  url: string;
  original_name: string;
  content_type: string;
  width: number;
  height: number;
  created_at: string;
}

export interface Character {
  id: number;
  project_id: number;
  name: string;
  visual_description: string;
  prompt_keywords: string[];
  lora_name: string | null;
  lora_weight: number;
  reference_images: ReferenceImage[];
  created_at: string;
  updated_at: string;
}

export type CharacterInput = Pick<
  Character,
  "name" | "visual_description" | "prompt_keywords" | "lora_name" | "lora_weight"
>;

export interface Health {
  engine: { status: string; version: string };
  comfyui: {
    online: boolean;
    provider: string | null;
    url: string | null;
    queue_running: number;
    queue_pending: number;
    detail: string | null;
  };
  providers: Record<
    "llm" | "vision" | "comfyui" | "detectors" | "identity",
    { name: string | null; ok: boolean; detail: string | null }
  >;
  mock: boolean;
  presets: { page_formats: number; workflows: number; issues: number };
}

export interface Presets {
  defaults: { page_format: string; workflow: string } | null;
  page_formats: {
    id: string;
    name: string;
    width_mm: number;
    height_mm: number;
    dpi: number;
    width_px: number;
    height_px: number;
  }[];
  workflows: { id: string; name: string; description: string; params: string[] }[];
  fonts: { id: string; name: string; bold: boolean; italic: boolean }[];
  layout_templates: LayoutTemplate[];
  prompts: string[];
  issues: { file: string; message: string }[];
}

/** Étape 5 : lettrage calculé d'une page (px de la page finie, hors fond perdu). */
export interface BubbleBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LetteredBubble {
  id: number;
  panel_id: number;
  kind: BubbleKind;
  text: string;
  speaker: string;
  box: BubbleBox;
  tail: { x: number; y: number } | null;
  manual: boolean;
  manual_tail: boolean;
  overflow: boolean;
  font: { family: string; size_pt: number; size_px: number; color: string };
  lines: { text: string; x: number; y: number }[];
  shape: { path: string; fill: string; stroke: string; stroke_px: number };
}

export interface LetteringWarning {
  code: "text_overflow" | "faces_covered" | "missing_image" | "layout_stale" | "no_layout" | string;
  message: string;
  panel_id: number | null;
  bubble_id: number | null;
  page_number?: number;
}

export interface PageLettering {
  page_id: number;
  page_number: number;
  chapter_id: number;
  dpi: number;
  page_format: string;
  direction: ReadingDirection | null;
  width: number;
  height: number;
  bleed_mm: number;
  layout_stale: boolean;
  styles: Record<BubbleKind, { family: string; name: string; url: string; size_pt: number }>;
  panels: { id: number; index: number; box: Rect; bubble_zone: Rect | null; image_url: string | null; faces: Rect[] }[];
  bubbles: LetteredBubble[];
  warnings: LetteringWarning[];
}

export interface BubbleUpdate {
  text?: string;
  kind?: BubbleKind;
  speaker?: string;
  position?: BubbleBox | null;
  tail?: { x: number; y: number } | null;
}

export interface PageRender {
  page_id: number;
  page_number: number;
  stem: string;
  bleed: boolean;
  crop_marks: boolean;
  width: number;
  height: number;
  dpi: number | null;
  rendered_at: string;
  warnings: LetteringWarning[];
  png_url: string;
  svg_url: string;
}

export interface ExportOptions {
  bleed: boolean;
  crop_marks: boolean;
}

export class EngineError extends Error {
  constructor(
    message: string,
    public status: number,
    public fieldErrors: Record<string, string> = {},
    public offline = false,
  ) {
    super(message);
  }
}

export function engineUrl(path: string): string {
  return `${ENGINE_BASE}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(engineUrl(path), { cache: "no-store", ...init });
  } catch {
    throw new EngineError("Interface web injoignable", 0, {}, true);
  }
  if (res.status === 204) return undefined as T;
  const data = await res
    .text()
    .then(parseEngineJson)
    .catch(() => null);
  if (!res.ok) {
    const fieldErrors: Record<string, string> = {};
    for (const e of data?.errors ?? []) fieldErrors[e.field] = e.message;
    const detail = typeof data?.detail === "string" ? data.detail : `Erreur ${res.status}`;
    throw new EngineError(detail, res.status, fieldErrors, Boolean(data?.offline));
  }
  return data as T;
}

/**
 * Les seeds vont jusqu'à 2⁶³ − 1 : au-delà de 2⁵³, `JSON.parse` les arrondirait (et « Même seed »
 * relancerait une autre seed). On les garde donc en texte ; le moteur accepte une seed en chaîne.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function parseEngineJson(text: string): any {
  return JSON.parse(text.replace(/("seed"\s*:\s*)(\d{16,})/g, '$1"$2"'));
}

/** Seed telle que renvoyée par le moteur : nombre, ou texte si elle dépasse les entiers exacts de JS. */
export type Seed = number | string;

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: async () => {
    const health = await request<Health>("/health");
    // Un autre service sur le port du moteur répondrait 200 sans ce contenu : on le traite comme hors ligne.
    if (!health?.engine || !health.comfyui || !health.providers) {
      throw new EngineError("Réponse inattendue du moteur", 502, {}, true);
    }
    return health;
  },
  presets: () => request<Presets>("/presets"),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  createProject: (body: Partial<ProjectInput>) => request<Project>("/projects", json("POST", body)),
  updateProject: (id: number, body: Partial<ProjectInput>) => request<Project>(`/projects/${id}`, json("PATCH", body)),
  deleteProject: (id: number) => request<void>(`/projects/${id}`, { method: "DELETE" }),

  listCharacters: (projectId: number) => request<Character[]>(`/projects/${projectId}/characters`),
  getCharacter: (id: number) => request<Character>(`/characters/${id}`),
  createCharacter: (projectId: number, body: CharacterInput) =>
    request<Character>(`/projects/${projectId}/characters`, json("POST", body)),
  updateCharacter: (id: number, body: Partial<CharacterInput>) =>
    request<Character>(`/characters/${id}`, json("PATCH", body)),
  deleteCharacter: (id: number) => request<void>(`/characters/${id}`, { method: "DELETE" }),
  uploadReferenceImages: (id: number, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request<Character>(`/characters/${id}/images`, { method: "POST", body: form });
  },
  deleteReferenceImage: (characterId: number, imageId: number) =>
    request<void>(`/characters/${characterId}/images/${imageId}`, { method: "DELETE" }),

  listChapters: (projectId: number) => request<Chapter[]>(`/projects/${projectId}/chapters`),
  upcomingChapters: (days = 7) => request<Chapter[]>(`/chapters/upcoming?days=${days}`),
  getChapter: (id: number) => request<Chapter>(`/chapters/${id}`),
  createChapter: (projectId: number, body: Partial<ChapterInput>) =>
    request<Chapter>(`/projects/${projectId}/chapters`, json("POST", body)),
  updateChapter: (id: number, body: Partial<ChapterInput>) => request<Chapter>(`/chapters/${id}`, json("PATCH", body)),
  deleteChapter: (id: number) => request<void>(`/chapters/${id}`, { method: "DELETE" }),
  reorderChapters: (projectId: number, chapterIds: number[]) =>
    request<Chapter[]>(`/projects/${projectId}/chapters/reorder`, json("POST", { chapter_ids: chapterIds })),

  startScript: (chapterId: number) => request<Job>(`/chapters/${chapterId}/script`, { method: "POST" }),
  chapterJobs: (chapterId: number, step?: string) =>
    request<Job[]>(`/chapters/${chapterId}/jobs${step ? `?step=${encodeURIComponent(step)}` : ""}`),
  getJob: (id: number) => request<Job>(`/jobs/${id}`),

  listPages: (chapterId: number) => request<PageData[]>(`/chapters/${chapterId}/pages`),
  savePages: (chapterId: number, pages: PageInput[]) =>
    request<PageData[]>(`/chapters/${chapterId}/pages`, json("PUT", { pages })),
  layoutChapter: (chapterId: number) => request<PageData[]>(`/chapters/${chapterId}/layout`, { method: "POST" }),
  layoutPage: (pageId: number, body: { template_id?: string | null } = {}) =>
    request<PageData>(`/pages/${pageId}/layout`, json("POST", body)),
  moveGutter: (pageId: number, body: { path: number[]; index: number; position: number }) =>
    request<PageData>(`/pages/${pageId}/gutters`, json("POST", body)),
  layoutTemplates: () => request<LayoutTemplate[]>("/layout/templates"),

  cancelJob: (id: number) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  queue: () => request<Queue>("/queue"),
  workflowPresets: () => request<WorkflowPreset[]>("/presets/workflows"),
  getPanel: (id: number) => request<PanelDetail>(`/panels/${id}`),
  updatePanel: (id: number, body: { final_prompt?: string | null; generation_preset?: string | null }) =>
    request<PanelDetail>(`/panels/${id}`, json("PATCH", body)),
  rebuildPrompt: (id: number) => request<PanelDetail>(`/panels/${id}/prompt/rebuild`, { method: "POST" }),
  generatePanel: (id: number, body: GenerateInput = {}) => request<Job[]>(`/panels/${id}/generate`, json("POST", body)),
  generatePage: (id: number, body: { force?: boolean; count?: number } = {}) =>
    request<BatchGenerateResult>(`/pages/${id}/generate`, json("POST", body)),
  generateChapter: (id: number, body: { force?: boolean; count?: number } = {}) =>
    request<BatchGenerateResult>(`/chapters/${id}/generate`, json("POST", body)),
  selectPanelImage: (id: number) => request<PanelImage[]>(`/panel-images/${id}/select`, { method: "POST" }),
  deletePanelImage: (id: number) => request<void>(`/panel-images/${id}`, { method: "DELETE" }),

  getLettering: (pageId: number) => request<PageLettering>(`/pages/${pageId}/lettering`),
  resetLettering: (pageId: number) => request<PageLettering>(`/pages/${pageId}/lettering/reset`, { method: "POST" }),
  updateBubble: (id: number, body: BubbleUpdate) => request<PageLettering>(`/bubbles/${id}`, json("PATCH", body)),
  renderPage: (pageId: number, body: ExportOptions) => request<PageRender>(`/pages/${pageId}/render`, json("POST", body)),
  getRender: (pageId: number) => request<PageRender>(`/pages/${pageId}/render`),
  exportChapter: (chapterId: number, body: ExportOptions) =>
    request<Job>(`/chapters/${chapterId}/export`, json("POST", body)),
  qcStatus: () => request<QCStatus>("/qc/status"),
  runPanelQC: (id: number, body: { image_id?: number; vision?: VisionMode } = {}) =>
    request<Job>(`/panels/${id}/qc`, json("POST", body)),
  runChapterQC: (id: number, body: { force?: boolean; vision?: VisionMode } = {}) =>
    request<ChapterQCResult>(`/chapters/${id}/qc`, json("POST", body)),
  chapterQC: (id: number) => request<QCSummary>(`/chapters/${id}/qc`),
  overrideQC: (imageId: number, note?: string) =>
    request<PanelImage>(`/panel-images/${imageId}/qc/override`, json("POST", note ? { note } : {})),

  annotate: (imageId: number, body: AnnotationInput) =>
    request<Annotation>(`/panel-images/${imageId}/annotation`, json("PUT", body)),
  deleteAnnotation: (imageId: number) => request<void>(`/panel-images/${imageId}/annotation`, { method: "DELETE" }),
  benchDataset: (scope: BenchScope = {}) => request<BenchDataset>(`/qc/bench/dataset${scopeQuery(scope)}`),
  benchRuns: () => request<BenchRunSummary[]>("/qc/bench/runs"),
  benchRun: (id: number) => request<BenchRun>(`/qc/bench/runs/${id}`),
  startBenchRun: (body: BenchScope & { vision?: boolean }) => request<BenchRunSummary>("/qc/bench/runs", json("POST", body)),
  applyBenchThresholds: (id: number, confirm: boolean) =>
    request<BenchApplyResult>(`/qc/bench/runs/${id}/apply`, json("POST", { confirm })),
  benchExportUrl: (id: number, format: "json" | "csv") => engineUrl(`/qc/bench/runs/${id}/export?format=${format}`),
};

/** Lien de téléchargement du ZIP d'un export de chapitre terminé. */
export const exportFileUrl = (jobId: number) => engineUrl(`/exports/${jobId}/file`);

export interface BenchScope {
  project_id?: number | null;
  chapter_id?: number | null;
}

function scopeQuery(scope: BenchScope): string {
  const q = new URLSearchParams();
  if (scope.project_id) q.set("project_id", String(scope.project_id));
  if (scope.chapter_id) q.set("chapter_id", String(scope.chapter_id));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function errorMessage(err: unknown): string {
  if (err instanceof EngineError) return err.offline ? "Moteur hors ligne" : err.message;
  return "Erreur inattendue";
}

/** Message complet : détail du moteur + erreurs par champ (ex. « workflow inconnu », « page non mise en page »). */
export function fullErrorMessage(err: unknown): string {
  if (err instanceof EngineError && !err.offline) {
    const fields = Object.values(err.fieldErrors);
    if (fields.length) return fields.map((m) => m.charAt(0).toUpperCase() + m.slice(1)).join(" · ");
  }
  return errorMessage(err);
}
