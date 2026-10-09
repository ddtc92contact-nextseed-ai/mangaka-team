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
}

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
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
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
  providers: Record<"llm" | "vision" | "comfyui", { name: string | null; ok: boolean; detail: string | null }>;
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
  layout_templates: LayoutTemplate[];
  prompts: string[];
  issues: { file: string; message: string }[];
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
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const fieldErrors: Record<string, string> = {};
    for (const e of data?.errors ?? []) fieldErrors[e.field] = e.message;
    const detail = typeof data?.detail === "string" ? data.detail : `Erreur ${res.status}`;
    throw new EngineError(detail, res.status, fieldErrors, Boolean(data?.offline));
  }
  return data as T;
}

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
};

export function errorMessage(err: unknown): string {
  if (err instanceof EngineError) return err.offline ? "Moteur hors ligne" : err.message;
  return "Erreur inattendue";
}
