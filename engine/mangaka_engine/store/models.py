"""Modèle de données SQLite (SQLAlchemy 2).

Série (`Project`) → Character (+ images de référence)
Série → SeriesAsset : objets et décors récurrents de la bibliothèque (+ images de référence), et
références de style de la planche de style (`kind = style` : une seule active, les autres en historique)
Série → ReferenceVariant : images générées par « Créer des références » d'une fiche, gardées ou non
Série → Chapter → Page → Panel (+ versions d'image → annotation humaine) → Bubble · Job.
Banc d'essai du QC : `QCBenchRun` (historique des mesures du QC sur les cases annotées).
Savoir-faire : `KnowledgeCollection` (globale ou d'une série) → `KnowledgeDocument` → `KnowledgeChunk`
(+ index plein texte FTS5 `knowledge_fts`, tenu à jour par des triggers) · `SeriesBible` (une par série)
· `LLMRun` (passages reçus par chaque appel du LLM).
Direction artistique : `PageDirection` (une par page : proposition de l'agent, champs verrouillés par
l'auteur, version appliquée à la mise en page et aux prompts).
Les fichiers binaires (images) vivent dans `data/`, la base ne stocke que leurs chemins relatifs.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ReadingDirection(enum.StrEnum):
    ltr = "ltr"  # BD franco-belge / comics
    rtl = "rtl"  # manga


class SeriesStatus(enum.StrEnum):
    ongoing = "ongoing"  # en cours
    paused = "paused"  # en pause
    completed = "completed"  # terminée
    cancelled = "cancelled"  # arrêtée


class ChapterStatus(enum.StrEnum):
    draft = "draft"  # brouillon
    script = "script"  # scénario
    layout = "layout"  # mise en page
    generation = "generation"  # génération
    lettering = "lettering"  # lettrage
    ready = "ready"  # prêt
    published = "published"  # publié


class PageKind(enum.StrEnum):
    story = "story"  # page de l'histoire
    bonus = "bonus"  # croquis, notes de l'auteur…
    chapter_cover = "chapter_cover"  # page de garde du chapitre


class PageState(enum.StrEnum):
    draft = "draft"
    layout = "layout"
    generating = "generating"
    review = "review"
    lettered = "lettered"
    done = "done"


class PanelState(enum.StrEnum):
    draft = "draft"
    queued = "queued"
    generating = "generating"
    review = "review"  # au moins une version générée, à valider
    qc = "qc"
    flagged = "flagged"
    approved = "approved"


class ImageKind(enum.StrEnum):
    final = "final"  # version de case (choisie, assemblée, lettrée, exportée)
    croquis = "croquis"  # brouillon de composition (palier croquis) : jamais choisi ni assemblé


class QCVerdict(enum.StrEnum):
    ok = "ok"
    review = "review"  # à revoir
    reject = "reject"  # rejet


class BubbleKind(enum.StrEnum):
    speech = "speech"
    thought = "thought"
    shout = "shout"
    narration = "narration"
    off = "off"
    sfx = "sfx"  # onomatopée : lettrage hors bulle (pas de forme ni de queue)


class JobStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, validate_strings=True, length=20)


# Ids jamais réutilisés (AUTOINCREMENT) pour les tables dont l'id finit dans l'URL d'un fichier servi : sans
# cela SQLite reprend max(id) + 1 après une suppression, et une URL recyclée montrerait l'image supprimée.
NEVER_REUSED = {"sqlite_autoincrement": True}


class Project(TimestampMixin, Base):
    """Une série (table historique `projects`)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    # Ancien style en texte libre : lecture seule (fiche série), ignoré dès qu'un pack est choisi.
    legacy_style: Mapped[str] = mapped_column(Text, default="")
    # Packs de style (presets/style_genres, style_renderings, style_tones) ; None = pas encore choisi.
    style_genre: Mapped[str | None] = mapped_column(String(100), default=None)
    style_rendering: Mapped[str | None] = mapped_column(String(100), default=None)
    style_tone: Mapped[str | None] = mapped_column(String(100), default=None)
    # Réglages fins (presets/style_options.yaml) : {"trait": "epais", "trames": "denses", "detail": "riche"}.
    style_options: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    status: Mapped[SeriesStatus] = mapped_column(_enum(SeriesStatus), default=SeriesStatus.ongoing)
    reading_direction: Mapped[ReadingDirection] = mapped_column(_enum(ReadingDirection), default=ReadingDirection.rtl)
    # Presets par défaut de la série
    page_format: Mapped[str] = mapped_column(String(100))
    workflow_preset: Mapped[str] = mapped_column(String(100))
    style_lora_name: Mapped[str | None] = mapped_column(String(255), default=None)
    # Mots déclencheurs du LoRA de style : catalogue presets/style_loras.yaml (plus de saisie libre).
    style_lora_weight: Mapped[float] = mapped_column(Float, default=0.8)
    # Grammaire de mise en page de la série (presets/layout_styles/) : sage, dynamique, nerveuse…
    layout_style: Mapped[str] = mapped_column(String(100), default="dynamique")
    # Série passée en « sage » par la migration v8, pas par l'utilisateur : note unique dans la fiche
    # série, retirée dès que le style change ou que la note est fermée.
    layout_style_notice: Mapped[bool] = mapped_column(default=False)
    # Palier croquis (brouillon de page, tri, passage au propre) ; `sketch_denoise` : débruitage du
    # passage au propre (None = `denoise` du preset « propre »).
    sketch_enabled: Mapped[bool] = mapped_column(default=True)
    sketch_denoise: Mapped[float | None] = mapped_column(Float, default=None)
    # Passage au propre : `img2img` (débruitage partiel du croquis) ou `controlnet` (composition
    # verrouillée sur le croquis, type `clean_control` ; None = type par défaut du preset).
    clean_mode: Mapped[str] = mapped_column(String(20), default="img2img")
    clean_control: Mapped[str | None] = mapped_column(String(40), default=None)
    # Agrandisseur de la finition d'impression (presets/upscalers/) ; None = celui de defaults.yaml.
    upscaler: Mapped[str | None] = mapped_column(String(100), default=None)

    characters: Mapped[list[Character]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Character.name"
    )
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Chapter.number"
    )
    assets: Mapped[list[SeriesAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SeriesAsset.name"
    )


class Character(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    visual_description: Mapped[str] = mapped_column(Text, default="")
    prompt_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    lora_name: Mapped[str | None] = mapped_column(String(255), default=None)
    lora_weight: Mapped[float] = mapped_column(Float, default=0.8)
    lora_trigger_words: Mapped[str] = mapped_column(Text, default="")  # ajoutés au prompt avec le LoRA
    # Autres noms du personnage (« le petit dragon », « Urus le dragon ») : reconnus par le scénario.
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")

    project: Mapped[Project] = relationship(back_populates="characters")
    reference_images: Mapped[list[CharacterImage]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        order_by="[CharacterImage.position, CharacterImage.id]",
    )


class CharacterImage(Base):
    __tablename__ = "character_images"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))  # relatif à data/
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Ordre choisi par l'auteur : la première image est la référence principale (servie en premier
    # quand les emplacements du workflow manquent).
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    character: Mapped[Character] = relationship(back_populates="reference_images")


class AssetKind(enum.StrEnum):
    object = "object"  # objet récurrent : un robot, une épée, une voiture…
    decor = "decor"  # décor récurrent : la salle de classe, le labo, la rue…
    style = "style"  # référence de style de la planche de style (une seule active par série)


class SeriesAsset(TimestampMixin, Base):
    """Objet ou décor récurrent de la bibliothèque d'une série (mêmes champs qu'un personnage).

    Une référence de style (`kind = style`) a une seule image : l'essai de la planche de style passé au
    propre ; `visual_description` garde le `$style` de la série au moment des essais.
    """

    __tablename__ = "series_assets"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind))
    name: Mapped[str] = mapped_column(String(120))
    visual_description: Mapped[str] = mapped_column(Text, default="")
    prompt_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    lora_name: Mapped[str | None] = mapped_column(String(255), default=None)
    lora_weight: Mapped[float] = mapped_column(Float, default=0.8)
    lora_trigger_words: Mapped[str] = mapped_column(Text, default="")  # ajoutés au prompt avec le LoRA
    # Référence de style : la référence active de la série (les autres restent dans l'historique).
    active: Mapped[bool] = mapped_column(default=True)

    project: Mapped[Project] = relationship(back_populates="assets")
    reference_images: Mapped[list[SeriesAssetImage]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="[SeriesAssetImage.position, SeriesAssetImage.id]",
    )


class SeriesAssetImage(Base):
    __tablename__ = "series_asset_images"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("series_assets.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(500))  # relatif à data/
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)  # comme CharacterImage.position
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    asset: Mapped[SeriesAsset] = relationship(back_populates="reference_images")


class ReferenceVariant(Base):
    """Image générée par « Créer des références » pour une fiche de la bibliothèque.

    La fiche est repérée par (`entry_kind`, `entry_id`) — personnage, objet ou décor —, sans clé
    étrangère (deux tables possibles) : l'API supprime les variantes avec leur fiche. « Garder comme
    référence » copie l'image parmi les références de la fiche (`kept_image_id`) ; la variante reste
    dans l'historique.
    """

    __tablename__ = "reference_variants"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # character | object | decor ; `style` : essai de la planche de style (entry_id = id de la série).
    entry_kind: Mapped[str] = mapped_column(String(20))
    entry_id: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), default=None)
    sheet: Mapped[str] = mapped_column(String(100))  # presets/reference_sheets/
    path: Mapped[str] = mapped_column(String(500))  # relatif à data/
    content_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer, default=None)
    # Variante de départ d'un « Affiner » (sans clé étrangère : la variante de départ peut être supprimée).
    parent_id: Mapped[int | None] = mapped_column(Integer, default=None)
    instruction: Mapped[str] = mapped_column(Text, default="")
    # Preset, palier, prompts, LoRA, image de référence envoyée, durée…
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Image de référence créée par « Garder comme référence » (None : pas gardée).
    kept_image_id: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("project_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    synopsis: Mapped[str] = mapped_column(Text, default="")
    target_page_count: Mapped[int] = mapped_column(Integer, default=15)
    status: Mapped[ChapterStatus] = mapped_column(_enum(ChapterStatus), default=ChapterStatus.draft)
    planned_date: Mapped[date | None] = mapped_column(default=None)
    # Résumé produit par l'étape « scénario », relu par les chapitres suivants (continuité).
    summary: Mapped[str] = mapped_column(Text, default="")

    project: Mapped[Project] = relationship(back_populates="chapters")
    pages: Mapped[list[Page]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="Page.number"
    )


class Page(TimestampMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("chapter_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[PageKind] = mapped_column(_enum(PageKind), default=PageKind.story)
    # Gabarit imposé à la main (None = choix automatique par le découpage).
    grid_template: Mapped[str | None] = mapped_column(String(100), default=None)
    # Résultat de l'étape « découpage » (voir pipeline/layout.py), rejouable.
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Graine de la mise en page (même graine = même page) ; tirée à nouveau par « Nouvelle mise en page ».
    layout_seed: Mapped[int | None] = mapped_column(Integer, default=None)
    # Style imposé à cette page (None = celui de la série).
    layout_style: Mapped[str | None] = mapped_column(String(100), default=None)
    # Indice de rythme donné par le scénario : lent | normal | rapide (None = normal).
    rythme: Mapped[str | None] = mapped_column(String(20), default=None)
    state: Mapped[PageState] = mapped_column(_enum(PageState), default=PageState.draft)

    chapter: Mapped[Chapter] = relationship(back_populates="pages")
    panels: Mapped[list[Panel]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="Panel.index"
    )
    direction: Mapped[PageDirection | None] = relationship(
        back_populates="page", cascade="all, delete-orphan", uselist=False
    )


class Panel(TimestampMixin, Base):
    __tablename__ = "panels"
    __table_args__ = (UniqueConstraint("page_id", "index"), NEVER_REUSED)

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    character_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Noms tels qu'écrits par le scénario (personnages secondaires compris).
    character_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Bibliothèque de la série : décor de la case et objets visibles (ids de `series_assets`, sans clé
    # étrangère : un objet ou un décor supprimé est retiré des cases par l'API, ignoré sinon).
    decor_id: Mapped[int | None] = mapped_column(Integer, default=None)
    object_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    shot_type: Mapped[str | None] = mapped_column(String(50), default=None)
    # Donnés par le scénario : lieu (lieu, moment, éléments du décor) et mise en scène (qui fait quoi,
    # où dans le cadre, interactions) ; vides pour les cases d'avant (le prompt les omet alors).
    setting: Mapped[str] = mapped_column(Text, default="", server_default="")
    staging: Mapped[str] = mapped_column(Text, default="", server_default="")
    dialogues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # inutilisé : voir Bubble
    importance: Mapped[int] = mapped_column(Integer, default=1)
    # Intensité dramatique donnée par le scénario : calme | normal | choc (None = non précisée).
    intensity: Mapped[str | None] = mapped_column(String(20), default=None)
    # Options de cadre imposées dans l'UI : {"frame": "border"|"none"|"fade", "bleed": bool, "inset": bool} ;
    # une clé absente (ou None) = décidée par le style de mise en page.
    frame: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Géométrie en pixels de la page : {"x1", "y1", "x2", "y2"} (recopiée depuis Page.layout)
    bbox: Mapped[dict[str, int] | None] = mapped_column(JSON, default=None)
    bubble_zone: Mapped[dict[str, int] | None] = mapped_column(JSON, default=None)
    final_prompt: Mapped[str | None] = mapped_column(Text, default=None)
    # True : prompt final édité à la main, conservé tant qu'on ne demande pas de le reconstruire.
    final_prompt_manual: Mapped[bool] = mapped_column(default=False)
    generation_preset: Mapped[str | None] = mapped_column(String(100), default=None)
    # Croquis validé au tri (composition retenue, id de `panel_images` de sorte croquis) ; None = aucun.
    sketch_image_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Débruitage du passage au propre imposé à cette case (None = celui de la série, sinon du preset).
    sketch_denoise: Mapped[float | None] = mapped_column(Float, default=None)
    # Composition verrouillée (ControlNet) : toute génération de la case suit l'image guide jusqu'au
    # déverrouillage — {"source": "croquis"|"version"|"import", "image_id", "version", "path" (import),
    # "width", "height", "type", "strength", "locked_at", "preview": {"job_id", "path", "width", "height",
    # "type"}} ; None = composition libre.
    composition_lock: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    qc_score: Mapped[int | None] = mapped_column(Integer, default=None)
    state: Mapped[PanelState] = mapped_column(_enum(PanelState), default=PanelState.draft)

    page: Mapped[Page] = relationship(back_populates="panels")
    images: Mapped[list[PanelImage]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="PanelImage.version"
    )
    bubbles: Mapped[list[Bubble]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="Bubble.order"
    )


class PanelImage(Base):
    """Une version générée d'une case (tout résultat est versionné)."""

    __tablename__ = "panel_images"
    __table_args__ = (UniqueConstraint("panel_id", "version"), NEVER_REUSED)

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    # Sorte de version : `final` (par défaut) ou `croquis` (jamais choisie, assemblée ni exportée).
    kind: Mapped[ImageKind] = mapped_column(_enum(ImageKind), default=ImageKind.final)
    path: Mapped[str] = mapped_column(String(500))
    seed: Mapped[int | None] = mapped_column(Integer, default=None)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    qc_score: Mapped[int | None] = mapped_column(Integer, default=None)
    qc_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    qc_verdict: Mapped[QCVerdict | None] = mapped_column(_enum(QCVerdict), default=None)
    # Détail du dernier QC : couches (score, durée, raisons), décision humaine, historique.
    qc_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Boîtes détectées (visages, mains, texte) en px de l'image : réutilisées par le lettrage.
    detections: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Finition d'impression : dérivé agrandi de cette version (pas une nouvelle version de composition) —
    # {"path", "width", "height", "upscaler", "upscaler_name", "factor", "source_width", "source_height",
    # "target_dpi", "dpi", "job_id", "duration_ms", "created_at"}. Utilisé par l'assemblage tant que la
    # version reste retenue ; effacé (fichier compris) quand une autre version de la case est retenue.
    finish: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    selected: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    panel: Mapped[Panel] = relationship(back_populates="images")
    annotation: Mapped[PanelImageAnnotation | None] = relationship(
        back_populates="image", cascade="all, delete-orphan", uselist=False
    )


class AnnotationLabel(enum.StrEnum):
    good = "good"  # bonne
    bad = "bad"  # mauvaise


class PanelImageAnnotation(TimestampMixin, Base):
    """Jugement humain d'une version (bonne / mauvaise), indépendant du verdict QC : vérité terrain du banc d'essai."""

    __tablename__ = "panel_image_annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("panel_images.id", ondelete="CASCADE"), unique=True, index=True)
    label: Mapped[AnnotationLabel] = mapped_column(_enum(AnnotationLabel))
    # Étiquettes de défaut facultatives (voir pipeline/qc_bench.py : DEFECTS).
    defects: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")

    image: Mapped[PanelImage] = relationship(back_populates="annotation")


class QCBenchRun(Base):
    """Un passage du banc d'essai : métriques par couche sur les cases annotées, avec le preset utilisé."""

    __tablename__ = "qc_bench_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    # Filtre de l'ensemble annoté (None = toutes les séries / tous les chapitres).
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    vision: Mapped[bool] = mapped_column(default=True)
    # Version du preset qc.yaml utilisé : empreinte du fichier + valeurs validées.
    preset_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    preset: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    # Résultats (None tant que le run n'est pas terminé) : métriques par couche + détail par case.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    applied_at: Mapped[datetime | None] = mapped_column(default=None)  # seuils suggérés appliqués à qc.yaml
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class Bubble(TimestampMixin, Base):
    __tablename__ = "bubbles"

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    speaker_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    speaker_name: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[BubbleKind] = mapped_column(_enum(BubbleKind), default=BubbleKind.speech)
    # Cadre {"x","y","w","h"} et pointe de la queue {"x","y"} en px de la page, avec "manual": true quand
    # ils ont été ajustés à la main dans l'écran Lettrage ; None = placement automatique (étape 5).
    position: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    tail: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Onomatopée (kind = sfx) : {"intensity", "font", "size_pt", "angle", "skew"} ; une valeur absente ou
    # None = calculée par le lettrage. Son centre ajusté à la main est dans `position` ({"x", "y", "manual"}).
    sfx: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    panel: Mapped[Panel] = relationship(back_populates="bubbles")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    panel_id: Mapped[int | None] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(String(30))  # script | layout | generation | qc | qc_bench | finishing | …
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.pending)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0–100
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # Paramètres de la demande (génération : preset, prompt, seed, variante…).
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentProfile(TimestampMixin, Base):
    """Réglages d'un agent du pipeline édités dans l'UI : profil global (`project_id` vide) ou d'une série.

    `values` ne contient que les réglages modifiés (clé du réglage → valeur) ; le reste est hérité
    (série → profil global → presets livrés). Chaque modification crée une `AgentProfileVersion`.
    """

    __tablename__ = "agent_profiles"
    __table_args__ = (UniqueConstraint("agent_id", "project_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(60), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=0)

    versions: Mapped[list[AgentProfileVersion]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="AgentProfileVersion.version"
    )


class AgentProfileVersion(Base):
    """Une version d'un profil d'agent : valeurs complètes du profil, auteur, date et différences."""

    __tablename__ = "agent_profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("agent_profiles.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # [{key, before, after}] : valeurs effectives avant / après, pour l'historique.
    diff: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    author: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(20), default="save")  # save | restore | reset
    restored_from: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    profile: Mapped[AgentProfile] = relationship(back_populates="versions")


class KnowledgeCollection(TimestampMixin, Base):
    """Collection de fiches de savoir-faire : globale (`project_id` nul) ou propre à une série."""

    __tablename__ = "knowledge_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)

    documents: Mapped[list[KnowledgeDocument]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", order_by="KnowledgeDocument.id"
    )


class KnowledgeDocument(TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("knowledge_collections.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="text")  # text | md | txt | pdf
    original_name: Mapped[str | None] = mapped_column(String(255), default=None)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # Dernière erreur d'indexation (embeddings indisponibles : la recherche par mots-clés reste possible).
    index_error: Mapped[str | None] = mapped_column(Text, default=None)

    collection: Mapped[KnowledgeCollection] = relationship(back_populates="documents")
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="KnowledgeChunk.index"
    )


class KnowledgeChunk(Base):
    """Passage d'un document, avec son vecteur (float32 little-endian) et le modèle qui l'a produit."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("knowledge_collections.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(Text, default="")  # « Titre › Sous-titre »
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    embedding_model: Mapped[str | None] = mapped_column(String(200), default=None)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class SeriesBible(TimestampMixin, Base):
    """Bible d'une série : toujours injectée dans les agents de cette série (et d'elle seule)."""

    __tablename__ = "series_bibles"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True)
    world: Mapped[str] = mapped_column(Text, default="")  # univers
    tone: Mapped[str] = mapped_column(Text, default="")  # ton
    rules: Mapped[str] = mapped_column(Text, default="")  # règles de l'univers
    motifs: Mapped[str] = mapped_column(Text, default="")  # gags et motifs récurrents
    # Notes de la bible par fiche personnage : {"<character_id>": "caractère, rôle, arc…"}.
    character_notes: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    # Résumés des chapitres validés : [{"chapter_id", "number", "title", "summary", "added_at"}].
    chapter_summaries: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class LLMRun(Base):
    """Un appel d'agent LLM et ce qu'on lui a appris : passages reçus (titres, extraits, scores) et bible."""

    __tablename__ = "llm_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(50))  # rôle : script…
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    query: Mapped[str] = mapped_column(Text, default="")
    passages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    bible: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    collections: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PageDirection(TimestampMixin, Base):
    """Direction artistique d'une page (voir pipeline/art_direction.py).

    `values` : choix courants (proposition de l'agent, corrigée par l'auteur) — rythme, style, gabarit,
    page choc, justification, et par case (repérée par `panel_id`) intensité, plan, angle, cadre,
    ambiance, onomatopées. `locks` : champs modifiés par l'auteur, gardés quand l'agent repropose.
    `applied` : copie de `values` au dernier « Appliquer à la mise en page » (lue par la mise en page et
    le prompt image) ; None tant que rien n'est appliqué.
    """

    __tablename__ = "page_directions"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), unique=True, index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    locks: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | accepted
    applied: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    applied_at: Mapped[datetime | None] = mapped_column(default=None)
    variant: Mapped[int] = mapped_column(Integer, default=0)  # « Proposer autre chose » : nombre de relances

    page: Mapped[Page] = relationship(back_populates="direction")
