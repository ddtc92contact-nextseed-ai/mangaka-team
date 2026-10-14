// Client de l'API du moteur (via le proxy Next.js /api/engine).

export const ENGINE_BASE = "/api/engine";

export type ReadingDirection = "ltr" | "rtl";
export type SeriesStatus = "ongoing" | "paused" | "completed" | "cancelled";
export type ChapterStatus = "draft" | "script" | "layout" | "generation" | "lettering" | "ready" | "published";
export type PageKind = "story" | "bonus" | "chapter_cover";
export type BubbleKind = "speech" | "thought" | "shout" | "narration" | "off";
/** Indices de mise en scène du scénario, lus par la grammaire de mise en page. */
export type Intensity = "calme" | "normal" | "choc";
export type Rythme = "lent" | "normal" | "rapide";

/** Une série (« projet » côté moteur). */
export interface Project {
  id: number;
  title: string;
  /** Dossier de la série dans ComfyUI : mangaka/<slug>/ (tiré du titre, unique). */
  slug: string;
  /** Ancien style en texte libre : lecture seule, ignoré dès qu'un pack est choisi. */
  legacy_style: string;
  /** Packs de style (presets/style_*) ; null : série d'avant les packs, style à choisir. */
  style_genre: string | null;
  style_rendering: string | null;
  style_tone: string | null;
  /** Réglages fins : réglage → choix (trait, trames, détail). */
  style_options: Record<string, string>;
  /** Noms des packs (« Seinen · N&B à trames · Dark »). */
  style_label: string;
  /** `$style` composé pour les prompts image. */
  style_prompt: string;
  status: SeriesStatus;
  reading_direction: ReadingDirection;
  page_format: string;
  workflow_preset: string;
  style_lora_name: string | null;
  style_lora_weight: number;
  /** Mots déclencheurs du LoRA de style, tirés du catalogue presets/style_loras.yaml. */
  style_lora_trigger_words: string[];
  /** Faux : LoRA hors catalogue, appliqué sans mots déclencheurs. */
  style_lora_in_catalog: boolean;
  /** Polices des bulles de parole et des cris (réglages de série du lettreur). */
  dialogue_font: string | null;
  shout_font: string | null;
  /** Style de mise en page de la série (presets/layout_styles/). */
  layout_style: string;
  /** Palier croquis : brouillon de page, tri, passage au propre (désactivable). */
  sketch_enabled: boolean;
  /** Débruitage du passage au propre (null : celui du preset). */
  sketch_denoise: number | null;
  /** Passage au propre : image → image depuis le croquis (défaut) ou ControlNet (composition verrouillée). */
  clean_mode: CleanMode;
  /** Type de contrôle du passage au propre par ControlNet (null : celui du preset). */
  clean_control: string | null;
  /** Agrandisseur de la finition d'impression (presets/upscalers/) ; null = celui de defaults.yaml. */
  upscaler: string | null;
  /** CFG des cases (1 à 3, presets non distillés) ; null = celui du palier. À 1, le prompt négatif n'est pas lu. */
  cfg: number | null;
  /** « Prompt rédigé par l'IA » : le LLM écrit le prompt de chaque case (false : assemblage par fragments). */
  ai_prompt: boolean;
  /** « Cohérence anime » : LoRA d'identité (presets/camera_loras.yaml) ajouté aux générations de la série. */
  anime_consistency: boolean;
  /** Pourquoi la cohérence anime ne s'applique pas au palier de la série (« Disponible en palier Qualité »). */
  anime_consistency_problem: string | null;
  character_count: number;
  chapter_count: number;
  /** Pages déjà mises en page : changer le sens de lecture les met en miroir. */
  laid_out_page_count: number;
  /** Pages avec des cases mais sans aucune image (croquis compris) : « Remettre en page » les recalcule. */
  relayout_page_count: number;
  /** Série restée en « sage » depuis une ancienne mise à jour (pas un choix) : note unique de la fiche série. */
  layout_style_notice: boolean;
  created_at: string;
  updated_at: string;
}

export type ProjectInput = Pick<
  Project,
  | "title"
  | "style_genre"
  | "style_rendering"
  | "style_tone"
  | "style_options"
  | "status"
  | "reading_direction"
  | "page_format"
  | "workflow_preset"
  | "style_lora_name"
  | "style_lora_weight"
  | "dialogue_font"
  | "shout_font"
  | "layout_style"
  | "sketch_enabled"
  | "sketch_denoise"
  | "clean_mode"
  | "clean_control"
  | "upscaler"
  | "cfg"
  | "ai_prompt"
  | "anime_consistency"
>;

export type CleanMode = "img2img" | "controlnet";

/** « Remettre en page les pages non générées » d'une série. */
/** Résultat de « Remettre l'atelier à zéro » (écran Réglages, ou `npm run reset`). */
export interface ResetResult {
  /** Dossier de la sauvegarde écrite avant toute suppression (data/backups/reset-<date-heure>/). */
  backup: string;
  /** Mode « tout » : réglages globaux des agents et savoir-faire remis par défaut. */
  all: boolean;
  series_deleted: number;
  data_removed: string[];
  /** Dossiers effacés dans ComfyUI (output/ et input/ mangaka/, jamais old/). */
  comfyui_removed: string[];
  /** ComfyUI non nettoyé (COMFYUI_DIR absent ou introuvable). */
  comfyui_warning: string | null;
}

/** Résultat de « Nettoyer les variantes non retenues ». */
export interface CleanupResult {
  variants_deleted: number;
  /** Dossiers de transit vidés dans ComfyUI (relatifs au dossier de ComfyUI). */
  comfyui_folders_removed: string[];
  /** Faux : dossier ComfyUI inconnu ou générations en cours (voir `warning`). */
  comfyui_cleaned: boolean;
  warning: string | null;
}

/** Résultat de « Reconstruire la bibliothèque » (copie lisible de la série dans ComfyUI/output/mangaka/). */
export interface LibraryResult {
  /** Faux : dossier ComfyUI inconnu, rien d'écrit (voir `warning`). */
  enabled: boolean;
  /** output/mangaka/<série> (relatif au dossier de ComfyUI). */
  folder: string | null;
  /** Chemin complet sur le disque. */
  path: string | null;
  written: number;
  removed: number;
  warning: string | null;
}

/** Dossiers de ComfyUI gérés par le moteur (COMFYUI_DIR) ; `warning` : rien n'est supprimé hors de data/. */
export interface StorageStatus {
  enabled: boolean;
  path: string | null;
  mock: boolean;
  problem: string | null;
  warning: string | null;
}

export interface RelayoutResult {
  relaid_page_ids: number[];
  /** Pages déjà (en partie) générées : inchangées. */
  kept_pages: number;
}

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

/** Cadrage manuel : centre de la fenêtre (fraction de l'image, 0–1) et zoom sur le remplissage (≥ 1). */
export interface PanelCrop {
  x: number;
  y: number;
  zoom: number;
}

/** Point de vue d'un spectateur : plan de réaction (dessiné) ou vue subjective (hors cadre). */
export interface Viewpoint {
  mode: "reaction" | "subjective";
  spectators: string[];
  /** direction (direction artistique) | défaut (l'agent n'a rien choisi) | auteur (jamais écrasé). */
  source: string;
}

/** Fiche personnage citée par une alerte de nom. */
export interface CardRef {
  id: number;
  name: string;
}

/**
 * Nom de personnage lu dans une case qui demande l'avis de l'auteur (moteur : pipeline/names.py) :
 * ambigu (plusieurs fiches à égalité, la première retenue), sans fiche, ou cité par le texte sans être
 * déclaré (ni présent, ni hors cadre).
 */
export interface NameNote {
  name: string;
  source: "image" | "hors cadre" | "bulle" | "description" | "mise en scène";
  kind: "ambigu" | "sans fiche" | "non déclaré";
  /** Fiche(s) retenue(s) ; vide : aucune. */
  chosen: CardRef[];
  /** Fiches à égalité (nom ambigu). */
  candidates: CardRef[];
  message: string;
}

export interface PanelData {
  id: number;
  index: number;
  description: string;
  /** Lieu de la case (lieu, moment, éléments du décor) — « Lieu : … » du prompt image. */
  setting?: string;
  /** Mise en scène (qui fait quoi, où dans le cadre) — « Mise en scène : … » du prompt image. */
  staging?: string;
  /** Personnages présents à l'image (dessinés, avec leur image de référence). */
  characters: string[];
  /** Noms de `characters` qui ne désignent aucune fiche personnage (à rattacher ou écarter). */
  unmatched_characters?: string[];
  /** Noms ambigus, sans fiche ou cités sans être déclarés : signalés à l'auteur. */
  name_notes?: NameNote[];
  /** Cités par la case mais hors cadre : jamais dessinés ni pourvus d'image de référence. Absent à l'envoi = gardés. */
  offscreen_characters?: string[];
  viewpoint?: Viewpoint | null;
  /** Décor de la bibliothèque de la série (id), null : aucun. */
  decor?: number | null;
  /** Objets de la bibliothèque de la série (ids). */
  objets?: number[];
  shot_type: string | null;
  importance: number;
  intensity: Intensity | null;
  dialogues: Dialogue[];
  /** Onomatopées de la case (lettrage hors bulle). */
  sfx?: PanelSfx[];
  /** Options de cadre imposées à la case (null = décidées par le style de mise en page). */
  frame?: PanelFrame | null;
  /** Cadrage manuel de l'image dans la case (null = centrée au remplissage). */
  crop?: PanelCrop | null;
  /** Zoom maximal du cadrage permis par l'image montrée (null = aucune image à cadrer). */
  crop_max_zoom?: number | null;
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
  /** Le ratio de la case s'écarte trop de celui de l'image retenue : régénération conseillée. */
  regeneration_advised: boolean;
  /** Palier croquis : nombre de croquis, croquis montré (validé, sinon le plus récent). */
  sketch_count?: number;
  sketch_image_id?: number | null;
  sketch_image_url?: string | null;
  /** Composition retenue au tri. */
  sketch_validated?: boolean;
  /** Débruitage du passage au propre imposé à la case (null : celui de la série). */
  sketch_denoise?: number | null;
  /** Une version propre a déjà été tirée du croquis validé. */
  sketch_cleaned?: boolean;
  /** Composition verrouillée (ControlNet) : type de contrôle du verrou, null = composition libre. */
  composition_lock?: string | null;
  /** Dpi de la version retenue à l'impression (null : pas de version retenue ou pas de mise en page). */
  print_info?: PrintInfo | null;
  /** Dernière génération de la case (la plus récente, sans limite d'historique). */
  last_job_id: number | null;
  last_job_status: JobStatus | null;
  last_job_error: string | null;
}

/** Finition d'impression : dpi effectif de la version retenue une fois imprimée. */
export interface PrintInfo {
  image_id: number;
  /** ok : déjà au dpi cible · finished : finalisée au dpi cible · low : sous le seuil. */
  status: "ok" | "finished" | "low";
  target_dpi: number;
  min_dpi: number;
  box_width: number;
  box_height: number;
  width_mm: number;
  height_mm: number;
  source_width: number;
  source_height: number;
  dpi: number;
  factor: number;
  target_width: number;
  target_height: number;
  needed: boolean;
  finished: boolean;
  finished_dpi: number | null;
  finished_width: number | null;
  finished_height: number | null;
  finished_upscaler: string | null;
}

/** Agrandisseur de la finition d'impression (presets/upscalers/). */
export interface Upscaler {
  id: string;
  name: string;
  description: string;
  model_scale: number | null;
  high_fidelity: boolean;
  is_default: boolean;
  estimated_s: number | null;
  timeout_s: number;
}

/** Image agrandie dérivée d'une version (finition d'impression). */
export interface PanelImageFinish {
  path: string;
  width: number;
  height: number;
  upscaler: string;
  upscaler_name: string;
  factor: number;
  dpi: number;
  target_dpi: number;
  created_at: string;
  [key: string]: unknown;
}

export interface PanelSfx {
  id: number;
  text: string;
  intensity: Intensity | null;
}

export type FrameKind = "border" | "none" | "fade";

/** Options de cadre d'une case : null = décidée par le style. */
export interface PanelFrame {
  frame: FrameKind | null;
  /** Déborder sur les cases voisines (jamais sur la marge de la page). */
  break_out: boolean | null;
  inset: boolean | null;
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
  /** Tonalité « papier blanc » (couche détecteurs) : parts de pixels sombres et de noir pur. */
  tone?: QCTone;
  attempts?: number;
  why?: string;
}

/** Tonalité d'une case (numpy) : parts 0-1, seuils du preset, ou pourquoi elle n'est pas vérifiée. */
export interface QCTone {
  checked: boolean;
  dark: number | null;
  black: number | null;
  max_dark: number | null;
  max_black: number | null;
  too_dark: boolean;
  message: string | null;
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
  /** Polygone de la case (px de la page) ; absent dans une mise en page d'avant les biais. */
  polygon?: [number, number][];
  slanted?: boolean;
  /** Options de cadre effectives (absentes dans une mise en page d'avant). */
  frame?: FrameKind;
  /** La case déborde sur ses voisines (dessinée par-dessus), toujours dans la zone utile. */
  break_out?: boolean;
  inset?: boolean;
  host_index?: number | null;
  /** Débordement : la case d'origine (où restent les bulles). */
  base_polygon?: [number, number][];
}

export interface LayoutGutter extends Rect {
  path: number[];
  index: number;
  orientation: "horizontal" | "vertical";
  position: number;
  min: number;
  max: number;
  /** Ligne médiane de la découpe : extrémité « début » puis « fin ». */
  line?: [[number, number], [number, number]];
  /** Extrémités visibles de la découpe (poignées d'inclinaison). */
  handles?: [[number, number], [number, number]];
  /** Positions des deux extrémités le long de l'axe découpé, et leurs bornes. */
  ends?: [number, number];
  ends_min?: [number, number];
  ends_max?: [number, number];
  slant_mm?: [number, number];
  angle_deg?: number;
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
  style?: {
    id: string;
    seed: number;
    rythme: Rythme | null;
    gutters_mm: { horizontal: number; vertical: number } | null;
    /** Page choc décidée par la direction artistique. */
    page_choc?: boolean;
  };
}

export interface PageData {
  id: number;
  chapter_id: number;
  number: number;
  kind: PageKind;
  grid_template: string | null;
  /** Style imposé à la page (null = celui de la série). */
  layout_style: string | null;
  layout_seed: number | null;
  rythme: Rythme | null;
  state: string;
  layout: PageLayout | null;
  layout_stale: boolean;
  panels: PanelData[];
}

/** Découpage envoyé au moteur : `id` absent = nouvel élément. */
export interface PanelInput {
  id?: number;
  description: string;
  /** Absent : gardé tel quel. */
  setting?: string;
  staging?: string;
  characters: string[];
  /** Absent : décor gardé ; null : aucun décor. */
  decor?: number | null;
  /** Absent : objets gardés. */
  objets?: number[];
  shot_type: string | null;
  importance: number;
  intensity?: Intensity | null;
  dialogues: Dialogue[];
}

export interface PageInput {
  id?: number;
  kind: PageKind;
  rythme?: Rythme | null;
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
export type ImageKind = "final" | "croquis";

export interface PanelImage {
  id: number;
  panel_id: number;
  version: number;
  /** croquis : brouillon de composition, jamais choisi, assemblé ni exporté. */
  kind?: ImageKind;
  url: string;
  seed: Seed | null;
  selected: boolean;
  width: number | null;
  height: number | null;
  preset: string | null;
  /** Palier du preset qui a produit la version (Turbo, Rapide, Qualité). */
  tier: string | null;
  params: {
    prompt?: string;
    negative_prompt?: string;
    duration_ms?: number;
    loras?: unknown[];
    /** Emplacements de référence remplis (personnages, puis décor, puis objets). */
    reference_images?: UsedReference[];
    /** Fiches qui avaient une image mais n'ont pas eu d'emplacement (priorité : personnages d'abord). */
    dropped_references?: DroppedReference[];
    /** Réparation ciblée : version source et réglages (absent pour une génération). */
    repair?: RepairParams;
    /** CFG appliqué ; à 1 (ou modèle distillé), le prompt négatif n'a pas été lu (`negative_active` faux). */
    cfg?: number | null;
    negative_active?: boolean;
    [key: string]: unknown;
  };
  qc_score: number | null;
  qc_reasons: string[];
  qc_verdict: QCVerdict | null;
  qc: QCDetails;
  detections: Detections | null;
  /** Jugement humain bonne / mauvaise (banc d'essai du QC), indépendant du verdict QC. */
  annotation: Annotation | null;
  /** Finition d'impression de la version (image agrandie), null : aucune. */
  finish?: PanelImageFinish | null;
  created_at: string;
}

export type RepairTarget = "face" | "hand" | "zone";

/** Rectangle à repeindre, en px de l'image de la version. */
export interface RepairRegion {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** Lien d'une version réparée vers sa source (`params.repair`). */
export interface RepairParams {
  source_image_id: number;
  source_version: number;
  target: RepairTarget;
  character_id: number | null;
  character_name: string | null;
  regions: RepairRegion[];
  painted: boolean;
  grow_px: number;
  feather_px: number;
  denoise: number;
}

/** Préremplissage de « Réparer » : preset du palier, réglages par défaut, prompt, personnages. */
export interface RepairInfo {
  available: boolean;
  problem: string | null;
  preset: string | null;
  preset_name: string | null;
  tier: string | null;
  grow_px: number;
  feather_px: number;
  denoise: number;
  target: RepairTarget;
  character_id: number | null;
  characters: { id: number; name: string }[];
  prompt: string;
}

export interface RepairInput {
  regions: RepairRegion[];
  /** Masque peint : PNG en data URL (opaque = à repeindre). */
  mask_png?: string | null;
  target: RepairTarget;
  character_id: number | null;
  prompt: string;
  grow_px: number;
  feather_px: number;
  denoise: number;
}

/** Image de référence envoyée dans un emplacement du workflow. */
export interface UsedReference {
  slot?: number;
  /** Absent sur les versions d'avant la bibliothèque (personnage). */
  kind?: LibraryKind | "style" | "panel";
  id?: number;
  name?: string;
  character_id?: number;
  image_id: number;
  /** Vue étiquetée par son angle de caméra (choisie pour l'angle de la case). */
  angle?: string;
  comfyui_name?: string;
}

/** Fiche écartée faute d'emplacement de référence. */
export interface DroppedReference {
  kind?: LibraryKind | "style";
  id?: number;
  name?: string;
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
  setting: string;
  staging: string;
  /** Personnages présents à l'image. */
  characters: string[];
  character_ids: number[];
  /** Noms sans fiche personnage : ni références, ni description, ni LoRA à la génération. */
  unmatched_characters: string[];
  /** Noms ambigus, sans fiche ou cités sans être déclarés : signalés à l'auteur. */
  name_notes?: NameNote[];
  /** Cités par la case mais hors cadre : ni dessinés, ni image de référence. */
  offscreen_characters?: string[];
  viewpoint?: Viewpoint | null;
  /** Personnages que le texte met en spectateur (« voient », « regarde »…) : la case attend un point de vue. */
  spectator_hints?: string[];
  /** Verbe de perception repéré dans le texte (« voient »). */
  perception?: string;
  decor: LibraryRef | null;
  objets: LibraryRef[];
  shot_type: string | null;
  /** Cadrage suivi par la génération (prompt, savoir-faire, vue de référence) et sa source ; « scenario » : repli
   * sur le plan du scénario faute de direction artistique appliquée (`framing_note` dit pourquoi). */
  framing_plan?: string | null;
  framing_angle?: string | null;
  framing_source?: "direction" | "dialogue" | "scenario" | "none";
  framing_note?: string | null;
  state: PanelState;
  bbox: Rect | null;
  final_prompt: string | null;
  final_prompt_manual: boolean;
  /** Ce que le dialogue avec l'IA impose à la case (« Plan : gros plan »…), jusqu'à « Reconstruire le prompt ». */
  dialog_overrides?: string[];
  /** Origine du prompt automatique : rédigé par l'IA ou assemblé par fragments (null : jamais construit). */
  prompt_source?: "ia" | "fragments" | null;
  /** La série fait rédiger ses prompts par l'IA. */
  ai_prompt?: boolean;
  /** Sera rédigé par l'IA à la prochaine génération (ou « Reconstruire le prompt »). */
  prompt_pending?: boolean;
  /** Rédaction en échec : prompt par fragments utilisé (message lisible). */
  prompt_warning?: string | null;
  /** « Sources utilisées » du prompt actuel : savoir-faire reçu par le rédacteur, date de la rédaction. */
  prompt_sources?: PromptSources | null;
  generation_preset: string | null;
  resolved_preset: string | null;
  target: { width: number; height: number } | null;
  images: PanelImage[];
  active_jobs: Job[];
  /** Croquis validé au tri (null : aucun). */
  sketch_image_id?: number | null;
  sketch_denoise?: number | null;
  print_info?: PrintInfo | null;
  /** Nom de l'agrandisseur de la série (finition d'impression), null : aucun configuré. */
  upscaler?: string | null;
  /** Composition verrouillée (ControlNet) ; null : composition libre. */
  composition_lock?: CompositionLock | null;
}

/** Un champ changé par une proposition du dialogue (plan, angle, action, ambiance, référence d'un personnage). */
export interface DialogChange {
  field: string;
  label: string;
  before: string | null;
  after: string | null;
}

/** Un échange du dialogue avec l'IA sur une case : consigne, proposition, sort de la proposition. */
export interface PanelDialogTurn {
  id: number;
  panel_id: number;
  instruction: string;
  explanation: string;
  status: "proposed" | "applied" | "cancelled";
  prompt_before: string | null;
  prompt_after: string;
  changes: DialogChange[];
  created_at: string;
  applied_at: string | null;
}

export interface DialogApplyResult {
  turn: PanelDialogTurn;
  panel: PanelDetail;
  jobs: Job[];
}

export type CompositionSource = "croquis" | "version" | "import";

/** Verrou de composition d'une case : image guide, type de contrôle, force, aperçu de la carte. */
export interface CompositionLock {
  source: CompositionSource;
  /** « croquis v2 », « version 3 », « image importée ». */
  source_label: string;
  image_id: number | null;
  version: number | null;
  source_url: string;
  type: string;
  type_name: string;
  strength: number;
  locked_at: string | null;
  /** Preset ControlNet des prochaines générations. */
  preset: string | null;
  preset_name: string | null;
  /** Le palier de la case ne propose pas de ControlNet… */
  problem: string | null;
  preview: {
    status: "none" | "pending" | "running" | "ready" | "failed" | "cancelled";
    /** Dernière carte calculée (celle d'un type précédent pendant un nouveau calcul). */
    url: string | null;
    /** Type de la carte affichée (celui du verrou une fois le recalcul terminé). */
    type: string | null;
    type_name: string | null;
    job_id: number | null;
    error: string | null;
    width: number | null;
    height: number | null;
  };
}

/** `GET /comfyui/control` : le verrouillage de composition est-il utilisable dans ComfyUI ? */
export interface ControlStatus {
  available: boolean;
  /** Message en français quand le verrouillage est indisponible (nœud ou fichier du patch absent…). */
  message: string | null;
  problems: string[];
  default_type: string | null;
  default_strength: number | null;
  types: ControlTypeInfo[];
  simulated?: boolean;
  error?: string | null;
}

export interface ControlTypeInfo {
  id: string;
  name: string;
  description: string;
  preprocessor: string | null;
  available: boolean;
  problem: string | null;
}

export interface GenerateInput {
  count?: number;
  seed?: Seed | null;
  preset?: string | null;
  prompt_override?: string | null;
}

/** « Générer le chapitre » : croquis d'abord (palier croquis de la série) ou versions finales. */
export type ProductionMode = "sketch" | "final";

export interface ChapterProductionPlan {
  mode: ProductionMode;
  /** Cases à croquer (sketch) ou à générer (final). */
  panels: number;
  /** Croquis validés à passer au propre (sketch). */
  to_clean: number;
  pages: number;
  /** Numéros des pages sans mise en page : calculée juste avant la génération. */
  unlaid_pages: number[];
  total: number;
}

export interface ChapterProductionResult {
  mode: ProductionMode;
  jobs: Job[];
  panel_ids: number[];
  cleaned_panel_ids: number[];
  laid_out_pages: number[];
  skipped: number;
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
  /** Palier du preset (« Turbo », « Rapide », « Qualité »). */
  tier?: string | null;
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
  /** Workflow du même palier utilisé pour les cases avec images de référence. */
  with_references: string | null;
  has_trial: boolean;
  tier: string | null;
  tier_choice: string | null;
  tier_order: number | null;
  estimated_s: number | null;
  /** Palier de « Régénérer en Qualité ». */
  is_quality: boolean;
  /** generation : palier de série ; croquis ; propre : version finale depuis un croquis validé ;
   * controle : composition verrouillée (ControlNet). */
  role?: "generation" | "croquis" | "propre" | "controle";
  from_sketch?: string | null;
  /** Workflow ControlNet (composition verrouillée) du même palier. */
  with_control?: string | null;
  is_sketch?: boolean;
  steps?: number | null;
  /** CFG par défaut ; modèle distillé (Turbo) : toujours 1. */
  cfg?: number;
  distilled?: boolean;
  /** cfg > 1 : le prompt négatif est lu par le modèle. */
  negative_active?: boolean;
}

/** Temps estimés du palier croquis d'une page ou d'un chapitre. */
export interface SketchEstimate {
  panels: number;
  /** Cases encore à croquer (sans version propre choisie ni croquis validé). */
  to_sketch: number;
  validated: number;
  /** Cases validées sans version propre tirée de leur croquis. */
  to_clean: number;
  sketch: Estimate;
  clean: Estimate;
}

/** Temps estimé des cases encore à générer (chapitre ou série). */
export interface Estimate {
  remaining_panels: number;
  /** null : un preset sans durée connue ni estimation. */
  total_s: number | null;
  /** false : au moins une partie vient des estimations des presets, pas de vraies durées. */
  measured: boolean;
  by_preset: {
    preset: string;
    tier: string | null;
    panels: number;
    per_panel_s: number | null;
    measured: boolean;
    samples: number;
  }[];
}

/** Rapport de `GET /comfyui/check` : nœuds et fichiers des presets face au ComfyUI réel. */
export interface ComfyCheck {
  provider: string;
  simulated: boolean;
  url: string | null;
  online: boolean;
  error: string | null;
  ok: boolean;
  system: {
    comfyui_version: string | null;
    pytorch_version: string | null;
    ram_total: number | null;
    ram_free: number | null;
    devices: { name: string; type: string; vram_total: number | null; vram_free: number | null }[];
  } | null;
  /** `optional` : preset ControlNet (son absence masque seulement le verrouillage de composition). */
  presets: { id: string; name: string; ok: boolean; problems: string[]; optional?: boolean }[];
  loras: { checked: number; problems: string[] };
  /** Verrouillage de composition (ControlNet) : null si ComfyUI n'a pas pu être interrogé. */
  control?: ControlStatus | null;
}

/** `GET /comfyui/loras` : LoRA que ComfyUI accepte (sous-dossiers de models/loras compris). */
export interface LoraCatalog {
  provider: string;
  /** false : ComfyUI hors ligne ou liste illisible (`error` dit pourquoi). */
  available: boolean;
  /** ComfyUI factice : petite liste d'exemple. */
  simulated: boolean;
  error: string | null;
  loader: string | null;
  loras: { name: string; folder: string; file: string }[];
}

export interface LayoutTemplate {
  id: string;
  name: string;
  panel_count: number;
}

export interface LayoutStyle {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
}

/** Packs de style (listes fermées de la fiche série). */
export interface StyleGenre {
  id: string;
  name: string;
  description: string;
  /** Style de mise en page suggéré (jamais « sage ») ; null : celui des nouvelles séries. */
  layout_style: string | null;
  reading_direction: ReadingDirection;
  fonts: { dialogue: string; shout: string };
  /** null : tous les tons. */
  allowed_tones: string[] | null;
  style_lora: string | null;
}

export interface StyleRendering {
  id: string;
  name: string;
  description: string;
  monochrome: boolean;
  is_default: boolean;
}

export interface StyleTone {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
}

export interface StyleOption {
  id: string;
  name: string;
  description: string;
  /** Réservé aux rendus noir et blanc (trames). */
  monochrome_only: boolean;
  choices: { id: string; name: string }[];
}

export interface StyleLora {
  file: string;
  name: string;
  trigger_words: string[];
  weight: number;
}

export interface ReferenceImage {
  id: number;
  url: string;
  original_name: string;
  content_type: string;
  width: number;
  height: number;
  created_at: string;
  /** Angle de caméra de la vue (id de presets/camera_loras.yaml) ; null = non étiquetée. */
  angle?: string | null;
}

/** LoRA de caméra ou d'identité (presets/camera_loras.yaml). */
export interface CameraLora {
  id: string;
  role: "angles" | "identity";
  name: string;
  description: string;
  file: string;
  trigger: string;
  weight: number;
  tiers: string[];
  default: boolean;
  /** Workflows (paliers) où ce LoRA est ajouté ; ailleurs : « Disponible en palier Qualité ». */
  workflows: string[];
}

export interface CameraAngle {
  id: string;
  label: string;
  camera: string;
  azimuth: number;
  elevation: number;
}

/** « Nouvel angle » (fiches) et « Changer l'angle » (cases) : LoRA, vocabulaire de caméra, palier. */
export interface CameraLoras {
  workflow: string | null;
  workflow_tier: string | null;
  /** null : disponible ; sinon pourquoi (palier non testé, LoRA absent…). */
  angle_problem: string | null;
  loras: CameraLora[];
  angles: CameraAngle[];
  main_view: string | null;
  weight_hint: string;
  tier_label: string;
}

/** Réglages d'une génération d'angle. */
export interface AngleInput {
  angle: string;
  lora?: string | null;
  weight?: number | null;
  seed?: Seed | null;
}

export interface Character {
  id: number;
  project_id: number;
  name: string;
  /** Dossier de la fiche dans ComfyUI : mangaka/<série>/personnages|objets|decors/<slug>/. */
  slug?: string;
  visual_description: string;
  prompt_keywords: string[];
  lora_name: string | null;
  lora_weight: number;
  /** Mots déclencheurs du LoRA de la fiche, ajoutés au prompt quand il est appliqué. */
  lora_trigger_words: string;
  reference_images: ReferenceImage[];
  created_at: string;
  updated_at: string;
  /** Autres noms reconnus par le scénario (personnages seulement). */
  aliases?: string[];
}

/** Rattachement d'un nom écrit par le scénario à une fiche (`character_id` null : foule anonyme marquée
 * « foule sans fiche » ; refusé pour un intervenant nommé). */
export interface CharacterLink {
  name: string;
  character_id: number | null;
  panels: number;
  alias_added: boolean;
}

/** Distribution du chapitre (moteur : pipeline/cast.py) : chaque intervenant cité, même secondaire. */
export type CastReferences = "aucune" | "portrait" | "planche";
export type CastRole = "principal" | "secondaire";

export interface CastAppearance {
  panel_id: number;
  page_number: number;
  /** 0-based. */
  panel_index: number;
  /** « case 2 de la page 3 ». */
  label: string;
  /** image | hors cadre | bulle | description | mise en scène */
  sources: string[];
}

export interface CrowdMark {
  id: number;
  name: string;
  author: string;
  at: string;
}

export interface CastMember {
  key: string;
  name: string;
  character_id: number | null;
  /** Noms tels qu'écrits par le scénario. */
  written: string[];
  appearances: CastAppearance[];
  panel_count: number;
  images: number;
  references: CastReferences;
  role: CastRole;
  /** Références conseillées : portrait (secondaire) ou planche (principal). */
  needs: "portrait" | "planche";
  /** Foule anonyme : peut être marquée « foule sans fiche ». */
  crowd: boolean;
  mark: CrowdMark | null;
  /** Ce qui bloque la génération. */
  fault: "sans fiche" | "sans image" | null;
  /** Conseil non bloquant (« planche conseillée… »). */
  advice: string | null;
}

export interface ChapterCast {
  chapter_id: number;
  project_id: number;
  members: CastMember[];
  /** Intervenants comptés par la garde (foules marquées exclues). */
  total: number;
  faults: number;
  without_card: string[];
  without_image: string[];
  marks: CrowdMark[];
}

/** Fiche préremplie par le LLM (rien n'est enregistré avant « Créer la fiche »). */
export interface CharacterDraft {
  name: string;
  written: string;
  visual_description: string;
  prompt_keywords: string[];
  age: string;
  silhouette: string;
  tenue: string;
  signe_distinctif: string;
  panel_count: number;
}

export interface CastBatch {
  items: { name: string; character_id: number | null; created: boolean; queued: boolean; message: string }[];
  jobs: Job[];
  cast: ChapterCast;
}

/** Sortes de fiches de la bibliothèque d'une série. */
export type LibraryKind = "character" | "object" | "decor";

/** Objet ou décor récurrent : mêmes champs qu'un personnage. */
export interface SeriesAsset extends Character {
  kind: "object" | "decor";
}

/** Fiche de la bibliothèque (personnage, objet ou décor). */
export type LibraryEntry = Character | SeriesAsset;
export type LibraryEntryInput = Pick<
  Character,
  "name" | "visual_description" | "prompt_keywords" | "lora_name" | "lora_weight" | "lora_trigger_words"
> & { aliases?: string[] };

/** Élément de la bibliothèque cité par une case. */
export interface LibraryRef {
  id: number;
  kind: LibraryKind;
  name: string;
}

/** Type de fiche de référence (presets/reference_sheets/) : portrait, turnaround, plan large… */
export interface ReferenceSheet {
  id: string;
  name: string;
  description: string;
  kinds: LibraryKind[];
  width: number;
  height: number;
  /** null : palier de la série (ou Qualité). */
  workflow: string | null;
}

/** Image générée par « Créer des références », gardée ou non. */
export interface ReferenceVariant {
  id: number;
  entry_kind: LibraryKind;
  entry_id: number;
  url: string;
  sheet: string;
  sheet_name: string;
  preset: string | null;
  tier: string | null;
  seed: Seed | null;
  width: number;
  height: number;
  prompt: string;
  instruction: string;
  /** Variante de départ d'un « Affiner ». */
  parent_id: number | null;
  kept: boolean;
  kept_image_id: number | null;
  job_id: number | null;
  /** Fiche d'objet ou de décor : personnage détecté par le QC (null : aucun) ; acceptée à la main ou non. */
  people_warning?: string | null;
  people_accepted?: boolean;
  params: Record<string, unknown>;
  created_at: string;
}

export interface ReferenceStudio {
  /** Plus récentes d'abord. */
  variants: ReferenceVariant[];
  active_jobs: Job[];
  max_kept: number;
  kept_count: number;
  /** Emplacements d'images de référence d'une case de la série. */
  reference_slots: number;
}

/** Essai de la planche de style (palier croquis). */
export interface StyleTrial {
  id: number;
  url: string;
  /** Numéro de la série d'essais (« Relancer » en crée une nouvelle). */
  batch: number | null;
  variant: number | null;
  count: number | null;
  seed: Seed | null;
  width: number;
  height: number;
  prompt: string;
  preset: string | null;
  /** Passé au propre : devenu une référence de style. */
  chosen: boolean;
  created_at: string;
}

/** Référence de style de la série (essai retenu passé au propre). */
export interface StyleReference {
  id: number;
  name: string;
  url: string;
  width: number;
  height: number;
  active: boolean;
  /** `$style` de la série au moment des essais. */
  style: string;
  /** Le style de la série a changé depuis. */
  outdated: boolean;
  trial_id: number | null;
  created_at: string;
}

export interface StyleBoard {
  configured: boolean;
  /** Pourquoi les essais sont impossibles (genre non choisi…), sinon null. */
  problem: string | null;
  scene_test: string | null;
  style: string;
  style_names: string;
  trials_per_batch: number;
  use_reference_sheets: "with_subject" | "always" | "never" | null;
  /** Sortes de fiches qui reçoivent la référence de style (jamais objets ni décors avec les presets livrés). */
  reference_sheet_kinds?: LibraryKind[];
  use_panels: "with_subject" | "free_slot" | "never" | null;
  active: StyleReference | null;
  history: StyleReference[];
  /** Plus récents d'abord. */
  trials: StyleTrial[];
  active_jobs: Job[];
}

// --- Identité visuelle de la série (palette, logo du titre) -------------------------------------
export interface PaletteColor {
  /** Rôle (presets/identity.yaml) : dominante, accent, fond, texte-clair, texte-sombre… */
  role: string;
  /** « #rrggbb ». */
  hex: string;
}

export interface Palette {
  name: string;
  explanation: string;
  colors: PaletteColor[];
}

export type LogoColorSlot = "fill" | "fill_end" | "outline" | "outer" | "shadow" | "subtitle";

/** Réglages complets d'un logo du titre (concept de l'IA ou logo enregistré). */
export interface LogoSpec {
  name: string;
  explanation: string;
  font: string;
  style: string;
  /** Une ou deux lignes ; `scale` : taille relative (1 = ligne mise en avant). */
  lines: { text: string; scale: number }[];
  subtitle: string | null;
  /** Inclinaison en degrés (positif : penche vers la droite). */
  slant: number;
  /** Interlettrage, en em. */
  letter_spacing: number;
  /** Épaisseur des contours, relative à l'effet. */
  outline_scale: number;
  colors: Record<LogoColorSlot, string | null> & { fill: string };
}

export interface RenderedLogo {
  spec: LogoSpec;
  /** SVG autonome (police embarquée). */
  svg: string;
  /** Plus faible contraste texte / contour (null : pas de contour). */
  contrast: number | null;
  contrast_ok: boolean;
  /** Corrections faites par le moteur (contour trop peu contrasté…). */
  notes: string[];
}

export interface LogoVersion extends RenderedLogo {
  id: number;
  version: number;
  created_at: string;
  svg_url: string;
  png_url: string;
}

export interface Bounds {
  min: number;
  max: number;
}

export interface SeriesIdentity {
  palette: Palette | null;
  palette_proposals: Palette[];
  /** Logo de la série : sa dernière version. */
  logo: LogoVersion | null;
  /** Plus récentes d'abord. */
  logo_versions: LogoVersion[];
  logo_proposals: RenderedLogo[];
  roles: Record<string, string>;
  required_roles: string[];
  palette_colors: Bounds;
  fonts: { id: string; name: string }[];
  styles: { id: string; name: string; description: string; slots: LogoColorSlot[] }[];
  limits: {
    max_lines: number;
    slant_max_deg: number;
    letter_spacing: Bounds;
    word_scale: Bounds;
    outline_scale: Bounds;
    min_contrast: number;
    backgrounds: Record<string, string>;
  };
}

export interface LogoPreview {
  svg: string;
  contrast: number | null;
  contrast_ok: boolean;
  problems: string[];
}

export interface ReferenceGenerateInput {
  sheet: string;
  count?: number;
  quality?: boolean;
  /** Image de départ : une image de référence de la fiche ; absente = à partir de la description seule. */
  start_image_id?: number | null;
}

export interface ReferenceRefineInput {
  instruction: string;
  count?: number;
  quality?: boolean;
}

/** Segment d'URL du moteur pour chaque sorte. */
const LIBRARY_SEGMENT: Record<LibraryKind, string> = {
  character: "characters",
  object: "objects",
  decor: "decors",
};

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
    "llm" | "vision" | "comfyui" | "detectors" | "identity" | "embedding",
    { name: string | null; ok: boolean; detail: string | null }
  >;
  /** Fournisseurs actifs (badge de l'en-tête) ; absent d'un moteur plus ancien. */
  active?: ActiveProviders;
  /** Dossiers de ComfyUI (rangement, nettoyage) ; absent d'un moteur plus ancien. */
  storage?: StorageStatus;
  mock: boolean;
  presets: { page_formats: number; workflows: number; issues: number };
}

/** Un fournisseur actif : nom, mode simulé et variable `.env` qui le choisit (jamais la clé). */
export interface ActiveProvider {
  name: string;
  label: string;
  mock: boolean;
  ok: boolean;
  detail: string | null;
  env: string;
  key_env: string | null;
  key_set: boolean | null;
  url?: string;
}

export type ActiveProviders = Record<"llm" | "vision" | "comfyui", ActiveProvider>;

export interface Presets {
  /** « Prompt rédigé par l'IA » des nouvelles séries (réglage global du dessinateur). */
  ai_prompt_default?: boolean;
  defaults: {
    page_format: string;
    workflow: string;
    workflow_with_references?: string | null;
    workflow_quality?: string | null;
    layout_style?: string | null;
    sketch_enabled?: boolean;
    workflow_sketch?: string | null;
    /** Agrandisseur de la finition d'impression et part du dpi cible qui suffit (0,9). */
    upscaler?: string | null;
    finishing_tolerance?: number;
  } | null;
  page_formats: {
    id: string;
    name: string;
    width_mm: number;
    height_mm: number;
    dpi: number;
    width_px: number;
    height_px: number;
  }[];
  workflows: {
    id: string;
    name: string;
    description: string;
    params: string[];
    reference_slots: number;
    with_references: string | null;
    has_trial: boolean;
    tier: string | null;
    /** Libellé du palier dans la fiche série (null : pas proposé comme palier). */
    tier_choice: string | null;
    tier_order: number | null;
    estimated_s: number | null;
    role?: "generation" | "croquis" | "propre" | "controle";
    /** Workflow « propre depuis croquis » du même palier. */
    from_sketch?: string | null;
    /** Débruitage livré (workflows « propre »). */
    denoise?: number | null;
    steps?: number | null;
    /** CFG par défaut du palier ; à 1, le prompt négatif n'est pas lu (« négatif inactif »). */
    cfg?: number;
    /** Modèle distillé (Turbo, croquis) : cfg 1 imposé. */
    distilled?: boolean;
    negative_active?: boolean;
  }[];
  /** Agrandisseurs de la finition d'impression (presets/upscalers/). */
  upscalers?: Omit<Upscaler, "timeout_s">[];
  fonts: { id: string; name: string; bold: boolean; italic: boolean }[];
  layout_templates: LayoutTemplate[];
  layout_styles: LayoutStyle[];
  style_genres: StyleGenre[];
  style_renderings: StyleRendering[];
  style_tones: StyleTone[];
  style_options: StyleOption[];
  style_loras: StyleLora[];
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
  // min / max : bornes du style ; un cadre ajusté à la main est rempli entre les deux, sauf taille saisie
  // à la main (`manual_size`). style_size_pt / margin_px : taille normale du style et marges de la bulle à
  // cette taille (le remplissage les fait grandir avec le texte) — pour l'aperçu du redimensionnement.
  font: {
    family: string;
    size_pt: number;
    size_px: number;
    color: string;
    min_size_pt: number;
    max_size_pt: number;
    manual_size: boolean;
    style_size_pt: number;
    margin_px: { w: number; h: number };
  };
  lines: { text: string; x: number; y: number }[];
  // miter_limit : joints en onglet (pointes vives des queues et des cris), jamais biseautés.
  shape: { path: string; fill: string; stroke: string; stroke_px: number; miter_limit: number };
}

/** Aperçu du redimensionnement d'une bulle : son texte dans le cadre `box`, calculé comme au lâcher. */
export interface BubbleFit {
  id: number;
  box: BubbleBox;
  size_pt: number;
  size_px: number;
  overflow: boolean;
  lines: { text: string; x: number; y: number }[];
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
  /** Zone utile de la page : rien n'est dessiné au-delà. */
  live_area?: { x1: number; y1: number; x2: number; y2: number } | null;
  layout_stale: boolean;
  styles: Record<BubbleKind, { family: string; name: string; url: string; size_pt: number }>;
  /** Polices proposées pour les onomatopées. */
  sfx_fonts?: Record<string, { family: string; name: string; url: string }>;
  sfx_settings?: { max_overflow_mm: number | null };
  panels: {
    id: number;
    index: number;
    /** Cadre de la case dans la zone utile (où se posent bulles et onomatopées). */
    box: Rect;
    /** Polygone de la case quand elle est en biais ou déborde sur ses voisines (null = son cadre). */
    polygon?: [number, number][] | null;
    frame?: FrameKind;
    inset?: boolean;
    break_out?: boolean;
    bubble_zone: Rect | null;
    image_url: string | null;
    /** Sorte de l'image montrée : version propre, ou croquis à défaut (aperçu seulement, jamais exporté). */
    image_kind?: "final" | "croquis" | null;
    /** Où l'image entière tombe sur la page une fois cadrée (la case n'en montre que la fenêtre). */
    image_rect?: Rect | null;
    faces: Rect[];
  }[];
  bubbles: LetteredBubble[];
  sfx?: LetteredSfx[];
  warnings: LetteringWarning[];
}

/** Onomatopée calculée : lignes dans le repère local (centre = origine), `transform` SVG vers la page. */
export interface LetteredSfx {
  id: number;
  panel_id: number;
  kind: "sfx";
  text: string;
  intensity: Intensity;
  font: { id: string; family: string; size_pt: number; size_px: number };
  center: { x: number; y: number };
  angle: number;
  skew: number;
  half: { w: number; h: number };
  quad: [number, number][];
  lines: { text: string; x: number; y: number }[];
  paint: { fill: string; outline: string; outline_px: number; halo: string; halo_px: number };
  transform: string;
  manual: boolean;
  manual_size: boolean;
  manual_angle: boolean;
  manual_skew: boolean;
  overflow_px: number;
}

/** Réglages d'une onomatopée ; null = calcul automatique. */
export interface SfxUpdate {
  intensity?: Intensity | null;
  font?: string | null;
  size_pt?: number | null;
  angle?: number | null;
  skew?: number | null;
  x?: number | null;
  y?: number | null;
}

export interface BubbleUpdate {
  text?: string;
  kind?: BubbleKind;
  speaker?: string;
  position?: BubbleBox | null;
  tail?: { x: number; y: number } | null;
  /** Taille du texte saisie à la main (pt) ; null = automatique. */
  size_pt?: number | null;
  sfx?: SfxUpdate | null;
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

// --- L'équipe : agents du pipeline -------------------------------------------------------

export type AgentState = "ready" | "down" | "misconfigured";
export type SettingOrigin = "preset" | "global" | "series";
export type AgentSettingType =
  | "text"
  | "longtext"
  | "prompt"
  | "prompt_list"
  | "number"
  | "integer"
  | "boolean"
  | "choice"
  | "list"
  | "yaml";

export interface AgentRun {
  job_id: number;
  status: JobStatus;
  finished_at: string | null;
  duration_ms: number | null;
  message: string;
  error: string | null;
  project_id: number | null;
}

export interface AgentSummary {
  id: string;
  name: string;
  icon: string;
  role: string;
  step: number;
  step_label: string;
  /** Modèle / fournisseur utilisé (profil global). */
  model: string;
  status: { state: AgentState; label: string; detail: string | null };
  last_run: AgentRun | null;
  version: number;
  series_overrides: number;
}

export interface AgentSetting {
  key: string;
  label: string;
  help: string;
  group: string;
  type: AgentSettingType;
  choices: { value: string; label: string }[];
  nullable: boolean;
  variables: string[];
  min: number | null;
  max: number | null;
  step: number | null;
  global_only: boolean;
  /** D'où vient la valeur livrée (« presets/prompts/script.yaml › temperature », « .env (LLM_PROVIDER) »). */
  source: string;
  value: unknown;
  origin: SettingOrigin;
  preset: unknown;
  /** Valeur sans le niveau en cours d'édition (ce que « hérité » donnerait). */
  inherited: unknown;
}

export interface Knowledge {
  collections: string[];
  top_k: number;
  /** Budget de jetons (Dessinateur : celui du rédacteur de prompt) ; null : celui de knowledge.yaml. */
  budget_tokens: number | null;
}

export interface AgentDetail extends AgentSummary {
  scope: { project_id: number | null; project_title: string | null };
  global_version: number;
  trial: boolean;
  trial_description: string;
  secrets: { env: string; label: string; present: boolean }[];
  settings: AgentSetting[];
  knowledge: { value: Knowledge; origin: SettingOrigin; inherited: Knowledge };
  problem: string | null;
  saved_version?: number | null;
}

export interface AgentVersion {
  version: number;
  created_at: string;
  author: string;
  action: "save" | "restore" | "reset";
  action_label: string;
  restored_from: number | null;
  keys: string[];
  diff: { key: string; label: string; before: unknown; after: unknown }[];
}

export interface TrialSection {
  title: string;
  kind: "text" | "json" | "layout" | "bubbles";
  text?: string;
  data?: unknown;
}

export interface TrialResult {
  input: TrialSection[];
  output: TrialSection[];
  error: string | null;
  duration_ms: number;
}

export interface AgentProfileInput {
  values: Record<string, unknown>;
  knowledge?: Knowledge;
}

export interface SeriesAgentOverride {
  agent_id: string;
  name: string;
  icon: string;
  step: number;
  version: number;
  updated_at: string;
  settings: { key: string; label: string }[];
}

// --- Direction artistique -------------------------------------------------------------------
export type DaRythme = "calme" | "montée" | "climax" | "respiration";
export type DaPageChoc = "pleine page" | "splash";

export interface DaSfx {
  text: string;
  intensity: string;
}

export interface DaPanel {
  panel_id: number;
  index: number;
  intensity: Intensity | null;
  plan: string | null;
  angle: string | null;
  cadre: string | null;
  ambiance: string;
  /** Mouvement ou pose du corps (français), repris par le rédacteur de prompt. */
  action: string;
  sfx: DaSfx[];
  /** Bibliothèque proposée par l'agent (null ou absent : garder le décor / les objets du scénario). */
  decor?: number | null;
  objets?: number[] | null;
  /** Case à spectateur : « plan de réaction » ou « vue subjective » (null : pas de spectateur). */
  point_de_vue?: string | null;
  spectateurs?: string[];
  /** Choix par défaut : l'agent n'a pas tranché. */
  point_de_vue_defaut?: boolean;
}

/** Choix de direction artistique d'une page (`has_direction` faux : pas encore proposée). */
export interface PageDirection {
  page_id: number;
  number: number;
  panel_count: number;
  rythme: DaRythme | null;
  layout_style: string | null;
  template: string | null;
  page_choc: DaPageChoc | null;
  rationale: string;
  panels: DaPanel[];
  /** Règles de mise en scène encore enfreintes (« chapitre : … » : commune aux pages dirigées ensemble). */
  warnings: string[];
  has_direction: boolean;
  /** Champs modifiés par l'auteur, gardés quand l'agent repropose : « rythme », « 12.plan »… */
  locks: string[];
  /** Proposée par l'agent, appliquée aux cases (validation, « Appliquer » ou d'office à la génération), rejetée
   * par l'auteur (jamais appliquée d'office). « accepted » : ancienne validation. */
  status: "proposed" | "applied" | "rejected" | "accepted";
  variant: number;
  out_of_date: boolean;
  applied: boolean;
  pending: boolean;
  applied_at: string | null;
}

export interface ChapterDirection {
  chapter_id: number;
  variety: string;
  variety_label: string;
  series_layout_style: string;
  pages: PageDirection[];
  options: {
    rythmes: DaRythme[];
    intensities: Intensity[];
    plans: string[];
    angles: string[];
    cadres: string[];
    page_chocs: DaPageChoc[];
    sfx_intensities: string[];
    points_de_vue?: string[];
    styles: { value: string; label: string }[];
    templates: LayoutTemplate[];
  };
}

export interface DirectionEdit {
  page?: Partial<Pick<PageDirection, "rythme" | "layout_style" | "template" | "page_choc">>;
  panels?: ({ panel_id: number } & Partial<Omit<DaPanel, "panel_id" | "index">>)[];
  lock?: string[];
  unlock?: string[];
  /** true : valider la page, c'est l'appliquer aux cases tout de suite. */
  accept?: boolean;
  /** true : rejeter la direction de la page (plus appliquée, même à la génération) ; false : annuler le rejet. */
  reject?: boolean;
}

export interface DirectionApplyResult {
  applied: number[];
  relaid: number[];
  skipped: { number: number; reason: string }[];
  message: string;
  pages: PageData[];
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

// --- Tomes et couverture -----------------------------------------------------
/** Zone réservée d'une couverture (logo et titre, numéro de tome, auteur). */
export interface CoverZone {
  id: string;
  label: string;
  /** Zone à garder dégagée dans l'illustration (le logo s'y pose). */
  clear: boolean;
  x_mm: number;
  y_mm: number;
  width_mm: number;
  height_mm: number;
  /** Dans l'image complète (fond perdu compris), en px. */
  px: { x: number; y: number; width: number; height: number };
  /** Dans l'image complète, en fraction de sa largeur / hauteur (surimpression de l'aperçu). */
  rel: { x: number; y: number; width: number; height: number };
}

/** Format de couverture (presets/cover_formats/). */
export interface CoverFormat {
  id: string;
  name: string;
  default: boolean;
  page_format: string | null;
  width_mm: number;
  height_mm: number;
  dpi: number;
  bleed_mm: number;
  safety_mm: number;
  full_width_mm: number;
  full_height_mm: number;
  trim_width_px: number;
  trim_height_px: number;
  full_width_px: number;
  full_height_px: number;
  bleed_px: number;
  zones: CoverZone[];
  /** Taille générée par le flux de couverture, avant l'agrandissement au DPI du format. */
  generation_width: number | null;
  generation_height: number | null;
}

export interface VolumeChapter {
  id: number;
  number: number;
  title: string;
  status: ChapterStatus;
}

/** Un tome d'une série. */
export interface Volume {
  id: number;
  project_id: number;
  number: number;
  title: string;
  cover_format: string;
  cover_format_name: string | null;
  /** Chapitres inclus, dans l'ordre du tome. */
  chapters: VolumeChapter[];
  cover_character_ids: number[];
  cover_intent: string;
  cover_prompt: string;
  /** ai : rédigé par l'IA ; manual : saisi ou retouché ; null : pas encore de prompt. */
  cover_prompt_source: "ai" | "manual" | null;
  cover_prompt_notes: string;
  selected_cover_id: number | null;
  selected_cover_url: string | null;
  cover_count: number;
  created_at: string;
  updated_at: string;
}

export interface VolumeInput {
  number?: number | null;
  title?: string;
  cover_format?: string | null;
  chapter_ids?: number[];
  cover_character_ids?: number[];
  cover_intent?: string;
  cover_prompt?: string;
}

export interface CoverCharacter {
  id: number;
  name: string;
  has_reference: boolean;
  image_url: string | null;
  /** Admis par la charte des couvertures de la série (toujours vrai si la charte ne nomme personne). */
  in_charter: boolean;
}

/** Contrôle d'identité d'une version (couche CCIP du QC) : avertissement, jamais de blocage. */
export interface CoverIdentity {
  status: "done" | "skipped" | "unavailable" | "error";
  message: string;
  characters: { name: string; similarity: number; ok: boolean }[];
  warnings: string[];
  min_similarity: number | null;
}

/** Charte des couvertures de la série, telle qu'appliquée au tome. */
export interface StudioCharter {
  saved: boolean;
  summary: string;
  lines: string[];
  character_ids: number[];
  present: string[];
  outside: string[];
  warnings: string[];
}

export type CharterField = "palette_mode" | "mood" | "shot" | "back_shot" | "logo_place" | "subject";

export interface CharterChoice {
  id: string;
  label: string;
  description: string;
}

/** Charte des couvertures d'une série (fiche série) : choix bornés de presets/cover_charter.yaml. */
export interface CoverCharter {
  project_id: number;
  available: boolean;
  problem: string | null;
  saved: boolean;
  values: Record<CharterField, string>;
  character_ids: number[];
  options: Record<CharterField, CharterChoice[]>;
  labels: Record<CharterField, string>;
  characters: { id: number; name: string; has_reference: boolean; image_url: string | null }[];
  max_characters: number;
  palette_name: string | null;
  palette: { role: string; hex: string; sent: boolean }[];
  monochrome_series: boolean;
  front_lines: string[];
  back_lines: string[];
  identity_check: boolean;
  identity_available: boolean;
  min_similarity: number | null;
  warnings: string[];
}

export type CoverCharterInput = Partial<Record<CharterField, string>> & { character_ids?: number[] };

export interface CoverVersion {
  id: number;
  url: string;
  width: number;
  height: number;
  seed: Seed | null;
  selected: boolean;
  cover_format: string;
  prompt: string;
  preset_name: string | null;
  upscaler_name: string | null;
  generated_width: number | null;
  generated_height: number | null;
  identity: CoverIdentity | null;
  created_at: string;
}

/** Écran « Couverture » d'un tome. */
export interface CoverStudio {
  volume: Volume;
  format: CoverFormat | null;
  formats: CoverFormat[];
  characters: CoverCharacter[];
  max_characters: number;
  reference_slots: number;
  /** Plus récentes d'abord. */
  versions: CoverVersion[];
  active_jobs: Job[];
  /** Couverture indisponible (cover.yaml absent, format inconnu). */
  problem: string | null;
  /** La série est en noir et blanc : la couverture, elle, est toujours en couleur. */
  monochrome_series: boolean;
  style: string;
  clear_zone: string | null;
  workflow: string | null;
  workflow_name: string | null;
  upscaler_name: string | null;
  /** Charte des couvertures de la série (null : preset absent). */
  charter: StudioCharter | null;
}

// --- Composition de la couverture (1re, 4e, dos, export) ---------------------

/** Rectangle en fraction de l'image complète (fond perdu compris). */
export interface RelRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Placement du logo sur la 1re : centre en fraction du format rogné, taille relative à sa zone. */
export interface LogoPlacement {
  cx: number;
  cy: number;
  scale: number;
}

export interface CompositionLogo {
  present: boolean;
  placement: LogoPlacement | null;
  rect: RelRect | null;
  zone: RelRect | null;
  safe: RelRect;
  scale_min: number;
  scale_max: number;
  default_scale: number;
}

export interface BackImageChoice {
  source: "panel" | "generated";
  id: number;
}

export interface PanelChoice {
  image_id: number;
  url: string;
  chapter_number: number;
  page_number: number;
  panel_number: number;
}

export interface BackVersion {
  id: number;
  url: string;
  width: number;
  height: number;
  seed: Seed | null;
  prompt: string;
  selected: boolean;
  identity: CoverIdentity | null;
  created_at: string;
}

export interface CompositionNotice {
  code: string;
  message: string;
  part: "front" | "back" | "spine";
}

export type CoverPart = "front" | "back" | "spine" | "flat";

/** Composition de la couverture d'un tome (écran « Couverture »). */
export interface CoverComposition {
  volume_id: number;
  project_id: number;
  number: number;
  series_title: string;
  direction: "ltr" | "rtl";
  format: CoverFormat | null;
  /** Composition indisponible (presets). */
  problem: string | null;
  /** Change dès que la composition change : clé des aperçus. */
  revision: string;
  author: string;
  series_author: string;
  summary: string;
  tagline: string;
  summary_source: "ai" | "manual" | null;
  summary_notes: string;
  summary_chars: number;
  summary_min: number;
  summary_max: number;
  tagline_max: number;
  summary_size_pt: number | null;
  back_layout: string | null;
  back_layouts: { id: string; name: string; description: string }[];
  back_image: BackImageChoice | null;
  back_image_url: string | null;
  back_prompt: string;
  back_aspect: [number, number];
  back_versions: BackVersion[];
  back_jobs: Job[];
  panel_choices: PanelChoice[];
  logo: CompositionLogo | null;
  has_front_image: boolean;
  palette_name: string | null;
  spine_mm: number | null;
  pages: number;
  /** Faces de la couverture à plat, de gauche à droite. */
  order: ("front" | "spine" | "back")[];
  warnings: CompositionNotice[];
  /** Bloquants : l'export est refusé tant qu'il en reste. */
  problems: CompositionNotice[];
  export_jobs: Job[];
  last_export: { job_id: number; filename: string; url: string; finished_at: string | null } | null;
}

export interface CompositionPatch {
  summary?: string;
  tagline?: string;
  back_layout?: string;
  author?: string;
  series_author?: string;
  logo?: LogoPlacement;
  reset_logo?: boolean;
  back_image?: BackImageChoice;
  clear_back_image?: boolean;
  back_prompt?: string;
}

// --- Savoir-faire et bible ---------------------------------------------------
export interface KnowledgeCollection {
  id: number;
  name: string;
  description: string;
  /** null : collection globale. */
  project_id: number | null;
  project_title: string | null;
  document_count: number;
  chunk_count: number;
  token_count: number;
  /** Sous le seuil « petite collection » : injectée entière dans les agents. */
  whole: boolean;
  /** Pack de savoir-faire livré (presets/knowledge_packs/) : lecture seule, réécrite par « Mettre à jour les packs ». */
  pack?: string | null;
  created_at: string;
  updated_at: string;
}

export type CollectionInput = { name: string; description?: string; project_id?: number | null };

export interface KnowledgeChunk {
  id: number;
  index: number;
  heading: string;
  text: string;
  token_count: number;
  embedded: boolean;
}

export interface KnowledgeDocumentSummary {
  id: number;
  collection_id: number;
  title: string;
  source: "text" | "md" | "txt" | "pdf";
  original_name: string | null;
  tags: string[];
  token_count: number;
  chunk_count: number;
  index_error: string | null;
  /** Document d'un pack livré (lecture seule) et identifiant de sa fiche (ex. « SHOT_CU_001 »). */
  pack?: string | null;
  pack_key?: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument extends KnowledgeDocumentSummary {
  content: string;
  collection_name: string;
  /** Champs du bloc meta d'une fiche de pack (retiré du texte injecté). */
  meta?: Record<string, unknown>;
  /** Mots-clés cherchés mais jamais injectés (titre, pont de vocabulaire). */
  keywords?: string;
  chunks: KnowledgeChunk[];
}

export type DocumentInput = { title: string; content: string; tags: string[] };

/** Ce que le rédacteur de prompt a reçu pour le prompt actuel d'une case. */
export interface PromptSources {
  written_at: string;
  query: string;
  collections: string[];
  passages: Passage[];
  /** Écartés comme redondants (raison dans `dropped`). */
  dropped?: Passage[];
  tokens: number;
  budget_tokens: number;
  bible: string;
  /** Prompt retouché depuis (à la main ou par le dialogue). */
  edited: boolean;
}

/** « Réécrire les prompts du chapitre » : cases concernées. */
export interface RewritePrompts {
  count: number;
  ai_prompt: boolean;
}

export interface Passage {
  chunk_id: number;
  document_id: number;
  document_title: string;
  collection_id: number;
  collection_name: string;
  heading: string;
  text: string;
  tokens: number;
  score: number | null;
  vector_score: number | null;
  keyword_score: number | null;
  /** framing : fiche du plan ou de l'angle de la case (une seule par famille) ; genre : courbe de tension du genre de la série. */
  mode: "retrieved" | "whole" | "framing" | "genre";
  /** Passage d'une fiche de pack livré. */
  pack?: string | null;
  /** Recherche par page (direction artistique) : pages pour lesquelles le passage a été retenu. */
  pages?: number[];
  /** Écarté comme redondant : raison (doublon, autre plan ou angle que la case). */
  dropped?: string | null;
  selected: boolean;
}

export interface BibleSummary {
  text: string;
  tokens: number;
  truncated: boolean;
  chapter_summaries: number;
}

export interface SearchResult {
  query: string;
  collections: string[];
  passages: Passage[];
  selected_tokens: number;
  budget_tokens: number;
  top_k: number;
  bible: BibleSummary | null;
  warning: string | null;
}

export interface SearchInput {
  query: string;
  collection_ids?: number[];
  project_id?: number;
  top_k?: number;
  budget_tokens?: number;
}

export interface ChapterSummaryEntry {
  chapter_id: number | null;
  number: number | null;
  title: string;
  summary: string;
  added_at: string | null;
}

export interface Bible {
  project_id: number;
  world: string;
  tone: string;
  rules: string;
  motifs: string;
  characters: { id: number; name: string; visual_description: string; note: string }[];
  /** Décors et objets de la bibliothèque, repris dans la bible injectée aux agents. */
  decors?: { id: number; name: string; visual_description: string }[];
  objets?: { id: number; name: string; visual_description: string }[];
  chapter_summaries: ChapterSummaryEntry[];
  rendered: BibleSummary | null;
  updated_at: string | null;
}

/** Valeur réglable de l'ADN de la série (presets/pre_direction.yaml) : part (0 à 1), entier ou oui/non. */
export interface DnaField {
  path: string;
  group: string;
  label: string;
  help: string;
  kind: "share" | "int" | "bool";
  min: number | null;
  max: number | null;
  step: number | null;
}

export type DnaValue = number | boolean;

/** ADN de la série : valeurs héritées du genre, ajustées par la série, effectives (chemin → valeur). */
export interface PreDirection {
  project_id: number;
  genre: string | null;
  genre_name: string | null;
  available: boolean;
  groups: Record<string, string>;
  fields: DnaField[];
  inherited: Record<string, DnaValue>;
  overrides: Record<string, DnaValue>;
  effective: Record<string, DnaValue>;
}

/** Créateur de série : questions fermées de l'échange et ce que la série a déjà (une relance propose un différentiel). */
export interface SeriesCreator {
  project_id: number;
  available: boolean;
  reason: string | null;
  agent_name: string;
  genre_name: string | null;
  questions: { id: string; label: string; help: string; choices: { id: string; label: string }[] }[];
  max_free_chars: number;
  max_pitch_chars: number;
  bible_filled: string[];
  notes_filled: number;
  characters: number;
  dna_adjusted: number;
}

export interface CreatorAnswer {
  choice: string | null;
  note: string;
}

/** Proposition du créateur de série : ce qui est écrit à côté de ce qui est proposé (rien n'est encore enregistré). */
export interface CreatorProposal {
  project_id: number;
  genre_name: string | null;
  attempts: number;
  notes: string;
  dna: {
    path: string;
    label: string;
    group: string;
    kind: string;
    min: number | null;
    max: number | null;
    genre_value: DnaValue;
    current_value: DnaValue;
    adjusted: boolean;
    proposed: DnaValue;
    why: string;
    conflict: boolean;
  }[];
  bible: { key: string; label: string; current: string; proposed: string; conflict: boolean }[];
  characters: { id: number; name: string; current: string; proposed: string; conflict: boolean }[];
}

export interface CreatorApply {
  dna: Record<string, DnaValue>;
  bible: Record<string, string>;
  character_notes: Record<number, string>;
  /** Clés confirmées par l'auteur : « bible.world », « character.12 », « dna.shots.wide.min ». */
  overwrite: string[];
}

export interface CreatorApplied {
  pre_direction: PreDirection;
  bible: Bible;
  written: string[];
}

/** Ce que « Découper » enverra : charte de la série en clair et ce qui manque à la bible. */
export interface ScriptBrief {
  project_id: number;
  pre_direction: string;
  art_pre_direction: string;
  bible_empty: boolean;
  characters_without_note: { id: number; name: string }[];
}

export type BibleInput = Partial<Pick<Bible, "world" | "tone" | "rules" | "motifs" | "chapter_summaries">> & {
  character_notes?: Record<number, string>;
};

/** Densité des dialogues d'un chapitre (bulles enregistrées, onomatopées à part). */
export interface DialogueStats {
  panels: number;
  replies: number;
  sfx: number;
  per_panel: number;
  mean_words: number;
  /** Pensées, voix off et narrations. */
  inner_voice: number;
  /** Cases dont la seule bulle est une onomatopée. */
  sfx_only: number;
}

/** Règles de dialogue du scénariste encore enfreintes (après les relances ou une retouche). */
export interface DialogueReport {
  stats: DialogueStats;
  warnings: string[];
}

export interface ScriptSources {
  run_id: number;
  job_id: number | null;
  agent: string;
  model: string | null;
  /** Requête de recherche (direction artistique : une ligne « Page N : … » par page). */
  query?: string;
  collections: string[];
  passages: Passage[];
  bible: BibleSummary | null;
  created_at: string;
}

export interface KnowledgeStatus {
  provider: string | null;
  model: string | null;
  available: boolean;
  detail: string | null;
  collections: number;
  documents: number;
  chunks: number;
  stale_chunks: number;
  small_collection_tokens: number;
  vector_backend: string;
  agents: {
    role: string;
    label: string;
    collections: string[];
    source: "profile" | "preset";
    series_collections: boolean;
    budget_tokens: number;
    top_k: number;
    bible: boolean;
    /** Prompts image : note courte du prompt par fragments (null : pas de rédacteur à part). */
    fragment_budget_tokens: number | null;
    fragment_top_k: number | null;
  }[];
  /** Dernier import des packs de savoir-faire livrés (démarrage ou « Mettre à jour les packs »). */
  packs?: PackReport[];
}

export interface PackReport {
  pack: string;
  collections: number;
  documents: number;
  created: number;
  updated: number;
  deleted: number;
  unchanged: number;
  skipped_sections: string[];
  warnings: string[];
  error: string | null;
}

/** Savoir-faire d'une case pour un destinataire (rédacteur de prompt ou note des fragments). */
export interface PanelKnowledgePart {
  passages: Passage[];
  tokens: number;
  budget_tokens: number;
  top_k: number;
  text: string;
  text_tokens: number;
  bible: string;
  bible_tokens: number;
  /** Passages qui auraient été servis sans le tri des redondances. */
  dropped?: Passage[];
}

export interface PanelKnowledge {
  panel_id: number;
  query: string;
  collections: string[];
  writer: PanelKnowledgePart;
  fragments: PanelKnowledgePart;
  warning: string | null;
}

// --- Traçabilité : journal des générations, verdicts, A/B, statistiques -----------------------
export type Verdict = "validated" | "rejected" | "regenerated" | "edited";
export type Judge = "validated" | "rejected";
export type MeasureKey = "dark_pct" | "black_pct" | "white_pct" | "saturation_pct" | "line_density_pct";

export interface JournalSettings {
  /** Raisons d'un rejet (liste fermée de presets/journal.yaml), dans l'ordre des raccourcis 1 à 9. */
  reasons: { id: string; label: string }[];
  /** Mesures de tonalité et cible (presets/qc_tonality.yaml ; null : pas de cible). */
  measures: { key: MeasureKey; label: string; target: number | null }[];
  tonality_reference: string;
  dark_below: number;
  black_below: number;
  white_from: number;
  /** Sous ce nombre de cases jugées : « peu de données ». */
  low_data_below: number;
  kinds: Record<string, string>;
  verdicts: Record<Verdict, string>;
}

export interface GenerationEvent {
  id: number;
  created_at: string;
  verdict: Verdict;
  action: string;
  reason: string | null;
  reason_label: string | null;
  note: string;
}

/** Une ligne du journal : la génération qui a produit une image (jamais réécrite). */
export interface GenerationLog {
  id: number;
  created_at: string;
  kind: string;
  status: "succeeded" | "failed" | "cancelled";
  error: string | null;
  panel_id: number | null;
  image_id: number | null;
  version: number | null;
  preset: string | null;
  tier: string | null;
  model: string | null;
  steps: number | null;
  cfg: number | null;
  seed: number | null;
  width: number | null;
  height: number | null;
  denoise: number | null;
  positive_prompt: string;
  negative_prompt: string;
  positive_chars: number;
  positive_words: number;
  negative_chars: number;
  negative_words: number;
  prompt_source: string | null;
  writer_hash: string | null;
  references: Record<string, unknown>[];
  loras: { name: string; weight: number; source: string }[];
  knowledge: { document_id: number; title: string; collection: string; tokens: number }[];
  framing: string | null;
  angle: string | null;
  mood: string | null;
  finish: string | null;
  duration_ms: number | null;
  measures: Partial<Record<MeasureKey, number | null>>;
  /** Valeur − cible, en points (null : pas de cible). */
  gaps: Partial<Record<MeasureKey, number | null>>;
  ab_group: string | null;
  ab_arm: "A" | "B" | null;
  ab_mode: ABMode | null;
  /** Dernier verdict « jugé » de l'auteur. */
  verdict: Judge | null;
  events: GenerationEvent[];
}

export interface VerdictInput {
  verdict: Judge;
  reason?: string | null;
  note?: string;
}

export type ABMode = "prompt" | "tier" | "cfg";

export interface ABInput {
  mode: ABMode;
  prompt_b?: string;
  presets?: [string, string];
  cfgs?: [number, number];
  seed?: number | null;
}

export interface ABGroup {
  group: string;
  mode: ABMode | null;
  seed: number | null;
  /** Un bras au moins est encore en file ou en cours. */
  pending: boolean;
  arms: { arm: "A" | "B"; log: GenerationLog | null; image: PanelImage | null }[];
  choice: "A" | "B" | null;
}

export interface StatsRow {
  generations: number;
  judged: number;
  validated: number;
  rejected: number;
  /** % de gardées parmi les jugées (null : aucune jugée). */
  validation_rate: number | null;
  regenerated: number;
  edited: number;
  low_data: boolean;
  means: Partial<Record<MeasureKey, number | null>>;
}

export interface Stats {
  total: StatsRow;
  low_data: boolean;
  low_data_below: number;
  breakdowns: { key: string; label: string; rows: (StatsRow & { value: string })[] }[];
  /** « Passer outre » une étape vitale (garde d'étapes), les plus récents d'abord. */
  stage_overrides: StageOverrideRow[];
}

/** Étapes vitales d'un chapitre (garde d'étapes du moteur : pipeline/stage_gate.py). */
export type StageKey = "script" | "direction" | "layout" | "references" | "prompts" | "approved" | "lettering";

export interface StageDecision {
  decision: "validated" | "forced" | "revoked";
  author: string;
  note: string;
  at: string;
}

export interface ChapterStage {
  key: StageKey;
  label: string;
  /** Réglée par le contenu du chapitre. */
  complete: boolean;
  /** « Passer outre » en cours. */
  forced: boolean;
  /** Complète ou forcée : ne bloque rien. */
  passed: boolean;
  total: number;
  faults: number;
  /** « 5 pages en attente sur 5 ». */
  summary: string;
  /** Éléments en faute (« page 3 », « Kaï »), 20 au plus. */
  examples: string[];
  /** Ce qu'il faut faire (« Applique-la »). */
  fix: string;
  /** Onglet du chapitre qui règle l'étape (`direction` pour les références : panneau Distribution). */
  screen: string;
  /** Actions bloquées en ce moment (« générer », « lettrer »…). */
  blocks: string[];
  decision: StageDecision | null;
}

export interface ChapterStages {
  chapter_id: number;
  project_id: number;
  stages: ChapterStage[];
}

export interface StageOverrideRow {
  id: number;
  at: string;
  project_id: number | null;
  chapter_id: number;
  chapter_number: number | null;
  /** null : chapitre supprimé depuis. */
  chapter_title: string | null;
  stage: string;
  stage_label: string;
  author: string;
  note: string;
  faults: number;
  total: number;
}

export interface StatsFilter {
  project_id?: number | null;
  chapter_id?: number | null;
  date_from?: string | null;
  date_to?: string | null;
  tier?: string | null;
  kind?: string | null;
}

export function statsQuery(filter: StatsFilter, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams(extra);
  for (const [k, v] of Object.entries(filter)) {
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

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
  updateProject: (id: number, body: Partial<ProjectInput> & { layout_style_notice?: false }) =>
    request<Project>(`/projects/${id}`, json("PATCH", body)),
  relayoutProject: (id: number) => request<RelayoutResult>(`/projects/${id}/relayout`, { method: "POST" }),
  deleteProject: (id: number) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  cleanupProject: (id: number) => request<CleanupResult>(`/projects/${id}/cleanup`, { method: "POST" }),
  rebuildLibrary: (id: number) => request<LibraryResult>(`/projects/${id}/library`, { method: "POST" }),
  rebuildAllLibraries: () => request<LibraryResult>("/library", { method: "POST" }),
  resetWorkshop: (confirm: string, all: boolean) => request<ResetResult>("/reset", json("POST", { confirm, all })),

  listLibrary: <T extends LibraryEntry = LibraryEntry>(kind: LibraryKind, projectId: number) =>
    request<T[]>(`/projects/${projectId}/${LIBRARY_SEGMENT[kind]}`),
  getLibraryEntry: (kind: LibraryKind, id: number) => request<LibraryEntry>(`/${LIBRARY_SEGMENT[kind]}/${id}`),
  createLibraryEntry: (kind: LibraryKind, projectId: number, body: LibraryEntryInput) =>
    request<LibraryEntry>(`/projects/${projectId}/${LIBRARY_SEGMENT[kind]}`, json("POST", body)),
  updateLibraryEntry: (kind: LibraryKind, id: number, body: Partial<LibraryEntryInput>) =>
    request<LibraryEntry>(`/${LIBRARY_SEGMENT[kind]}/${id}`, json("PATCH", body)),
  deleteLibraryEntry: (kind: LibraryKind, id: number) =>
    request<void>(`/${LIBRARY_SEGMENT[kind]}/${id}`, { method: "DELETE" }),
  uploadLibraryImages: (kind: LibraryKind, id: number, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request<LibraryEntry>(`/${LIBRARY_SEGMENT[kind]}/${id}/images`, { method: "POST", body: form });
  },
  deleteLibraryImage: (kind: LibraryKind, id: number, imageId: number) =>
    request<void>(`/${LIBRARY_SEGMENT[kind]}/${id}/images/${imageId}`, { method: "DELETE" }),
  reorderLibraryImages: (kind: LibraryKind, id: number, imageIds: number[]) =>
    request<LibraryEntry>(`/${LIBRARY_SEGMENT[kind]}/${id}/images/order`, json("PUT", { image_ids: imageIds })),
  setLibraryImageAngle: (kind: LibraryKind, id: number, imageId: number, angle: string | null) =>
    request<LibraryEntry>(`/${LIBRARY_SEGMENT[kind]}/${id}/images/${imageId}/angle`, json("PUT", { angle })),
  cameraLoras: () => request<CameraLoras>("/presets/camera-loras"),
  /** « Nouvel angle » : une nouvelle vue de la fiche, candidate de l'historique ; « Valider » (`keepReference`) la range parmi ses images, étiquetée par son angle. */
  newAngleView: (kind: LibraryKind, id: number, body: AngleInput & { start_image_id?: number | null }) =>
    request<Job[]>(`/${LIBRARY_SEGMENT[kind]}/${id}/angle-views`, json("POST", body)),
  referenceSheets: (kind?: LibraryKind) =>
    request<ReferenceSheet[]>(`/presets/reference-sheets${kind ? `?kind=${kind}` : ""}`),
  referenceStudio: (kind: LibraryKind, id: number) =>
    request<ReferenceStudio>(`/${LIBRARY_SEGMENT[kind]}/${id}/reference-variants`),
  generateReferences: (kind: LibraryKind, id: number, body: ReferenceGenerateInput) =>
    request<Job[]>(`/${LIBRARY_SEGMENT[kind]}/${id}/reference-variants`, json("POST", body)),
  refineReference: (variantId: number, body: ReferenceRefineInput) =>
    request<Job[]>(`/reference-variants/${variantId}/refine`, json("POST", body)),
  /** `acceptPeople` : « Garder quand même » une fiche d'objet ou de décor où un personnage a été détecté. */
  keepReference: (variantId: number, acceptPeople = false) =>
    request<LibraryEntry>(
      `/reference-variants/${variantId}/keep`,
      acceptPeople ? json("POST", { accept_people: true }) : { method: "POST" },
    ),
  deleteReferenceVariant: (variantId: number) =>
    request<void>(`/reference-variants/${variantId}`, { method: "DELETE" }),
  styleBoard: (projectId: number) => request<StyleBoard>(`/projects/${projectId}/style-board`),
  // Identité visuelle (fiche série)
  identity: (projectId: number) => request<SeriesIdentity>(`/projects/${projectId}/identity`),
  proposePalettes: (projectId: number, more = false) =>
    request<SeriesIdentity>(`/projects/${projectId}/identity/palettes`, json("POST", { more })),
  savePalette: (projectId: number, palette: Palette) =>
    request<SeriesIdentity>(`/projects/${projectId}/identity/palette`, json("PUT", palette)),
  proposeLogos: (projectId: number, more = false) =>
    request<SeriesIdentity>(`/projects/${projectId}/identity/logos`, json("POST", { more })),
  previewLogo: (projectId: number, spec: LogoSpec) =>
    request<LogoPreview>(`/projects/${projectId}/identity/logo/preview`, json("POST", spec)),
  saveLogo: (projectId: number, spec: LogoSpec) =>
    request<SeriesIdentity>(`/projects/${projectId}/identity/logo`, json("POST", spec)),
  generateStyleTrials: (projectId: number) =>
    request<Job[]>(`/projects/${projectId}/style-board/trials`, { method: "POST" }),
  chooseStyleTrial: (trialId: number) => request<Job>(`/style-trials/${trialId}/choose`, { method: "POST" }),
  activateStyleReference: (assetId: number) =>
    request<StyleBoard>(`/style-references/${assetId}/activate`, { method: "POST" }),
  listCharacters: (projectId: number) => request<Character[]>(`/projects/${projectId}/characters`),

  listChapters: (projectId: number) => request<Chapter[]>(`/projects/${projectId}/chapters`),
  coverFormats: () => request<CoverFormat[]>("/presets/cover-formats"),
  listVolumes: (projectId: number) => request<Volume[]>(`/projects/${projectId}/volumes`),
  createVolume: (projectId: number, body: VolumeInput) =>
    request<Volume>(`/projects/${projectId}/volumes`, json("POST", body)),
  updateVolume: (id: number, body: VolumeInput) => request<Volume>(`/volumes/${id}`, json("PATCH", body)),
  deleteVolume: (id: number) => request<void>(`/volumes/${id}`, { method: "DELETE" }),
  coverStudio: (volumeId: number) => request<CoverStudio>(`/volumes/${volumeId}/cover`),
  coverCharter: (projectId: number) => request<CoverCharter>(`/projects/${projectId}/cover-charter`),
  saveCoverCharter: (projectId: number, body: CoverCharterInput) =>
    request<CoverCharter>(`/projects/${projectId}/cover-charter`, json("PUT", body)),
  resetCoverCharter: (projectId: number) =>
    request<CoverCharter>(`/projects/${projectId}/cover-charter`, { method: "DELETE" }),
  writeCoverPrompt: (volumeId: number, body: { intent?: string; character_ids?: number[] }) =>
    request<CoverStudio>(`/volumes/${volumeId}/cover/prompt`, json("POST", body)),
  generateCover: (volumeId: number, body: { prompt?: string; seed?: Seed | null } = {}) =>
    request<Job>(`/volumes/${volumeId}/cover/generate`, json("POST", body)),
  selectCover: (coverId: number) => request<CoverStudio>(`/volume-covers/${coverId}/select`, { method: "POST" }),
  deleteCover: (coverId: number) => request<void>(`/volume-covers/${coverId}`, { method: "DELETE" }),
  coverComposition: (volumeId: number) => request<CoverComposition>(`/volumes/${volumeId}/composition`),
  updateComposition: (volumeId: number, body: CompositionPatch) =>
    request<CoverComposition>(`/volumes/${volumeId}/composition`, json("PATCH", body)),
  writeBackSummary: (volumeId: number, body: { rewrite?: boolean } = {}) =>
    request<CoverComposition>(`/volumes/${volumeId}/back/summary`, json("POST", body)),
  generateBackIllustration: (volumeId: number, body: { prompt?: string; seed?: Seed | null } = {}) =>
    request<Job>(`/volumes/${volumeId}/back/generate`, json("POST", body)),
  exportCover: (volumeId: number, body: ExportOptions) =>
    request<Job>(`/volumes/${volumeId}/cover/export`, json("POST", body)),
  upcomingChapters: (days = 7) => request<Chapter[]>(`/chapters/upcoming?days=${days}`),
  getChapter: (id: number) => request<Chapter>(`/chapters/${id}`),
  createChapter: (projectId: number, body: Partial<ChapterInput>) =>
    request<Chapter>(`/projects/${projectId}/chapters`, json("POST", body)),
  updateChapter: (id: number, body: Partial<ChapterInput>) => request<Chapter>(`/chapters/${id}`, json("PATCH", body)),
  deleteChapter: (id: number) => request<void>(`/chapters/${id}`, { method: "DELETE" }),
  chapterStages: (id: number) => request<ChapterStages>(`/chapters/${id}/stages`),
  overrideStage: (id: number, stage: StageKey, body: { author?: string; note?: string } = {}) =>
    request<ChapterStages>(`/chapters/${id}/stages/${stage}/override`, json("POST", body)),
  revokeStageOverride: (id: number, stage: StageKey) =>
    request<ChapterStages>(`/chapters/${id}/stages/${stage}/override`, { method: "DELETE" }),
  reorderChapters: (projectId: number, chapterIds: number[]) =>
    request<Chapter[]>(`/projects/${projectId}/chapters/reorder`, json("POST", { chapter_ids: chapterIds })),

  startScript: (chapterId: number) => request<Job>(`/chapters/${chapterId}/script`, { method: "POST" }),
  linkCharacterName: (chapterId: number, name: string, characterId: number | null) =>
    request<CharacterLink>(
      `/chapters/${chapterId}/character-links`,
      json("POST", { name, character_id: characterId }),
    ),
  chapterCast: (chapterId: number) => request<ChapterCast>(`/chapters/${chapterId}/cast`),
  draftCastCard: (chapterId: number, name: string) =>
    request<CharacterDraft>(`/chapters/${chapterId}/cast/draft`, json("POST", { name })),
  markCrowd: (chapterId: number, name: string, author = "") =>
    request<ChapterCast>(`/chapters/${chapterId}/cast/crowds`, json("POST", { name, author })),
  revokeCrowd: (chapterId: number, markId: number, author = "") =>
    request<ChapterCast>(`/chapters/${chapterId}/cast/crowds/${markId}`, json("DELETE", { author })),
  createSecondaries: (chapterId: number) =>
    request<CastBatch>(`/chapters/${chapterId}/cast/secondaries`, { method: "POST" }),
  chapterJobs: (chapterId: number, step?: string) =>
    request<Job[]>(`/chapters/${chapterId}/jobs${step ? `?step=${encodeURIComponent(step)}` : ""}`),
  getJob: (id: number) => request<Job>(`/jobs/${id}`),

  getDirection: (chapterId: number) => request<ChapterDirection>(`/chapters/${chapterId}/direction`),
  startDirection: (chapterId: number, pageId?: number) =>
    request<Job>(`/chapters/${chapterId}/direction`, json("POST", pageId ? { page_id: pageId } : {})),
  editDirection: (pageId: number, body: DirectionEdit) =>
    request<PageDirection>(`/pages/${pageId}/direction`, json("PATCH", body)),
  applyDirection: (chapterId: number, pageIds?: number[]) =>
    request<DirectionApplyResult>(`/chapters/${chapterId}/direction/apply`, json("POST", pageIds ? { page_ids: pageIds } : {})),

  listPages: (chapterId: number) => request<PageData[]>(`/chapters/${chapterId}/pages`),
  savePages: (chapterId: number, pages: PageInput[]) =>
    request<PageData[]>(`/chapters/${chapterId}/pages`, json("PUT", { pages })),
  layoutChapter: (chapterId: number) => request<PageData[]>(`/chapters/${chapterId}/layout`, { method: "POST" }),
  layoutPage: (pageId: number, body: { template_id?: string | null; style?: string | null; reroll?: boolean } = {}) =>
    request<PageData>(`/pages/${pageId}/layout`, json("POST", body)),
  slantCut: (pageId: number, body: { path: number[]; index: number; ends: [number, number] }) =>
    request<PageData>(`/pages/${pageId}/cuts`, json("POST", body)),
  layoutStyles: () => request<LayoutStyle[]>("/layout/styles"),
  setPanelFrame: (panelId: number, body: Partial<PanelFrame>) =>
    request<PageData>(`/panels/${panelId}/frame`, json("PUT", body)),
  setPanelCrop: (panelId: number, body: PanelCrop) => request<PageData>(`/panels/${panelId}/crop`, json("PUT", body)),
  resetPanelCrop: (panelId: number) => request<PageData>(`/panels/${panelId}/crop`, { method: "DELETE" }),
  moveGutter: (pageId: number, body: { path: number[]; index: number; position: number }) =>
    request<PageData>(`/pages/${pageId}/gutters`, json("POST", body)),
  layoutTemplates: () => request<LayoutTemplate[]>("/layout/templates"),

  cancelJob: (id: number) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  queue: () => request<Queue>("/queue"),
  workflowPresets: () => request<WorkflowPreset[]>("/presets/workflows"),
  // /object_info pèse plusieurs Mo : le moteur borne ses appels, on borne aussi le nôtre.
  checkComfy: () => request<ComfyCheck>("/comfyui/check", { signal: AbortSignal.timeout(90_000) }),
  // Délai court : sans réponse, le sélecteur passe en saisie libre au lieu de tourner sans fin.
  comfyLoras: (refresh = false) =>
    request<LoraCatalog>(`/comfyui/loras${refresh ? "?refresh=true" : ""}`, { signal: AbortSignal.timeout(15_000) }),
  startComfyTrial: (preset: string) => request<Job>("/comfyui/trial", json("POST", { preset })),
  getPanel: (id: number) => request<PanelDetail>(`/panels/${id}`),
  panelKnowledge: (id: number) => request<PanelKnowledge>(`/panels/${id}/knowledge`),
  updatePanel: (
    id: number,
    body: {
      final_prompt?: string | null;
      generation_preset?: string | null;
      description?: string;
      setting?: string;
      staging?: string;
      sketch_denoise?: number | null;
      characters?: string[];
      offscreen_characters?: string[];
      viewpoint?: { mode: Viewpoint["mode"]; spectators: string[] } | null;
    },
  ) =>
    request<PanelDetail>(`/panels/${id}`, json("PATCH", body)),
  // Prompt rédigé par l'IA : jusqu'à 2 appels au LLM (le proxy laisse 3 min à cette route).
  /** `instruction` : consigne passée au même pipeline que le dialogue sur la case (sans historique). */
  rebuildPrompt: (id: number, instruction?: string) =>
    request<PanelDetail>(`/panels/${id}/prompt/rebuild`, {
      ...json("POST", instruction ? { instruction } : {}),
      signal: AbortSignal.timeout(180_000),
    }),
  panelDialog: (id: number) => request<PanelDialogTurn[]>(`/panels/${id}/dialog`),
  askPanelDialog: (id: number, instruction: string) =>
    request<PanelDialogTurn>(`/panels/${id}/dialog`, {
      ...json("POST", { instruction }),
      signal: AbortSignal.timeout(180_000),
    }),
  applyPanelDialog: (turnId: number, generate = false) =>
    request<DialogApplyResult>(`/panel-dialog/${turnId}/apply`, json("POST", { generate })),
  cancelPanelDialog: (turnId: number) => request<PanelDialogTurn>(`/panel-dialog/${turnId}/cancel`, { method: "POST" }),
  controlStatus: (refresh = false) =>
    request<ControlStatus>(`/comfyui/control${refresh ? "?refresh=true" : ""}`, { signal: AbortSignal.timeout(30_000) }),
  lockComposition: (
    id: number,
    body: { source: "croquis" | "version"; image_id?: number | null; type?: string | null; strength?: number | null },
  ) => request<PanelDetail>(`/panels/${id}/composition-lock`, json("POST", body)),
  lockCompositionFromImport: (id: number, file: File, type?: string | null, strength?: number | null) => {
    const form = new FormData();
    form.append("file", file);
    if (type) form.append("type", type);
    if (strength != null) form.append("strength", String(strength));
    return request<PanelDetail>(`/panels/${id}/composition-lock/import`, { method: "POST", body: form });
  },
  updateCompositionLock: (id: number, body: { type?: string | null; strength?: number | null }) =>
    request<PanelDetail>(`/panels/${id}/composition-lock`, json("PATCH", body)),
  refreshCompositionPreview: (id: number) =>
    request<PanelDetail>(`/panels/${id}/composition-lock/preview`, { method: "POST" }),
  unlockComposition: (id: number) => request<PanelDetail>(`/panels/${id}/composition-lock`, { method: "DELETE" }),
  generatePanel: (id: number, body: GenerateInput = {}) => request<Job[]>(`/panels/${id}/generate`, json("POST", body)),
  regeneratePanelQuality: (id: number) => request<Job[]>(`/panels/${id}/regenerate-quality`, { method: "POST" }),
  /** « Changer l'angle » : une nouvelle version de la case vue sous un autre angle (les autres ne bougent pas). */
  changePanelAngle: (id: number, body: AngleInput & { source_image_id?: number | null }) =>
    request<Job[]>(`/panels/${id}/change-angle`, json("POST", body)),
  chapterEstimate: (id: number) => request<Estimate>(`/chapters/${id}/estimate`),
  projectEstimate: (id: number) => request<Estimate>(`/projects/${id}/estimate`),
  generatePage: (id: number, body: { force?: boolean; count?: number } = {}) =>
    request<BatchGenerateResult>(`/pages/${id}/generate`, json("POST", body)),
  rewritablePrompts: (id: number) => request<RewritePrompts>(`/chapters/${id}/prompts/rewrite`),
  rewriteChapterPrompts: (id: number) =>
    request<RewritePrompts>(`/chapters/${id}/prompts/rewrite`, { method: "POST" }),
  generateChapter: (id: number, body: { force?: boolean; count?: number } = {}) =>
    request<BatchGenerateResult>(`/chapters/${id}/generate`, json("POST", body)),
  chapterProductionPlan: (id: number) => request<ChapterProductionPlan>(`/chapters/${id}/produce`),
  produceChapter: (id: number) => request<ChapterProductionResult>(`/chapters/${id}/produce`, { method: "POST" }),
  sketchPanel: (id: number, body: { seed?: Seed | null } = {}) => request<Job[]>(`/panels/${id}/sketch`, json("POST", body)),
  validateSketch: (id: number, imageId?: number) =>
    request<PanelDetail>(`/panels/${id}/sketch/validate`, json("POST", imageId ? { image_id: imageId } : {})),
  unvalidateSketch: (id: number) => request<PanelDetail>(`/panels/${id}/sketch/validate`, { method: "DELETE" }),
  cleanPanel: (id: number, body: { denoise?: number | null } = {}) => request<Job[]>(`/panels/${id}/clean`, json("POST", body)),
  sketchPage: (id: number) => request<BatchGenerateResult>(`/pages/${id}/sketch`, { method: "POST" }),
  sketchChapter: (id: number) => request<BatchGenerateResult>(`/chapters/${id}/sketch`, { method: "POST" }),
  cleanPage: (id: number) => request<BatchGenerateResult>(`/pages/${id}/clean`, { method: "POST" }),
  cleanChapter: (id: number) => request<BatchGenerateResult>(`/chapters/${id}/clean`, { method: "POST" }),
  pageSketchEstimate: (id: number) => request<SketchEstimate>(`/pages/${id}/sketch-estimate`),
  chapterSketchEstimate: (id: number) => request<SketchEstimate>(`/chapters/${id}/sketch-estimate`),
  upscalers: () => request<Upscaler[]>("/presets/upscalers"),
  finishPanel: (id: number) => request<Job>(`/panels/${id}/finish`, { method: "POST" }),
  finishPage: (id: number) => request<BatchGenerateResult>(`/pages/${id}/finish`, { method: "POST" }),
  finishChapter: (id: number) => request<BatchGenerateResult>(`/chapters/${id}/finish`, { method: "POST" }),
  selectPanelImage: (id: number) => request<PanelImage[]>(`/panel-images/${id}/select`, { method: "POST" }),
  deletePanelImage: (id: number) => request<void>(`/panel-images/${id}`, { method: "DELETE" }),
  /** `character` : « auto » (le seul personnage de la case), « none » (aucun) ou l'id d'un personnage. */
  getRepairInfo: (id: number, target: RepairTarget, character: number | "auto" | "none") =>
    request<RepairInfo>(
      `/panel-images/${id}/repair?target=${target}${
        typeof character === "number" ? `&character_id=${character}` : character === "none" ? "&auto_character=false" : ""
      }`,
    ),
  repairPanelImage: (id: number, body: RepairInput) => request<Job[]>(`/panel-images/${id}/repair`, json("POST", body)),

  getLettering: (pageId: number) => request<PageLettering>(`/pages/${pageId}/lettering`),
  resetLettering: (pageId: number) => request<PageLettering>(`/pages/${pageId}/lettering/reset`, { method: "POST" }),
  updateBubble: (id: number, body: BubbleUpdate) => request<PageLettering>(`/bubbles/${id}`, json("PATCH", body)),
  fitBubble: (id: number, box: BubbleBox) => request<BubbleFit>(`/bubbles/${id}/fit`, json("POST", box)),
  addSfx: (panelId: number, body: { text: string; intensity?: Intensity; x?: number; y?: number }) =>
    request<PageLettering>(`/panels/${panelId}/sfx`, json("POST", body)),
  deleteSfx: (id: number) => request<PageLettering>(`/bubbles/${id}`, { method: "DELETE" }),
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

  journalSettings: () => request<JournalSettings>("/journal/settings"),
  imageJournal: (imageId: number) => request<{ log: GenerationLog | null }>(`/panel-images/${imageId}/journal`),
  judgeImage: (imageId: number, body: VerdictInput) =>
    request<{ log: GenerationLog | null }>(`/panel-images/${imageId}/verdict`, json("POST", body)),
  startAB: (panelId: number, body: ABInput) =>
    request<{ group: string; seed: number; jobs: Job[] }>(`/panels/${panelId}/ab`, json("POST", body)),
  listAB: (panelId: number) => request<ABGroup[]>(`/panels/${panelId}/ab`),
  chooseAB: (group: string, body: { winner: "A" | "B"; reason?: string | null; note?: string; select?: boolean }) =>
    request<ABGroup>(`/ab/${encodeURIComponent(group)}/choice`, json("POST", body)),
  stats: (filter: StatsFilter = {}) => request<Stats>(`/stats${statsQuery(filter)}`),
  statsExportUrl: (format: "csv" | "json", filter: StatsFilter = {}) =>
    engineUrl(`/stats/export${statsQuery(filter, { format })}`),

  listAgents: () => request<AgentSummary[]>("/agents"),
  getAgent: (id: string, projectId?: number | null) => request<AgentDetail>(`/agents/${id}${agentScope(projectId)}`),
  saveAgent: (id: string, projectId: number | null, body: AgentProfileInput) =>
    request<AgentDetail>(`/agents/${id}/profile${agentScope(projectId)}`, json("PUT", body)),
  agentVersions: (id: string, projectId?: number | null) =>
    request<AgentVersion[]>(`/agents/${id}/versions${agentScope(projectId)}`),
  restoreAgentVersion: (id: string, version: number, projectId?: number | null) =>
    request<AgentDetail>(`/agents/${id}/versions/${version}/restore${agentScope(projectId)}`, json("POST", {})),
  resetAgent: (id: string, projectId?: number | null) =>
    request<AgentDetail>(`/agents/${id}/reset${agentScope(projectId)}`, json("POST", {})),
  tryAgent: (id: string, projectId: number | null, body: AgentProfileInput) =>
    request<TrialResult>(`/agents/${id}/trial${agentScope(projectId)}`, json("POST", body)),
  agentExportUrl: (id: string, projectId?: number | null) => engineUrl(`/agents/${id}/export${agentScope(projectId)}`),
  seriesAgents: (projectId: number) => request<SeriesAgentOverride[]>(`/projects/${projectId}/agents`),
  knowledgeStatus: () => request<KnowledgeStatus>("/knowledge/status"),
  listCollections: (projectId?: number) =>
    request<KnowledgeCollection[]>(`/knowledge/collections${projectId ? `?project_id=${projectId}` : ""}`),
  getCollection: (id: number) => request<KnowledgeCollection>(`/knowledge/collections/${id}`),
  createCollection: (body: CollectionInput) =>
    request<KnowledgeCollection>("/knowledge/collections", json("POST", body)),
  updateCollection: (id: number, body: Partial<CollectionInput>) =>
    request<KnowledgeCollection>(`/knowledge/collections/${id}`, json("PATCH", body)),
  deleteCollection: (id: number) => request<void>(`/knowledge/collections/${id}`, { method: "DELETE" }),
  listDocuments: (collectionId: number) =>
    request<KnowledgeDocumentSummary[]>(`/knowledge/collections/${collectionId}/documents`),
  createDocument: (collectionId: number, body: DocumentInput) =>
    request<KnowledgeDocument>(`/knowledge/collections/${collectionId}/documents`, json("POST", body)),
  uploadDocuments: (collectionId: number, files: File[], tags: string[] = []) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("tags", tags.join(","));
    return request<KnowledgeDocument[]>(`/knowledge/collections/${collectionId}/upload`, { method: "POST", body: form });
  },
  getDocument: (id: number) => request<KnowledgeDocument>(`/knowledge/documents/${id}`),
  updateDocument: (id: number, body: Partial<DocumentInput>) =>
    request<KnowledgeDocument>(`/knowledge/documents/${id}`, json("PATCH", body)),
  deleteDocument: (id: number) => request<void>(`/knowledge/documents/${id}`, { method: "DELETE" }),
  reindexKnowledge: () =>
    request<{ documents: number; chunks: number; errors: string[] }>("/knowledge/reindex", { method: "POST" }),
  updateKnowledgePacks: () => request<PackReport[]>("/knowledge/packs/update", { method: "POST" }),
  searchKnowledge: (body: SearchInput) => request<SearchResult>("/knowledge/search", json("POST", body)),
  getBible: (projectId: number) => request<Bible>(`/projects/${projectId}/bible`),
  saveBible: (projectId: number, body: BibleInput) => request<Bible>(`/projects/${projectId}/bible`, json("PUT", body)),
  chapterDialogues: (chapterId: number) => request<DialogueReport>(`/chapters/${chapterId}/dialogues`),
  getPreDirection: (projectId: number) => request<PreDirection>(`/projects/${projectId}/pre-direction`),
  savePreDirection: (projectId: number, overrides: Record<string, DnaValue>) =>
    request<PreDirection>(`/projects/${projectId}/pre-direction`, json("PUT", { overrides })),
  getSeriesCreator: (projectId: number) => request<SeriesCreator>(`/projects/${projectId}/series-creator`),
  proposeSeries: (projectId: number, body: { pitch: string; answers: Record<string, CreatorAnswer> }) =>
    request<CreatorProposal>(`/projects/${projectId}/series-creator/proposal`, json("POST", body)),
  applySeriesProposal: (projectId: number, body: CreatorApply) =>
    request<CreatorApplied>(`/projects/${projectId}/series-creator/apply`, json("POST", body)),
  scriptBrief: (chapterId: number) => request<ScriptBrief>(`/chapters/${chapterId}/script-brief`),
  chapterSources: (chapterId: number, agent = "script") =>
    request<ScriptSources | null>(`/chapters/${chapterId}/sources?agent=${encodeURIComponent(agent)}`),
};

function agentScope(projectId?: number | null): string {
  return projectId ? `?project_id=${projectId}` : "";
}

/** « a, b ,c » → ["a", "b", "c"] (sans doublons ni vides). */
export function parseTags(value: string): string[] {
  return [...new Set(value.split(",").map((t) => t.trim()).filter(Boolean))];
}

/** Lien de téléchargement du ZIP d'un export de chapitre terminé. */
export const exportFileUrl = (jobId: number) => engineUrl(`/exports/${jobId}/file`);
/** Aperçu PNG d'une face de la couverture (rendu de l'export, réduit) ; `revision` : clé de cache. */
export const compositionPreviewUrl = (volumeId: number, part: CoverPart, revision: string, width = 640) =>
  engineUrl(`/volumes/${volumeId}/composition/${part}.png?width=${width}&v=${revision}`);

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
