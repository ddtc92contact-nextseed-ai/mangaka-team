"""Schémas d'entrée/sortie de l'API REST."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
PresetId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Direction = Literal["ltr", "rtl"]
SeriesStatusName = Literal["ongoing", "paused", "completed", "cancelled"]
ChapterStatusName = Literal["draft", "script", "layout", "generation", "lettering", "ready", "published"]
PageKindName = Literal["story", "bonus", "chapter_cover"]
BubbleKindName = Literal["speech", "thought", "shout", "narration", "off"]
QCVerdictName = Literal["ok", "review", "reject"]
LoraName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]
LoraWeight = Annotated[float, Field(ge=0, le=2)]
LoraTriggers = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
IntensityName = Literal["calme", "normal", "choc"]
RythmeName = Literal["lent", "normal", "rapide"]
FrameKindName = Literal["border", "none", "fade"]
# Débruitage du passage au propre (palier croquis) : 0 = croquis inchangé, 1 = image neuve.
Denoise = Annotated[float, Field(ge=0.05, le=1)]
ImageKindName = Literal["final", "croquis"]
# Passage au propre : image → image depuis le croquis (débruitage) ou ControlNet (composition verrouillée).
CleanModeName = Literal["img2img", "controlnet"]
ControlTypeId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
# Force du patch ControlNet : 0 = contrôle ignoré, 1 = composition tenue (défaut), jusqu'à 2.
ControlStrength = Annotated[float, Field(ge=0, le=2)]
# CFG des cases (Qwen-Image 2.1) : 1 = négatif inactif ; au-delà de 3, l'image se dégrade.
Cfg = Annotated[float, Field(ge=1, le=3)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Séries (table « projects ») ---------------------------------------------
# Réglages fins du style (presets/style_options.yaml) : réglage → choix ; aucun texte libre.
StyleOptionsIn = Annotated[dict[PresetId, PresetId], Field(max_length=20)]


class ProjectCreate(_In):
    title: Title
    # Packs de style (listes fermées des presets), obligatoires : plus aucun style en texte libre.
    style_genre: PresetId
    style_rendering: PresetId
    style_tone: PresetId
    style_options: StyleOptionsIn = Field(default_factory=dict)
    status: SeriesStatusName = "ongoing"
    # Absent : sens de lecture du genre.
    reading_direction: Direction | None = None
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None
    style_lora_name: LoraName | None = None
    # Absent : poids conseillé du catalogue style_loras.yaml (0,8 hors catalogue).
    style_lora_weight: LoraWeight | None = None
    # Absent : style suggéré par le genre (jamais « sage »), sinon `layout_style` de presets/defaults.yaml.
    layout_style: PresetId | None = None
    # Polices des bulles de parole et des cris (fonts.yaml) ; absentes : celles du genre.
    dialogue_font: PresetId | None = None
    shout_font: PresetId | None = None
    # Absent : `sketch_enabled` de presets/defaults.yaml (activé).
    sketch_enabled: bool | None = None
    sketch_denoise: Denoise | None = None
    clean_mode: CleanModeName = "img2img"
    clean_control: ControlTypeId | None = None  # null : type par défaut du preset ControlNet
    # Agrandisseur de la finition d'impression (None : celui de defaults.yaml).
    upscaler: PresetId | None = None
    # CFG des cases (1 à 3) ; absent : celui du palier. Refusé au-delà de 1 pour un palier distillé (Turbo).
    cfg: Cfg | None = None
    # « Prompt rédigé par l'IA » ; absent : `enabled` de presets/prompts/redacteur-image.yaml (oui).
    ai_prompt: bool | None = None
    # « Cohérence anime » : LoRA d'identité de presets/camera_loras.yaml (palier Qualité) ; non par défaut.
    anime_consistency: bool = False


class ProjectUpdate(_In):
    title: Title | None = None
    style_genre: PresetId | None = None
    style_rendering: PresetId | None = None
    style_tone: PresetId | None = None
    style_options: StyleOptionsIn | None = None
    status: SeriesStatusName | None = None
    reading_direction: Direction | None = None
    page_format: PresetId | None = None
    workflow_preset: PresetId | None = None
    style_lora_name: LoraName | None = None
    style_lora_weight: LoraWeight | None = None
    layout_style: PresetId | None = None
    dialogue_font: PresetId | None = None
    shout_font: PresetId | None = None
    sketch_enabled: bool | None = None
    sketch_denoise: Denoise | None = None  # null : `denoise` du preset « propre »
    clean_mode: CleanModeName | None = None
    clean_control: ControlTypeId | None = None  # null : type par défaut du preset ControlNet
    upscaler: PresetId | None = None  # null : revient à l'agrandisseur de defaults.yaml
    cfg: Cfg | None = None  # null : CFG du palier ; > 1 refusé pour un palier distillé (Turbo)
    ai_prompt: bool | None = None  # « Prompt rédigé par l'IA » (false : assemblage par fragments)
    anime_consistency: bool | None = None  # « Cohérence anime » (LoRA d'identité, palier Qualité)
    # false : masque la note « série passée en sage par une ancienne mise à jour » (seule valeur admise).
    layout_style_notice: Literal[False] | None = None


class ProjectOut(BaseModel):
    id: int
    title: str
    slug: str  # dossier de la série dans ComfyUI : mangaka/<slug>/
    # Ancien style libre (lecture seule) ; ignoré dès qu'un pack est choisi.
    legacy_style: str
    style_genre: str | None
    style_rendering: str | None
    style_tone: str | None
    style_options: dict[str, str]
    # Noms des packs (« Seinen · N&B à trames · Dark ») et `$style` composé pour les prompts image.
    style_label: str
    style_prompt: str
    status: SeriesStatusName
    reading_direction: Direction
    page_format: str
    workflow_preset: str
    style_lora_name: str | None
    style_lora_weight: float
    # Mots déclencheurs du catalogue (style_loras.yaml) ; `style_lora_in_catalog` faux : appliqué sans.
    style_lora_trigger_words: list[str]
    style_lora_in_catalog: bool
    layout_style: str
    dialogue_font: str | None = None
    shout_font: str | None = None
    sketch_enabled: bool = True
    sketch_denoise: float | None = None
    clean_mode: CleanModeName = "img2img"
    clean_control: str | None = None
    upscaler: str | None = None
    cfg: float | None = None  # null : celui du palier
    ai_prompt: bool = False
    anime_consistency: bool = False
    # Pourquoi « Cohérence anime » ne s'applique pas au palier de la série (« Disponible en palier Qualité »).
    anime_consistency_problem: str | None = None
    character_count: int
    chapter_count: int
    # Pages déjà mises en page : changer le sens de lecture les recalcule (confirmation dans l'UI).
    laid_out_page_count: int = 0
    # Pages non générées (aucune image, croquis compris) qu'un changement de style peut remettre en page.
    relayout_page_count: int = 0
    # Série passée en « sage » par la migration v8 (pas par l'utilisateur) : note unique de la fiche série.
    layout_style_notice: bool = False
    created_at: datetime
    updated_at: datetime


class LibraryOut(BaseModel):
    """Résultat de « Reconstruire la bibliothèque » (copie lisible de la série dans ComfyUI/output/mangaka/)."""

    enabled: bool  # False : dossier ComfyUI inconnu, rien d'écrit (voir `warning`)
    folder: str | None = None  # output/mangaka/<série> (relatif au dossier de ComfyUI)
    path: str | None = None  # chemin complet sur le disque
    written: int = 0  # fichiers écrits ou remplacés
    removed: int = 0  # fichiers retirés (plus retenus)
    removed_dirs: int = 0  # dossiers vides retirés
    warning: str | None = None


class OrphanFolderRef(BaseModel):
    area: Literal["output", "input"]
    name: str = Field(min_length=1, max_length=255)


class OrphanFolderOut(OrphanFolderRef):
    """Dossier de ComfyUI/<area>/mangaka/ qui n'est à aucune série de la base."""

    files: int  # nombre de fichiers dedans (0 : dossier vide)


class OrphansOut(BaseModel):
    """Aperçu de « Ranger le dossier ComfyUI » : dossiers à déplacer dans mangaka/old/orphelins-<date>/."""

    enabled: bool  # False : COMFYUI_DIR invalide ou refusé (voir `warning`), rangement désactivé
    path: str | None = None  # dossier de ComfyUI
    archive: str | None = None  # old/orphelins-<date> (sous output/mangaka/ et input/mangaka/)
    orphans: list[OrphanFolderOut] = []
    warning: str | None = None


class TidyIn(BaseModel):
    """Dossiers confirmés (ceux de l'aperçu) ; un dossier devenu une série entre-temps n'est pas déplacé."""

    folders: list[OrphanFolderRef] = Field(default_factory=list, max_length=10000)


class TidyOut(BaseModel):
    """Résultat de « Ranger le dossier ComfyUI »."""

    enabled: bool
    moved: list[str] = []  # chemins d'arrivée, relatifs au dossier de ComfyUI
    removed_empty: int = 0  # dossiers vides retirés des séries connues
    warning: str | None = None


class CleanupOut(BaseModel):
    """Résultat de « Nettoyer les variantes non retenues »."""

    variants_deleted: int  # variantes non gardées effacées (fiches et essais de la planche de style)
    comfyui_folders_removed: list[str]  # dossiers de transit vidés dans ComfyUI (relatifs à ComfyUI)
    comfyui_cleaned: bool  # False : dossier ComfyUI inconnu ou générations en cours (voir `warning`)
    warning: str | None = None


class ResetIn(BaseModel):
    """« Remettre l'atelier à zéro » : le mot RÉINITIALISER tapé, et le mode « tout »."""

    confirm: str
    all: bool = False  # aussi les réglages globaux des agents et le savoir-faire (remis par défaut)


class ResetOut(BaseModel):
    backup: str  # dossier de la sauvegarde (data/backups/reset-<date-heure>/)
    all: bool
    series_deleted: int
    data_removed: list[str]  # éléments effacés dans data/
    comfyui_removed: list[str]  # dossiers effacés dans ComfyUI (relatifs à ComfyUI ; old/ jamais)
    comfyui_warning: str | None = None  # ComfyUI non nettoyé (COMFYUI_DIR absent ou introuvable)


class RelayoutOut(BaseModel):
    relaid_page_ids: list[int]  # pages remises en page (sans aucune image)
    kept_pages: int  # pages avec des cases déjà générées (ou en cours) : inchangées


# --- Chapitres ------------------------------------------------------------------
Synopsis = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]
PageCount = Annotated[int, Field(ge=1, le=60)]


class ChapterCreate(_In):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    number: Annotated[int, Field(ge=1, le=100000)] | None = None
    synopsis: Synopsis = ""
    target_page_count: PageCount = 15
    status: ChapterStatusName = "draft"
    planned_date: date | None = None


class ChapterUpdate(_In):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    synopsis: Synopsis | None = None
    summary: Synopsis | None = None
    target_page_count: PageCount | None = None
    status: ChapterStatusName | None = None
    planned_date: date | None = None


class ChapterReorder(_In):
    chapter_ids: list[int] = Field(min_length=1)


class ChapterOut(BaseModel):
    id: int
    project_id: int
    series_title: str
    number: int
    title: str
    synopsis: str
    summary: str
    target_page_count: int
    status: ChapterStatusName
    planned_date: date | None
    page_count: int
    panel_count: int
    created_at: datetime
    updated_at: datetime


# --- Découpage (pages → cases → bulles) ---------------------------------------
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class BubbleIn(_In):
    id: int | None = None  # les bulles sont recréées ; l'id ne sert qu'à garder leur position de lettrage
    speaker: Short = ""
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    kind: BubbleKindName = "speech"


SfxText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class SfxIn(_In):
    id: int | None = None  # recréées comme les bulles ; l'id garde leurs réglages de lettrage
    text: SfxText
    intensity: IntensityName | None = None


MAX_PANEL_OBJECTS = 8


SceneText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1500)]


ViewpointMode = Literal["reaction", "subjective"]


class ViewpointIn(_In):
    """Point de vue d'un spectateur : « reaction » (plan de réaction, le spectateur est dessiné) ou
    « subjective » (vue subjective, le spectateur reste hors cadre)."""

    mode: ViewpointMode
    spectators: Annotated[list[Short], Field(min_length=1, max_length=12)]


class ViewpointOut(BaseModel):
    mode: ViewpointMode
    spectators: list[str] = Field(default_factory=list)
    # direction (choisi par la direction artistique) | défaut (l'agent n'a rien choisi) | auteur
    source: str = "direction"


class CardRef(BaseModel):
    id: int
    name: str


class NameNoteOut(BaseModel):
    """Nom de personnage lu dans une case qui demande l'avis de l'auteur (pipeline/names.py)."""

    name: str  # tel qu'écrit dans la case
    source: Literal["image", "hors cadre", "bulle", "description", "mise en scène"]
    # ambigu : plusieurs fiches à égalité, la première retenue ; sans fiche : aucune ; non déclaré : nommé
    # par le texte sans être ni présent ni hors cadre (dessiné sans sa référence) ; hors cadre en action : déclaré
    # hors cadre alors que la description ou la mise en scène lui donne une action visible.
    kind: Literal["ambigu", "sans fiche", "non déclaré", "hors cadre en action"]
    chosen: list[CardRef] = Field(default_factory=list)  # fiche(s) retenue(s) ; vide : aucune
    candidates: list[CardRef] = Field(default_factory=list)  # fiches à égalité (nom ambigu)
    message: str


class PanelIn(_In):
    id: int | None = None
    description: LongText = ""
    # Lieu et mise en scène (scénario) : absents = gardés tels quels.
    setting: SceneText | None = None
    staging: SceneText | None = None
    # Personnages présents à l'image ; `offscreen_characters` : cités hors cadre (absent = gardés tels quels).
    characters: Annotated[list[Short], Field(max_length=20)] = Field(default_factory=list)
    offscreen_characters: Annotated[list[Short], Field(max_length=20)] | None = None
    shot_type: str | None = None
    importance: Annotated[int, Field(ge=1, le=3)] = 2
    intensity: IntensityName | None = None
    dialogues: Annotated[list[BubbleIn], Field(max_length=12)] = Field(default_factory=list)
    # Onomatopées : absent = celles de la case sont gardées telles quelles.
    sfx: Annotated[list[SfxIn], Field(max_length=8)] | None = None
    # Bibliothèque de la série (ids) : absent = gardés tels quels ; decor null = pas de décor.
    decor: int | None = None
    objets: Annotated[list[int], Field(max_length=MAX_PANEL_OBJECTS)] | None = None
    # Lieu de la série (id, unité de lieu) : absent = gardé tel quel ; null = aucun lieu.
    location: int | None = None


class PageIn(_In):
    id: int | None = None
    kind: PageKindName = "story"
    rythme: RythmeName | None = None
    panels: Annotated[list[PanelIn], Field(max_length=9)] = Field(default_factory=list)


class BreakdownIn(_In):
    pages: Annotated[list[PageIn], Field(max_length=80)]


class BubbleOut(BaseModel):
    id: int
    speaker: str
    text: str
    kind: BubbleKindName


class SfxOut(BaseModel):
    id: int
    text: str
    intensity: IntensityName | None = None


class PanelFrameIn(_In):
    """Options de cadre imposées à une case ; null (ou absent) = décidée par le style de mise en page."""

    frame: FrameKindName | None = None
    # Déborder sur les cases voisines (toujours dans la zone utile de la page).
    break_out: bool | None = None
    inset: bool | None = None


class PanelCropIn(_In):
    """Cadrage manuel de l'image dans la case : centre de la fenêtre (fraction de l'image, 0–1) et zoom sur
    le remplissage (1 = l'image remplit tout juste la case)."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    zoom: float = Field(ge=1, le=4)


class PanelCropOut(BaseModel):
    x: float
    y: float
    zoom: float


class PrintInfoOut(BaseModel):
    """Dpi effectif de la version retenue à l'impression (finition d'impression)."""

    image_id: int
    status: Literal["ok", "finished", "low"]  # au dpi cible · finalisée · sous le seuil
    target_dpi: int  # dpi du format de page
    min_dpi: int  # seuil : finishing_tolerance × dpi cible
    box_width: int  # boîte imprimée (px au dpi cible, fond perdu compris)
    box_height: int
    width_mm: float
    height_mm: float
    source_width: int
    source_height: int
    dpi: int  # dpi effectif de la version retenue
    factor: float  # agrandissement nécessaire pour atteindre le dpi cible
    target_width: int  # taille finale de la finition
    target_height: int
    needed: bool
    finished: bool
    finished_dpi: int | None = None
    finished_width: int | None = None
    finished_height: int | None = None
    finished_upscaler: str | None = None


class PanelOut(BaseModel):
    id: int
    index: int
    description: str
    setting: str = ""  # précision de cadrage du lieu : moment, coin du lieu, éléments du décor
    staging: str = ""  # mise en scène : qui fait quoi, où dans le cadre
    characters: list[str]  # présents à l'image (dessinés, avec leur image de référence)
    # Noms de `characters` qui ne désignent aucune fiche personnage (ni nom, ni alias, ni nom partiel) :
    # sans référence, sans description ni LoRA pour la génération — à rattacher à une fiche.
    unmatched_characters: list[str] = Field(default_factory=list)
    # Noms ambigus, sans fiche ou cités sans être déclarés : à signaler à l'auteur (jamais perdus en silence).
    name_notes: list[NameNoteOut] = Field(default_factory=list)
    # Cités par la case mais hors cadre : jamais dessinés ni pourvus d'image de référence.
    offscreen_characters: list[str] = Field(default_factory=list)
    viewpoint: ViewpointOut | None = None
    decor: int | None = None  # décor de la bibliothèque (id)
    objets: list[int] = Field(default_factory=list)  # objets de la bibliothèque (ids)
    location: int | None = None  # lieu de la série (id) ; `setting` en est la précision de cadrage
    location_name: str | None = None
    shot_type: str | None
    importance: int
    intensity: IntensityName | None = None
    dialogues: list[BubbleOut]
    sfx: list[SfxOut] = Field(default_factory=list)
    # Options de cadre imposées dans l'UI (les options effectives sont dans layout.panels).
    frame: PanelFrameIn | None = None
    # Cadrage manuel de l'image (None = centrée au remplissage) et zoom maximal permis par l'image montrée.
    crop: PanelCropOut | None = None
    crop_max_zoom: float | None = None
    bbox: dict[str, int] | None
    bubble_zone: dict[str, int] | None
    state: str = "draft"
    final_prompt: str | None = None
    final_prompt_manual: bool = False
    generation_preset: str | None = None
    image_count: int = 0  # versions propres (les croquis sont comptés à part)
    selected_image_id: int | None = None
    selected_image_url: str | None = None
    # Palier croquis : nombre de croquis, croquis montré (validé, sinon le plus récent), validation.
    sketch_count: int = 0
    sketch_image_id: int | None = None
    sketch_image_url: str | None = None
    sketch_validated: bool = False
    sketch_denoise: float | None = None
    # Version propre déjà tirée du croquis validé.
    sketch_cleaned: bool = False
    # Composition verrouillée (ControlNet) : type de contrôle du verrou, None = composition libre.
    composition_lock: str | None = None
    # QC de la version choisie (None : pas encore contrôlée).
    qc_verdict: QCVerdictName | None = None
    qc_score: int | None = None
    qc_reasons: list[str] = Field(default_factory=list)
    qc_override: bool = False  # verdict forcé à ok par un humain
    detections: dict[str, Any] | None = None  # boîtes de la version choisie
    # Le ratio de la case s'écarte trop de celui de l'image retenue (seuil : presets/layout.yaml).
    regeneration_advised: bool = False
    # Dpi de la version retenue à l'impression (None : pas de version retenue ou pas de mise en page).
    print_info: PrintInfoOut | None = None
    # Dernière génération de la case (tous jobs confondus, sans limite) : pour afficher un échec et son erreur.
    last_job_id: int | None = None
    last_job_status: str | None = None
    last_job_error: str | None = None


class DialogueStatsOut(BaseModel):
    panels: int
    replies: int  # répliques hors onomatopées
    sfx: int
    per_panel: float
    mean_words: float
    inner_voice: int  # pensées, voix off, narrations
    sfx_only: int  # cases dont la seule bulle est une onomatopée


class DialogueReportOut(BaseModel):
    """Densité des dialogues d'un chapitre et règles (`dialogue_rules`) encore enfreintes."""

    stats: DialogueStatsOut
    warnings: list[str]


class PageOut(BaseModel):
    id: int
    chapter_id: int
    number: int
    kind: PageKindName
    grid_template: str | None
    layout_style: str | None = None  # style imposé à la page (None = celui de la série)
    layout_seed: int | None = None
    rythme: RythmeName | None = None
    state: str
    layout: dict[str, Any] | None
    layout_stale: bool
    # Name (palier croquis, pipeline/name_board.py) : validée, caduque (case modifiée depuis la validation) ou
    # à valider ; None sans palier croquis (ou page sans case).
    name_state: Literal["validated", "stale", "pending"] | None = None
    name_validated_at: datetime | None = None
    panels: list[PanelOut]
    # Scène du chapitre (étape Scènes) ; None : page bonus, ou chapitre écrit sans scènes.
    scene_id: int | None = None


class PageLayoutIn(_In):
    # Absent = garder le gabarit actuel ; null = choix automatique ; sinon gabarit imposé.
    template_id: PresetId | None = None
    # Absent = garder ; null = style de la série ; sinon style imposé à cette page.
    style: PresetId | None = None
    # True : « Nouvelle mise en page » (nouvelle graine, autre gabarit si possible).
    reroll: bool = False


FinitePx = Annotated[float, Field(allow_inf_nan=False)]


class CutSlant(_In):
    """Incline une découpe : positions (px de la page, le long de l'axe découpé) de ses deux extrémités."""

    path: Annotated[list[Annotated[int, Field(ge=0)]], Field(max_length=10)]
    index: Annotated[int, Field(ge=0)]
    ends: Annotated[list[FinitePx], Field(min_length=2, max_length=2)]


class GutterMove(_In):
    path: Annotated[list[Annotated[int, Field(ge=0)]], Field(max_length=10)]
    index: Annotated[int, Field(ge=0)]
    position: FinitePx


# --- Lettrage (étape 5) ------------------------------------------------------
Coord = Annotated[int, Field(ge=-100000, le=100000)]
Extent = Annotated[int, Field(ge=20, le=100000)]


class BubbleBox(_In):
    x: Coord
    y: Coord
    w: Extent
    h: Extent


class TailPoint(_In):
    x: Coord
    y: Coord


class SfxParams(_In):
    """Réglages d'une onomatopée (écran Lettrage) : une clé envoyée à null rend la valeur au calcul automatique."""

    intensity: IntensityName | None = None
    font: PresetId | None = None
    size_pt: Annotated[float, Field(ge=4, le=300, allow_inf_nan=False)] | None = None
    angle: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)] | None = None
    skew: Annotated[float, Field(ge=-45, le=45, allow_inf_nan=False)] | None = None
    # Centre (px de la page) placé à la main ; x et y vont ensemble.
    x: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None
    y: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None


class BubbleUpdate(_In):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    kind: BubbleKindName | None = None
    speaker: Short | None = None
    # Cadre / pointe ajustés à la main ; null = placement automatique.
    position: BubbleBox | None = None
    tail: TailPoint | None = None
    # Taille du texte saisie à la main (pt) ; null = automatique (remplit un cadre ajusté à la main).
    size_pt: Annotated[float, Field(ge=4, le=72, allow_inf_nan=False)] | None = None
    # Onomatopée seulement.
    sfx: SfxParams | None = None


class SfxCreate(_In):
    text: SfxText
    intensity: IntensityName = "normal"
    x: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None
    y: Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)] | None = None


class RenderIn(_In):
    bleed: bool = False
    crop_marks: bool = False


class ExportIn(_In):
    bleed: bool = False
    crop_marks: bool = False


# --- Jobs ----------------------------------------------------------------------
class JobOut(BaseModel):
    id: int
    step: str
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    progress: int
    message: str
    error: str | None
    project_id: int | None
    chapter_id: int | None
    panel_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


# --- Génération (étape 3) ------------------------------------------------------
MAX_SEED = 2**63 - 1
VariantCount = Annotated[int, Field(ge=1, le=4)]
FinalPrompt = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]


class ComfyTrialIn(_In):
    preset: PresetId | None = None  # null : workflow par défaut des séries


AngleId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
CameraLoraId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class ChangeAngleIn(_In):
    """« Changer l'angle » d'une case : la version `source_image_id` (la version choisie par défaut) vue sous
    l'angle `angle` (presets/camera_loras.yaml), LoRA Multiple-Angles `lora` (celui par défaut) au poids `weight`."""

    angle: AngleId
    source_image_id: int | None = None
    lora: CameraLoraId | None = None
    weight: LoraWeight | None = None
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None


class GenerateIn(_In):
    count: VariantCount = 1
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None
    preset: PresetId | None = None
    prompt_override: FinalPrompt | None = None


RepairTarget = Literal["face", "hand", "zone"]


class RepairRegionIn(_In):
    """Rectangle à repeindre, en px de l'image de la version (détection du QC ou rectangle tracé)."""

    x1: Annotated[float, Field(ge=0, le=100_000)]
    y1: Annotated[float, Field(ge=0, le=100_000)]
    x2: Annotated[float, Field(ge=0, le=100_000)]
    y2: Annotated[float, Field(ge=0, le=100_000)]
    # Une boîte de `PanelImage.detections` peut être renvoyée telle quelle (score et étiquette ignorés).
    score: float | None = None
    label: Annotated[str, StringConstraints(max_length=40)] | None = None


class RepairIn(_In):
    """Réparation ciblée d'une version : zone (rectangles et/ou masque peint), prompt et réglages."""

    regions: Annotated[list[RepairRegionIn], Field(max_length=50)] = Field(default_factory=list)
    # Masque peint : PNG en base64 (data URL acceptée), blanc ou opaque = à repeindre ; redimensionné.
    mask_png: Annotated[str, StringConstraints(max_length=20_000_000)] | None = None
    target: RepairTarget = "zone"
    character_id: int | None = None
    prompt: FinalPrompt | None = None
    grow_px: Annotated[int, Field(ge=0, le=256)] | None = None
    feather_px: Annotated[int, Field(ge=0, le=128)] | None = None
    denoise: Annotated[float, Field(ge=0.05, le=1)] | None = None
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None


class RepairCharacterOut(BaseModel):
    id: int
    name: str


class RepairInfoOut(BaseModel):
    """Préremplissage de la fenêtre « Réparer » : preset, réglages par défaut, prompt, personnages."""

    available: bool
    problem: str | None = None  # pourquoi la réparation est impossible (croquis, preset manquant…)
    preset: str | None = None
    preset_name: str | None = None
    tier: str | None = None
    grow_px: int = 0
    feather_px: int = 0
    denoise: float = 0.45
    target: RepairTarget = "zone"
    character_id: int | None = None
    characters: list[RepairCharacterOut] = Field(default_factory=list)
    prompt: str = ""


class BatchGenerateIn(_In):
    force: bool = False
    count: VariantCount = 1
    preset: PresetId | None = None


class BatchGenerateOut(BaseModel):
    jobs: list[JobOut]
    panel_ids: list[int]
    skipped: int


ProductionModeName = Literal["sketch", "final"]


class ChapterProductionPlanOut(BaseModel):
    """« Générer le chapitre » (pages de l'histoire et bonus) : ce qu'un clic mettra en file."""

    mode: ProductionModeName  # sketch : croquis d'abord (palier croquis de la série), final : versions finales
    panels: int  # cases à croquer (sketch) ou à générer (final)
    to_clean: int  # sketch : croquis validés à passer au propre
    pages: int  # pages concernées
    unlaid_pages: list[int]  # numéros des pages mises en page juste avant la génération
    total: int  # cases des pages de l'histoire et bonus


class ChapterProductionOut(BaseModel):
    mode: ProductionModeName
    jobs: list[JobOut]
    panel_ids: list[int]  # cases croquées (sketch) ou générées (final)
    cleaned_panel_ids: list[int]  # sketch : cases passées au propre depuis leur croquis validé
    laid_out_pages: list[int]
    skipped: int


class PanelImageOut(BaseModel):
    id: int
    panel_id: int
    version: int
    kind: ImageKindName = "final"  # croquis : jamais choisi, assemblé ni exporté
    url: str
    seed: int | None
    selected: bool
    width: int | None
    height: int | None
    preset: str | None
    tier: str | None = None  # palier du preset qui a produit la version (Turbo, Rapide, Qualité)
    params: dict[str, Any]
    qc_score: int | None
    qc_reasons: list[str]
    qc_verdict: QCVerdictName | None = None
    # Détail du dernier QC : couches (statut, score, durée, raisons), décision humaine, historique.
    qc: dict[str, Any] = Field(default_factory=dict)
    # Boîtes détectées en px de l'image : {"width", "height", "faces": [...], "hands": [...], "text": [...]}.
    detections: dict[str, Any] | None = None
    # Jugement humain « bonne / mauvaise » (banc d'essai du QC), indépendant du verdict QC.
    annotation: AnnotationOut | None = None
    # Finition d'impression de la version (image agrandie dérivée) : taille, agrandisseur, dpi…
    finish: dict[str, Any] | None = None
    created_at: datetime


class UpscalerOut(BaseModel):
    id: str
    name: str
    description: str
    model_scale: float | None
    high_fidelity: bool
    is_default: bool
    estimated_s: float | None
    timeout_s: float


class FinishBatchOut(BaseModel):
    jobs: list[JobOut]
    panel_ids: list[int]
    skipped: int  # cases déjà au dpi cible, déjà finalisées, sans version ou déjà en file


class PageFinishingOut(BaseModel):
    page_id: int
    upscaler: str | None  # nom de l'agrandisseur de la série
    panels: dict[int, PrintInfoOut | None]
    active_jobs: list[JobOut]


class PanelUpdate(_In):
    # final_prompt : texte = édition manuelle conservée ; null ou "" = revenir au prompt automatique.
    final_prompt: FinalPrompt | None = None
    # generation_preset : null = choix automatique.
    generation_preset: PresetId | None = None
    # Description de la case (tri des croquis : « modifier la description puis re-croquer »).
    description: LongText | None = None
    # Lieu et mise en scène de la case (prompt image : « Lieu : … », « Mise en scène : … »).
    setting: SceneText | None = None
    staging: SceneText | None = None
    # Qui est dans l'image : présents (`characters`) et cités hors cadre (`offscreen_characters`) ; un nom
    # dans les deux listes est présent.
    characters: Annotated[list[Short], Field(max_length=20)] | None = None
    offscreen_characters: Annotated[list[Short], Field(max_length=20)] | None = None
    # Point de vue d'un spectateur, choisi par l'auteur (jamais écrasé par la direction artistique) : range
    # les spectateurs hors cadre (vue subjective) ou à l'image (plan de réaction) ; null = aucun.
    viewpoint: ViewpointIn | None = None
    # « Laisser hors cadre » : fiches (ids) gardées hors cadre malgré une action visible dans le texte (liste
    # complète) ; leur action est retirée du prompt image et l'alerte disparaît.
    offscreen_kept: Annotated[list[int], Field(max_length=20)] | None = None
    # Débruitage du passage au propre de cette case ; null = celui de la série (sinon du preset).
    sketch_denoise: Denoise | None = None
    # Plan de la case (planche brouillon : « changer le plan ») ; null = aucun. L'emporte sur celui de la
    # direction artistique appliquée (gardé comme un choix du dialogue avec l'IA).
    shot_type: Short | None = None


DialogInstruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class PanelDialogIn(_In):
    """Consigne de l'auteur sur une case (« gros plan sur le visage de Lucius, en contre-plongée »)."""

    instruction: DialogInstruction


class RebuildPromptIn(_In):
    """« Reconstruire le prompt » ; `instruction` (facultative) : consigne passée au même pipeline que le
    dialogue sur la case, sans historique."""

    instruction: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class DialogApplyIn(_In):
    # True : « Appliquer et générer » (une nouvelle version de cette case seulement).
    generate: bool = False


class DialogChangeOut(BaseModel):
    field: str  # plan | angle | action | ambiance | reference.<id du personnage>
    label: str  # « Plan », « Référence de Lucius »
    before: str | None = None
    after: str | None = None


class PanelDialogTurnOut(BaseModel):
    id: int
    panel_id: int
    instruction: str
    explanation: str
    status: Literal["proposed", "applied", "cancelled"]
    prompt_before: str | None = None
    prompt_after: str
    changes: list[DialogChangeOut] = Field(default_factory=list)
    created_at: datetime
    applied_at: datetime | None = None


class CompositionLockIn(_In):
    """« Verrouiller la composition » depuis le croquis validé ou une version de la case."""

    source: Literal["croquis", "version"]
    image_id: int | None = None  # croquis : null = le croquis validé ; version : obligatoire
    type: ControlTypeId | None = None  # null : type par défaut du preset ControlNet
    strength: ControlStrength | None = None  # null : force par défaut du preset


class CompositionLockUpdate(_In):
    type: ControlTypeId | None = None
    strength: ControlStrength | None = None


class ControlPreviewOut(BaseModel):
    status: Literal["none", "pending", "running", "ready", "failed", "cancelled"]
    url: str | None = None  # dernière carte produite (peut être celle d'un type précédent pendant le calcul)
    type: str | None = None  # type de la carte affichée (peut différer du type du verrou pendant un recalcul)
    type_name: str | None = None
    job_id: int | None = None
    error: str | None = None
    width: int | None = None
    height: int | None = None


class CompositionLockOut(BaseModel):
    source: Literal["croquis", "version", "import"]
    source_label: str  # « croquis v2 », « version 3 », « image importée »
    image_id: int | None = None
    version: int | None = None
    source_url: str
    type: str
    type_name: str
    strength: float
    locked_at: str | None = None
    preset: str | None = None  # preset ControlNet des prochaines générations
    preset_name: str | None = None
    problem: str | None = None  # le palier de la case ne propose pas de ControlNet…
    preview: ControlPreviewOut


class LibraryRef(BaseModel):
    """Élément de la bibliothèque cité par une case (personnage, objet, décor, véhicule ou créature)."""

    id: int
    kind: Literal["character", "object", "decor", "vehicle", "creature"]
    name: str


class PanelDetailOut(BaseModel):
    id: int
    page_id: int
    page_number: int
    chapter_id: int
    project_id: int
    index: int
    label: str
    description: str
    setting: str = ""
    staging: str = ""
    characters: list[str]
    character_ids: list[int]
    unmatched_characters: list[str] = Field(default_factory=list)  # voir PanelOut
    name_notes: list[NameNoteOut] = Field(default_factory=list)  # voir PanelOut
    offscreen_characters: list[str] = Field(default_factory=list)  # voir PanelOut
    # Fiches laissées hors cadre par l'auteur malgré une action visible (« Laisser hors cadre ») : plus d'alerte,
    # et l'action est retirée du prompt image.
    offscreen_kept: list[int] = Field(default_factory=list)
    viewpoint: ViewpointOut | None = None
    # Personnages que le texte met en spectateur (« voient », « regarde »…) : la case attend un point de vue.
    spectator_hints: list[str] = Field(default_factory=list)
    perception: str = ""  # verbe de perception repéré (« voient »)
    decor: LibraryRef | None = None
    objets: list[LibraryRef] = Field(default_factory=list)
    shot_type: str | None
    # Cadrage suivi par la génération (prompt, fiches de savoir-faire, vue de référence) : plan et angle, et
    # leur source — « direction » (direction artistique appliquée), « dialogue » (dialogue avec l'IA),
    # « scenario » (repli sur le plan du scénario, sans direction appliquée : `framing_note` dit pourquoi),
    # « none » (aucun plan).
    framing_plan: str | None = None
    framing_angle: str | None = None
    framing_source: Literal["direction", "dialogue", "scenario", "none"] = "none"
    framing_note: str | None = None
    state: str
    bbox: dict[str, int] | None
    final_prompt: str | None
    final_prompt_manual: bool
    # Ce que le dialogue avec l'IA impose à la case (« Plan : gros plan », « Référence de Lucius : … »),
    # gardé jusqu'à « Reconstruire le prompt ».
    dialog_overrides: list[str] = Field(default_factory=list)
    # Origine du prompt automatique : "ia" (rédigé par le LLM) | "fragments" ; `ai_prompt` : réglage de la
    # série ; `prompt_pending` : sera rédigé par l'IA à la prochaine génération (ou « Reconstruire ») ;
    # `prompt_warning` : rédaction en échec, repli par fragments.
    prompt_source: Literal["ia", "fragments"] | None = None
    ai_prompt: bool = False
    prompt_pending: bool = False
    prompt_warning: str | None = None
    # « Sources utilisées » du prompt actuel : savoir-faire reçu par le rédacteur et date de la rédaction.
    prompt_sources: PromptSourcesOut | None = None
    generation_preset: str | None
    resolved_preset: str | None
    target: dict[str, int] | None
    images: list[PanelImageOut]
    active_jobs: list[JobOut]
    sketch_image_id: int | None = None  # croquis validé
    sketch_denoise: float | None = None
    print_info: PrintInfoOut | None = None
    upscaler: str | None = None  # agrandisseur de la finition (nom), None si aucun configuré
    composition_lock: CompositionLockOut | None = None  # None : composition libre


class QueueItemOut(BaseModel):
    job: JobOut
    position: int  # 0 = en cours, 1 = prochain…
    label: str
    panel_id: int | None
    panel_index: int | None
    page_id: int | None
    page_number: int | None
    chapter_id: int | None
    chapter_number: int | None
    chapter_title: str | None
    project_id: int | None
    series_title: str | None
    preset: str | None
    tier: str | None = None  # palier du preset (« Turbo », « Rapide », « Qualité »)
    variant: int | None
    count: int | None
    estimated_duration_s: float | None  # médiane des générations réussies du même preset
    eta_s: float | None  # temps restant avant la fin de ce job


class QueueOut(BaseModel):
    running: QueueItemOut | None
    pending: list[QueueItemOut]
    total_eta_s: float | None
    comfyui: str | None  # http | mock


class WorkflowPresetOut(BaseModel):
    id: str
    name: str
    description: str
    params: list[str]
    reference_slots: int
    supports_lora: bool
    lora_loader: str | None
    timeout_s: float
    is_default: bool
    is_reference_default: bool
    with_references: str | None = None  # workflow du même palier pour les cases avec références
    has_trial: bool = False
    tier: str | None = None  # Turbo, Rapide, Qualité
    tier_choice: str | None = None  # libellé dans la fiche série (absent : pas proposé comme palier)
    tier_order: int | None = None
    estimated_s: float | None = None
    is_quality: bool = False  # palier de « Régénérer en Qualité »
    role: Literal["generation", "croquis", "propre", "controle"] = "generation"
    from_sketch: str | None = None  # workflow « propre depuis croquis » du même palier
    with_control: str | None = None  # workflow ControlNet (composition verrouillée) du même palier
    is_sketch: bool = False  # workflow des croquis (defaults.workflow_sketch)
    steps: int | None = None
    cfg: float = 1.0
    distilled: bool = False  # modèle distillé (Turbo) : cfg 1 imposé
    negative_active: bool = False  # cfg > 1 : le prompt négatif est lu par le modèle


class PresetEstimateOut(BaseModel):
    preset: str
    tier: str | None
    panels: int
    per_panel_s: float | None
    measured: bool  # médiane de vraies durées (≥ 3) ; sinon `estimated_s` du preset
    samples: int


class EstimateOut(BaseModel):
    remaining_panels: int
    total_s: float | None  # None : un preset sans durée connue ni `estimated_s`
    measured: bool  # False : au moins une partie vient des estimations des presets (« estimation »)
    by_preset: list[PresetEstimateOut]


# --- Palier croquis ----------------------------------------------------------------
class SketchIn(_In):
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None  # null : nouvelle graine


class SketchValidateIn(_In):
    image_id: int | None = None  # null : le croquis le plus récent


class CleanIn(_In):
    denoise: Denoise | None = None  # null : case > série > preset


class NameValidateIn(_In):
    """« Valider la name » d'une page (palier croquis, pipeline/name_board.py)."""

    author: Short = ""


class PanelSplitIn(_In):
    """Couper une case en deux : descriptions des deux moitiés (absent = celle de la case), répliques qui
    passent dans la nouvelle case (la seconde), et re-croquer les deux cases (palier croquis)."""

    first: LongText | None = None
    second: LongText | None = None
    move_bubble_ids: Annotated[list[int], Field(max_length=50)] = Field(default_factory=list)
    sketch: bool = True


class PanelSplitOut(BaseModel):
    page: PageOut
    panel_ids: list[int]  # les deux cases touchées (la case coupée, puis la nouvelle)
    jobs: list[JobOut]  # croquis mis en file pour ces deux cases
    sketch_note: str | None = None  # pourquoi rien n'est re-croqué (ComfyUI hors ligne, palier désactivé…)


class SketchEstimateOut(BaseModel):
    panels: int  # cases de la page / du chapitre
    to_sketch: int  # cases encore à croquer (sans version propre ni croquis validé)
    validated: int  # cases au croquis validé
    to_clean: int  # cases validées sans version propre tirée de leur croquis
    sketch: EstimateOut  # « croquis de la page »
    clean: EstimateOut  # « passage au propre des cases validées »


# --- Contrôle qualité (étape 4) ------------------------------------------------
# auto : la vision ne tourne que si les couches 1-2 hésitent ; force : toujours ; skip : jamais.
VisionModeName = Literal["auto", "force", "skip"]


class PanelQCIn(_In):
    image_id: int | None = None  # absent : la version choisie (sinon la plus récente)
    vision: VisionModeName = "auto"


class ChapterQCIn(_In):
    force: bool = False  # True : recontrôle aussi les cases déjà contrôlées
    vision: VisionModeName = "auto"


class QCOverrideIn(_In):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class QCSummaryOut(BaseModel):
    ok: int
    review: int
    reject: int
    unchecked: int
    no_image: int
    total: int


class ChapterQCOut(BaseModel):
    job: JobOut | None
    panel_ids: list[int]
    skipped: int
    summary: QCSummaryOut


class QCLayerStatusOut(BaseModel):
    provider: str | None
    available: bool
    detail: str | None


class QCStatusOut(BaseModel):
    available: bool  # preset valide et au moins une couche disponible
    detail: str | None
    auto_after_generation: bool
    max_auto_retries: int
    ok_min: int | None
    reject_below: int | None
    vision_mode: str | None
    layers: dict[str, QCLayerStatusOut]


# --- Personnages -----------------------------------------------------------
def _clean_keywords(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    out: list[str] = []
    for kw in value:
        kw = kw.strip()
        if kw and kw not in out:
            out.append(kw)
    return out


Keywords = Annotated[list[Annotated[str, StringConstraints(max_length=100)]], Field(max_length=50)]


Aliases = Annotated[list[Name], Field(max_length=20)]


def _clean_aliases(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    out: list[str] = []
    for alias in value:
        if alias and alias.casefold() not in {a.casefold() for a in out}:
            out.append(alias)
    return out


class EntryCreate(_In):
    """Fiche de la bibliothèque (objet, décor) ; un personnage a en plus ses autres noms (`CharacterCreate`)."""

    name: Name
    visual_description: LongText = ""
    prompt_keywords: Keywords = Field(default_factory=list)
    lora_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    lora_weight: float = Field(default=0.8, ge=0, le=2)
    lora_trigger_words: LoraTriggers = ""

    _kw = field_validator("prompt_keywords")(_clean_keywords)

    @field_validator("lora_name")
    @classmethod
    def _empty_lora(cls, v: str | None) -> str | None:
        return v or None


class CharacterCreate(EntryCreate):
    # Autres noms reconnus par le scénario (« le petit dragon ») : voir pipeline/names.py.
    aliases: Aliases = Field(default_factory=list)

    _aliases = field_validator("aliases")(_clean_aliases)


class EntryUpdate(_In):
    name: Name | None = None
    visual_description: LongText | None = None
    prompt_keywords: Keywords | None = None
    lora_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    lora_weight: float | None = Field(default=None, ge=0, le=2)
    lora_trigger_words: LoraTriggers | None = None

    _kw = field_validator("prompt_keywords")(_clean_keywords)


class CharacterUpdate(EntryUpdate):
    aliases: Aliases | None = None

    _aliases = field_validator("aliases")(_clean_aliases)


class CharacterLinkIn(_In):
    """Rattache un nom écrit par le scénario à une fiche (il devient un de ses alias), ou l'écarte
    (`character_id` null : figurant sans fiche, retiré des personnages des cases du chapitre)."""

    name: Name
    character_id: int | None


class CharacterLinkOut(BaseModel):
    name: str
    character_id: int | None
    panels: int  # cases du chapitre concernées
    alias_added: bool


class ReferenceImageOut(BaseModel):
    id: int
    url: str
    original_name: str
    content_type: str
    width: int
    height: int
    created_at: datetime
    # Angle de caméra de la vue (id de presets/camera_loras.yaml) ; null = non étiquetée.
    angle: str | None = None


class ImageAngleIn(_In):
    angle: AngleId | None = None  # null : retire l'étiquette


class CharacterOut(BaseModel):
    id: int
    project_id: int
    name: str
    slug: str  # dossier de la fiche dans ComfyUI : mangaka/<série>/personnages|objets|decors/<slug>/
    visual_description: str
    prompt_keywords: list[str]
    lora_name: str | None
    lora_weight: float
    lora_trigger_words: str
    reference_images: list[ReferenceImageOut]
    created_at: datetime
    updated_at: datetime
    aliases: list[str] = Field(default_factory=list)  # personnages seulement


# --- Objets, décors, véhicules et créatures de la bibliothèque (mêmes champs qu'un personnage) ------
AssetKindName = Literal["object", "decor", "vehicle", "creature"]
AssetCreate = EntryCreate
AssetUpdate = EntryUpdate


class AssetOut(CharacterOut):
    kind: AssetKindName


class AssetKindIn(_In):
    """Changer de catégorie un objet, un véhicule ou une créature (objet → véhicule…) : images, variantes et cases
    qui le montrent gardées."""

    kind: Literal["object", "vehicle", "creature"]


class ImageOrderIn(_In):
    """Nouvel ordre des images de référence d'une fiche (toutes, une fois chacune) ; la 1re est la principale."""

    image_ids: list[int] = Field(min_length=1, max_length=200)


# --- « Créer des références » (fiches générées par ComfyUI) ---------------------
LibraryKindName = Literal["character", "object", "decor", "vehicle", "creature"]
Instruction = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ReferenceSheetOut(BaseModel):
    id: str
    name: str
    description: str
    kinds: list[LibraryKindName]
    width: int
    height: int
    workflow: str | None  # None : palier de la série (ou Qualité)


class ReferenceGenerateIn(_In):
    sheet: PresetId
    count: VariantCount = 4
    quality: bool = False  # palier Qualité au lieu de celui de la série
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None
    # Image de départ facultative : une image de référence de la fiche (image 1 du workflow « avec
    # références ») ; absente = à partir de zéro, depuis la description seule.
    start_image_id: int | None = None
    # « Refaire la base en épuré » : à partir de zéro (jamais d'image de départ), la variante gardée devient
    # l'image principale ; l'ancienne base reste parmi les images de la fiche.
    rebase: bool = False


class AngleViewIn(_In):
    """« Nouvel angle » d'une fiche : la vue `start_image_id` (la principale par défaut) tournée jusqu'à `angle`."""

    angle: AngleId
    start_image_id: int | None = None
    lora: CameraLoraId | None = None
    weight: LoraWeight | None = None
    seed: Annotated[int, Field(ge=0, le=MAX_SEED)] | None = None


class CameraLoraOut(BaseModel):
    id: str
    role: Literal["angles", "identity"]
    name: str
    description: str
    file: str
    trigger: str
    weight: float
    tiers: list[str]
    default: bool
    # Workflows (paliers) où ce LoRA est ajouté ; ailleurs : « Disponible en palier Qualité ».
    workflows: list[str]


class CameraAngleOut(BaseModel):
    id: str
    label: str
    camera: str
    azimuth: float
    elevation: float


class CameraLorasOut(BaseModel):
    """presets/camera_loras.yaml : LoRA d'angle et d'identité, vocabulaire de caméra, palier des générations d'angle."""

    workflow: str | None
    workflow_tier: str | None
    # null : « Nouvel angle » et « Changer l'angle » disponibles ; sinon pourquoi (palier, LoRA absent…).
    angle_problem: str | None
    loras: list[CameraLoraOut]
    angles: list[CameraAngleOut]
    main_view: str | None
    weight_hint: str
    tier_label: str


class ReferenceKeepIn(_In):
    # « Garder quand même » : accepte à la main une fiche d'objet ou de décor où un personnage a été détecté.
    accept_people: bool = False


class ReferenceRefineIn(_In):
    instruction: Instruction = Field(min_length=1)
    count: VariantCount = 4
    quality: bool = False
    sheet: PresetId | None = None  # par défaut : celui de la variante de départ


class ReferenceVariantOut(BaseModel):
    id: int
    entry_kind: LibraryKindName
    entry_id: int
    url: str
    sheet: str
    sheet_name: str
    preset: str | None
    tier: str | None
    seed: int | None
    width: int
    height: int
    prompt: str
    instruction: str
    parent_id: int | None
    kept: bool  # gardée parmi les images de référence de la fiche (et toujours présente)
    kept_image_id: int | None
    job_id: int | None
    # Fiche d'objet ou de décor : personnage détecté (QC) → avertissement, et « Garder comme référence »
    # refusé tant que la variante n'est pas acceptée à la main (`people_accepted`).
    people_warning: str | None = None
    people_accepted: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class StaleDrawingOut(BaseModel):
    """« Créée avec l'ancien rendu (détaillé) » : la base de la fiche garde son trait, ses variantes aussi."""

    option: str  # réglage de style_options.yaml (`dessin`)
    message: str  # « Créée avec l'ancien rendu (détaillé) »
    action: str  # « Refaire la base en épuré »
    image_id: int  # image principale concernée
    sheet: str  # type de fiche de cette image, à refaire


class ReferenceStudioOut(BaseModel):
    """Historique des variantes d'une fiche (plus récentes d'abord) et générations en cours."""

    variants: list[ReferenceVariantOut]
    active_jobs: list[JobOut]
    max_kept: int
    kept_count: int
    reference_slots: int  # emplacements d'images de référence d'une case (workflow « avec références »)
    # Image principale créée avec un autre dessin que celui de la série (« Épuré ») ; None sinon.
    stale_drawing: StaleDrawingOut | None = None


# --- Planche de style ---------------------------------------------------------------
class StyleTrialOut(BaseModel):
    """Essai de la planche de style (palier croquis)."""

    id: int
    url: str
    batch: int | None  # numéro de la série d'essais (« Relancer » en crée une nouvelle)
    variant: int | None
    count: int | None
    seed: int | None
    width: int
    height: int
    prompt: str
    preset: str | None
    chosen: bool  # passé au propre : devenu une référence de style
    created_at: datetime


class StyleReferenceOut(BaseModel):
    """Référence de style de la série (essai retenu passé au propre)."""

    id: int
    name: str
    url: str
    width: int
    height: int
    active: bool
    style: str  # `$style` de la série au moment des essais
    outdated: bool  # le style de la série a changé depuis
    trial_id: int | None
    created_at: datetime


class StyleBoardOut(BaseModel):
    """Planche de style d'une série : référence active, historique, essais et jobs en cours."""

    configured: bool  # `style_board` présent dans defaults.yaml
    problem: str | None  # pourquoi les essais sont impossibles (genre non choisi…), sinon None
    scene_test: str | None
    style: str
    style_names: str
    trials_per_batch: int
    use_reference_sheets: Literal["with_subject", "always", "never"] | None
    reference_sheet_kinds: list[LibraryKindName] = Field(default_factory=list)
    use_panels: Literal["with_subject", "free_slot", "never"] | None
    active: StyleReferenceOut | None
    history: list[StyleReferenceOut]
    trials: list[StyleTrialOut]
    active_jobs: list[JobOut]


# --- Banc d'essai du QC -----------------------------------------------------------
AnnotationLabelName = Literal["good", "bad"]
DefectName = Literal["face", "hands", "identity", "description", "text", "other"]


class AnnotationIn(_In):
    label: AnnotationLabelName
    defects: list[DefectName] = Field(default_factory=list, max_length=6)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""

    @field_validator("defects")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class AnnotationOut(BaseModel):
    label: AnnotationLabelName
    defects: list[str]
    note: str
    updated_at: datetime


class BenchDatasetOut(BaseModel):
    good: int
    bad: int
    total: int
    by_defect: dict[str, int]
    goal_min: int | None
    goal_max: int | None
    target_recall: float | None


class BenchRunIn(_In):
    project_id: int | None = None
    chapter_id: int | None = None
    vision: bool = True  # False : sans la couche vision (lente)


class BenchRunOut(BaseModel):
    id: int
    job: JobOut | None
    status: str  # pending | running | succeeded | failed | cancelled
    error: str | None
    project_id: int | None
    chapter_id: int | None
    scope: str
    vision: bool
    preset_hash: str | None
    sample_count: int
    good: int | None
    bad: int | None
    created_at: datetime
    finished_at: datetime | None
    applied_at: datetime | None
    # Résumé par couche : précision, rappel, FP, FN, cases évaluées, temps moyen.
    layers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BenchRunDetailOut(BenchRunOut):
    metrics: dict[str, Any] | None
    items: list[dict[str, Any]]
    preset: dict[str, Any]
    previous: BenchRunOut | None
    current_preset_hash: str | None


class BenchApplyIn(_In):
    confirm: bool = False  # False : aperçu des modifications, rien n'est écrit


class BenchApplyOut(BaseModel):
    applied: bool
    changes: list[dict[str, Any]]
    preset_changed: bool  # le preset a changé depuis ce run
    message: str


# --- Savoir-faire et bible ----------------------------------------------------
KnowledgeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500_000)]
BibleField = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class CollectionCreate(_In):
    name: Name
    description: LongText = ""
    project_id: int | None = None  # None : collection globale


class CollectionUpdate(_In):
    name: Name | None = None
    description: LongText | None = None
    project_id: int | None = None


class CollectionOut(BaseModel):
    id: int
    name: str
    description: str
    project_id: int | None
    project_title: str | None
    document_count: int
    chunk_count: int
    token_count: int
    whole: bool  # sous le seuil « petite collection » : injectée entière
    pack: str | None = None  # pack de savoir-faire livré : collection en lecture seule, réécrite par une mise à jour
    created_at: datetime
    updated_at: datetime


class DocumentCreate(_In):
    title: Title
    content: KnowledgeText
    tags: list[Tag] = Field(default_factory=list, max_length=20)


class DocumentUpdate(_In):
    title: Title | None = None
    content: KnowledgeText | None = None
    tags: list[Tag] | None = Field(default=None, max_length=20)


class ChunkOut(BaseModel):
    id: int
    index: int
    heading: str
    text: str
    token_count: int
    embedded: bool


class DocumentSummaryOut(BaseModel):
    id: int
    collection_id: int
    title: str
    source: str
    original_name: str | None
    tags: list[str]
    token_count: int
    chunk_count: int
    index_error: str | None
    pack: str | None = None  # document d'un pack (lecture seule)
    pack_key: str | None = None  # identifiant de la fiche dans le pack
    created_at: datetime
    updated_at: datetime


class DocumentOut(DocumentSummaryOut):
    content: str
    collection_name: str
    meta: dict[str, Any] = Field(default_factory=dict)  # champs du bloc meta d'une fiche de pack
    keywords: str = ""  # mots-clés cherchés mais jamais injectés (titre, pont de vocabulaire)
    chunks: list[ChunkOut]


class SearchIn(_In):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    collection_ids: list[int] | None = None
    project_id: int | None = None  # collections de la série + collections globales
    top_k: int | None = Field(default=None, ge=1, le=50)
    budget_tokens: int | None = Field(default=None, ge=0, le=32000)


class PassageOut(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    collection_id: int
    collection_name: str
    heading: str
    text: str
    tokens: int
    score: float | None
    vector_score: float | None
    keyword_score: float | None
    # framing : fiche du plan ou de l'angle de la case (une seule par famille), servie en premier ; genre : courbe
    # de tension du genre de la série (scénariste, une seule), servie en premier
    mode: Literal["retrieved", "whole", "framing", "genre"]
    pack: str | None = None
    pages: list[int] = Field(default_factory=list)  # recherche par page (direction artistique)
    dropped: str | None = None  # écarté comme redondant : raison (en français)
    selected: bool = False


class PanelKnowledgePart(BaseModel):
    """Savoir-faire d'une case pour un destinataire (rédacteur de prompt ou note des fragments)."""

    passages: list[PassageOut]
    tokens: int  # jetons des passages retenus
    budget_tokens: int
    top_k: int
    text: str  # ce que reçoit le destinataire ($savoir_faire)
    text_tokens: int
    bible: str  # notes de la bible sur les personnages de la case ($bible)
    bible_tokens: int
    # Passages qui auraient été servis sans le tri des redondances (doublon, autre plan / angle que la case).
    dropped: list[PassageOut] = Field(default_factory=list)


class PromptSourcesOut(BaseModel):
    """Ce que le rédacteur de prompt a reçu pour le prompt actuel d'une case (« Sources utilisées »)."""

    written_at: datetime
    query: str = ""
    collections: list[str] = Field(default_factory=list)
    passages: list[PassageOut] = Field(default_factory=list)
    dropped: list[PassageOut] = Field(default_factory=list)  # écartés comme redondants (raison dans `dropped`)
    tokens: int = 0
    budget_tokens: int = 0
    bible: str = ""
    # Prompt retouché depuis (à la main ou par le dialogue) : ces sources sont celles de la rédaction d'origine.
    edited: bool = False


class RewritePromptsOut(BaseModel):
    """« Réécrire les prompts du chapitre » : cases dont le prompt rédigé par l'IA sera rédigé de nouveau."""

    count: int
    ai_prompt: bool


class PanelKnowledgeOut(BaseModel):
    """Ce que lit le Dessinateur pour une case : une recherche, deux budgets."""

    panel_id: int
    query: str
    collections: list[str]
    writer: PanelKnowledgePart
    fragments: PanelKnowledgePart
    warning: str | None = None


class BibleSummary(BaseModel):
    text: str
    tokens: int
    truncated: bool
    chapter_summaries: int


class SearchOut(BaseModel):
    query: str
    collections: list[str]
    passages: list[PassageOut]  # classement complet
    selected_tokens: int
    budget_tokens: int
    top_k: int
    bible: BibleSummary | None = None
    warning: str | None = None


class BibleCharacter(BaseModel):
    id: int
    name: str
    visual_description: str
    note: str


class BibleAsset(BaseModel):
    """Objet ou décor de la bibliothèque, repris dans la bible injectée aux agents."""

    id: int
    name: str
    visual_description: str


class ChapterSummaryEntry(BaseModel):
    chapter_id: int | None = None
    number: int | None = None
    title: str = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
    added_at: str | None = None


class BibleUpdate(_In):
    world: BibleField | None = None
    tone: BibleField | None = None
    rules: BibleField | None = None
    motifs: BibleField | None = None
    character_notes: dict[int, Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]] | None = None
    chapter_summaries: list[ChapterSummaryEntry] | None = Field(default=None, max_length=1000)


class BibleOut(BaseModel):
    project_id: int
    world: str
    tone: str
    rules: str
    motifs: str
    characters: list[BibleCharacter]
    decors: list[BibleAsset] = Field(default_factory=list)
    objets: list[BibleAsset] = Field(default_factory=list)
    vehicules: list[BibleAsset] = Field(default_factory=list)
    creatures: list[BibleAsset] = Field(default_factory=list)
    chapter_summaries: list[ChapterSummaryEntry]
    rendered: BibleSummary | None
    updated_at: datetime | None


class SourcesOut(BaseModel):
    run_id: int
    job_id: int | None
    agent: str
    model: str | None
    query: str = ""  # requête de recherche (direction artistique : une ligne « Page N : … » par page)
    collections: list[str]
    passages: list[PassageOut]
    bible: BibleSummary | None
    created_at: datetime


class KnowledgeAgentOut(BaseModel):
    role: str
    label: str
    collections: list[str]  # noms demandés (profil ou knowledge.yaml)
    source: Literal["profile", "preset"]
    series_collections: bool
    budget_tokens: int  # pour `image_prompt` : celui du rédacteur de prompt
    top_k: int
    bible: bool
    # `image_prompt` seulement : note courte du prompt par fragments (None : pas de rédacteur à part).
    fragment_budget_tokens: int | None = None
    fragment_top_k: int | None = None


class PackReportOut(BaseModel):
    pack: str
    collections: int
    documents: int
    created: int
    updated: int
    deleted: int
    unchanged: int
    skipped_sections: list[str]
    warnings: list[str]
    error: str | None


class KnowledgeStatusOut(BaseModel):
    provider: str | None
    model: str | None
    available: bool
    detail: str | None
    collections: int
    documents: int
    chunks: int
    stale_chunks: int  # sans vecteur, ou vecteur d'un autre modèle : à réindexer
    small_collection_tokens: int
    vector_backend: str
    agents: list[KnowledgeAgentOut]
    packs: list[PackReportOut] = Field(default_factory=list)  # dernier import des packs livrés


class ReindexOut(BaseModel):
    documents: int
    chunks: int
    errors: list[str]


# --- Traçabilité : journal des générations, verdicts, A/B, statistiques ------------------------
VerdictName = Literal["validated", "rejected", "regenerated", "edited"]
JudgeName = Literal["validated", "rejected"]
ReasonId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
VerdictNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class VerdictReasonOut(BaseModel):
    id: str
    label: str


class MeasureOut(BaseModel):
    key: str  # dark_pct | black_pct | white_pct | saturation_pct | line_density_pct
    label: str
    target: float | None = None


class JournalSettingsOut(BaseModel):
    """Réglages du journal pour l'interface : raisons d'un rejet, mesures et cible de tonalité."""

    reasons: list[VerdictReasonOut]
    measures: list[MeasureOut]
    tonality_reference: str
    dark_below: int
    black_below: int
    white_from: int
    low_data_below: int
    kinds: dict[str, str]
    verdicts: dict[str, str]


class GenerationEventOut(BaseModel):
    id: int
    created_at: datetime
    verdict: VerdictName
    action: str
    reason: str | None = None
    reason_label: str | None = None
    note: str = ""


class GenerationLogOut(BaseModel):
    id: int
    created_at: datetime
    kind: str
    status: str
    error: str | None = None
    job_id: int | None = None
    project_id: int | None = None
    chapter_id: int | None = None
    page_id: int | None = None
    panel_id: int | None = None
    image_kind: str | None = None
    image_id: int | None = None
    version: int | None = None
    preset: str | None = None
    tier: str | None = None
    model: str | None = None
    steps: int | None = None
    cfg: float | None = None
    seed: int | None = None
    width: int | None = None
    height: int | None = None
    denoise: float | None = None
    positive_prompt: str = ""
    negative_prompt: str = ""
    positive_chars: int = 0
    positive_words: int = 0
    negative_chars: int = 0
    negative_words: int = 0
    prompt_source: str | None = None
    writer_hash: str | None = None
    references: list[dict[str, Any]] = Field(default_factory=list)
    loras: list[dict[str, Any]] = Field(default_factory=list)
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    framing: str | None = None
    angle: str | None = None
    mood: str | None = None
    finish: str | None = None
    duration_ms: int | None = None
    measures: dict[str, float | None] = Field(default_factory=dict)
    gaps: dict[str, float | None] = Field(default_factory=dict)  # valeur − cible, en points
    ab_group: str | None = None
    ab_arm: str | None = None
    ab_mode: str | None = None
    verdict: JudgeName | None = None  # dernier verdict « jugé » (gardée / rejetée)
    events: list[GenerationEventOut] = Field(default_factory=list)


class ImageJournalOut(BaseModel):
    """Journal d'une version : la génération qui l'a produite (None : version d'avant le journal)."""

    log: GenerationLogOut | None = None


class VerdictIn(_In):
    verdict: JudgeName
    reason: ReasonId | None = None
    note: VerdictNote = ""


class ABIn(_In):
    mode: Literal["prompt", "tier", "cfg"]
    prompt_b: LongText | None = None
    presets: list[PresetId] | None = Field(default=None, min_length=2, max_length=2)
    cfgs: list[Cfg] | None = Field(default=None, min_length=2, max_length=2)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class ABStartOut(BaseModel):
    group: str
    seed: int
    jobs: list[JobOut]


class ABArmOut(BaseModel):
    arm: Literal["A", "B"]
    log: GenerationLogOut | None = None
    image: PanelImageOut | None = None


class ABGroupOut(BaseModel):
    group: str
    mode: str | None = None
    seed: int | None = None
    pending: bool = False  # au moins un bras encore en file ou en cours
    arms: list[ABArmOut]
    choice: Literal["A", "B"] | None = None


class ABChoiceIn(_In):
    winner: Literal["A", "B"]
    reason: ReasonId | None = None
    note: VerdictNote = ""
    # Le bras retenu devient aussi la version choisie de la case.
    select: bool = True


class StatsGroupOut(BaseModel):
    value: str
    generations: int
    judged: int
    validated: int
    rejected: int
    validation_rate: float | None = None  # % de gardées parmi les jugées
    regenerated: int
    edited: int
    low_data: bool
    means: dict[str, float | None]


class StatsBreakdownOut(BaseModel):
    key: str
    label: str
    rows: list[StatsGroupOut]


class StatsTotalOut(BaseModel):
    generations: int
    judged: int
    validated: int
    rejected: int
    validation_rate: float | None = None
    regenerated: int
    edited: int
    low_data: bool
    means: dict[str, float | None]


class StatsOut(BaseModel):
    total: StatsTotalOut
    low_data: bool
    low_data_below: int
    breakdowns: list[StatsBreakdownOut]
    # « Passer outre » une étape vitale (garde d'étapes), les plus récents d'abord.
    stage_overrides: list[StageOverrideRowOut] = []


# --- Garde d'étapes (pipeline/stage_gate.py) -------------------------------------------------
StageName = Literal["scenes", "script", "direction", "layout", "references", "prompts", "name", "approved", "lettering"]


class StageDecisionOut(BaseModel):
    decision: Literal["validated", "forced", "revoked"]
    author: str
    note: str
    at: datetime


class StageOut(BaseModel):
    key: StageName
    label: str
    complete: bool  # réglée par le contenu du chapitre
    forced: bool  # « Passer outre » en cours
    passed: bool  # complète ou forcée : ne bloque rien
    total: int
    faults: int
    summary: str  # « 5 pages en attente sur 5 »
    examples: list[str]
    fix: str
    screen: str  # onglet du chapitre qui règle l'étape (`personnages` : fiches de la série)
    blocks: list[str]  # actions bloquées en ce moment (« générer », « lettrer »…)
    decision: StageDecisionOut | None = None


class ChapterStagesOut(BaseModel):
    chapter_id: int
    project_id: int
    stages: list[StageOut]


class StageOverrideIn(_In):
    author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class StageOverrideRowOut(BaseModel):
    id: int
    at: datetime
    project_id: int | None
    chapter_id: int
    chapter_number: int | None
    chapter_title: str | None  # None : chapitre supprimé depuis
    stage: str
    stage_label: str
    author: str
    note: str
    faults: int
    total: int


# --- Distribution du chapitre (pipeline/cast.py) -----------------------------------------------------------
class CastAppearanceOut(BaseModel):
    panel_id: int
    page_number: int
    panel_index: int  # 0-based
    label: str  # « case 2 de la page 3 »
    sources: list[str]  # image | hors cadre | bulle | description | mise en scène


class CrowdMarkOut(BaseModel):
    id: int
    name: str
    author: str
    at: datetime


class CastMemberOut(BaseModel):
    key: str
    name: str
    character_id: int | None
    written: list[str]
    appearances: list[CastAppearanceOut]
    panel_count: int
    images: int
    references: Literal["aucune", "portrait", "planche"]
    role: Literal["principal", "secondaire"]
    needs: Literal["portrait", "planche"]
    crowd: bool  # foule anonyme : peut être marquée « foule sans fiche »
    mark: CrowdMarkOut | None
    fault: Literal["sans fiche", "sans image"] | None
    advice: str | None


class ChapterCastOut(BaseModel):
    chapter_id: int
    project_id: int
    members: list[CastMemberOut]
    total: int  # intervenants comptés par la garde (foules marquées exclues)
    faults: int
    without_card: list[str]
    without_image: list[str]
    marks: list[CrowdMarkOut]


class CastNameIn(_In):
    name: Name


class CrowdMarkIn(_In):
    name: Name
    author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class CrowdRevokeIn(_In):
    author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = ""


class CharacterDraftOut(BaseModel):
    """Fiche préremplie d'un intervenant (rien n'est enregistré : l'auteur la relit puis la crée)."""

    name: str  # nom de fiche proposé (« Le garde »)
    written: str  # nom tel qu'écrit par le scénario
    visual_description: str
    prompt_keywords: list[str]
    age: str
    silhouette: str
    tenue: str
    signe_distinctif: str
    panel_count: int  # cases lues


class CastBatchItemOut(BaseModel):
    name: str
    character_id: int | None = None
    created: bool = False  # fiche créée par ce passage
    queued: bool = False  # portrait mis en file
    message: str = ""  # erreur lisible, ou pourquoi rien n'a été fait


class CastBatchOut(BaseModel):
    items: list[CastBatchItemOut]
    jobs: list[JobOut]
    cast: ChapterCastOut
