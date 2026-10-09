// Client de l'API du moteur (via le proxy Next.js /api/engine).

export const ENGINE_BASE = "/api/engine";

export type ReadingDirection = "ltr" | "rtl";

export interface Project {
  id: number;
  title: string;
  style: string;
  reading_direction: ReadingDirection;
  page_format: string;
  workflow_preset: string;
  character_count: number;
  created_at: string;
  updated_at: string;
}

export type ProjectInput = Pick<Project, "title" | "style" | "reading_direction" | "page_format" | "workflow_preset">;

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
  health: () => request<Health>("/health"),
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
};

export function errorMessage(err: unknown): string {
  if (err instanceof EngineError) return err.offline ? "Moteur hors ligne" : err.message;
  return "Erreur inattendue";
}
