"""Modèle de données SQLite (SQLAlchemy 2).

Série (`Project`) → Character (+ images de référence)
Série → SeriesAsset : objets et décors récurrents de la bibliothèque (+ images de référence), et
références de style de la planche de style (`kind = style` : une seule active, les autres en historique)
Série → SeriesLocation : lieux de la série (unité de lieu des cases, décor de la bibliothèque rattaché)
Série → ReferenceVariant : images générées par « Créer des références » d'une fiche, gardées ou non
Série → Volume (tome : chapitres inclus dans l'ordre via `VolumeChapter`, format et versions de couverture
`VolumeCover`)
Série → Chapter → Page → Panel (+ versions d'image → annotation humaine) → Bubble · Job.
Chapter → ChapterScene : scènes du chapitre (ordre, type, pages ; validées par l'auteur), chaque page de l'histoire
rattachée à sa scène (`Page.scene_id`).
Banc d'essai du QC : `QCBenchRun` (historique des mesures du QC sur les cases annotées).
Savoir-faire : `KnowledgeCollection` (globale ou d'une série) → `KnowledgeDocument` → `KnowledgeChunk`
(+ index plein texte FTS5 `knowledge_fts`, tenu à jour par des triggers) · `SeriesBible` (une par série)
· `LLMRun` (passages reçus par chaque appel du LLM).
Direction artistique : `PageDirection` (une par page : proposition de l'agent, champs verrouillés par
l'auteur, version appliquée à la mise en page et aux prompts).
Traçabilité : `GenerationLog` (une ligne par génération ComfyUI, jamais réécrite) → `GenerationEvent`
(verdicts de l'auteur : gardée, rejetée, régénérée, retouchée).
Garde d'étapes : `ChapterStageDecision` (validation d'une étape vitale du chapitre, passer-outre, levée).
Identité visuelle : palette retenue et propositions (colonnes de `Project`) · `SeriesLogo` (versions du logo).
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


# Ids jamais réutilisés (AUTOINCREMENT) pour les tables dont l'id finit dans l'URL d'un fichier servi ou dans
# un dossier de data/ (séries, chapitres, pages) : sans cela SQLite reprend max(id) + 1 après une suppression,
# et une URL ou un dossier recyclé montrerait les images supprimées.
NEVER_REUSED = {"sqlite_autoincrement": True}


class Project(TimestampMixin, Base):
    """Une série (table historique `projects`)."""

    __tablename__ = "projects"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    # Nom du dossier de la série dans ComfyUI (store/slugs.py) : tiré du titre, unique, jamais `old`.
    slug: Mapped[str] = mapped_column(String(120), default="", server_default="", index=True)
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
    # CFG des cases (1 à 3) pour les presets non distillés ; None = celui du palier (`defaults.cfg`).
    # À cfg 1, le prompt négatif n'est pas lu. Les presets distillés (Turbo, croquis) gardent cfg 1.
    cfg: Mapped[float | None] = mapped_column(Float, default=None)
    # « Prompt rédigé par l'IA » : le LLM du dessinateur écrit le prompt image de chaque case en un
    # paragraphe (pipeline/prompt_writer.py) ; False = assemblage par fragments (image_prompt.yaml#parts).
    # Nouvelles séries : `enabled` de presets/prompts/redacteur-image.yaml ; séries d'avant la v21 : False.
    ai_prompt: Mapped[bool] = mapped_column(default=True)
    # Prompt image (#228) : « détaillé » (fragments ou paragraphe du rédacteur, ci-dessus) ou « gabarit » (prompt
    # court assemblé par le moteur, pipeline/prompt_template.py) ; None = `image_prompt_mode` de defaults.yaml.
    image_prompt_mode: Mapped[str | None] = mapped_column(String(20), default=None)
    # « Cohérence anime » : LoRA d'identité (presets/camera_loras.yaml) ajouté aux générations de la série
    # dont le palier le permet (Qualité) ; désactivé par défaut.
    anime_consistency: Mapped[bool] = mapped_column(default=False)
    # Identité visuelle (pipeline/identity.py) : palette retenue {"name", "explanation", "colors": [{"role", "hex"}]}
    # (None = pas encore choisie), dernières palettes et derniers concepts de logo proposés par l'IA.
    palette: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    palette_proposals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    logo_proposals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    # Nom d'auteur imprimé sur la couverture des tomes (un tome peut le remplacer : `Volume.author`).
    author: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # ADN de la série (presets/pre_direction.yaml) : seules les valeurs ajustées par l'auteur, par chemin
    # ({"shots.wide.min": 0.2}) ; tout le reste est hérité du genre (pipeline/pre_direction.py `series_dna`).
    pre_direction: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    # Profils de tempo des types de scène (presets/scene_types.yaml) ajustés par la série, par type et chemin
    # ({"combat.panels.max_per_page": 7}) ; le reste vient du preset (pipeline/pre_direction.py `tempo_profile`).
    scene_tempo: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    characters: Mapped[list[Character]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Character.name"
    )
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Chapter.number"
    )
    assets: Mapped[list[SeriesAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SeriesAsset.name"
    )
    volumes: Mapped[list[Volume]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Volume.number"
    )
    logos: Mapped[list[SeriesLogo]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SeriesLogo.version"
    )
    locations: Mapped[list[SeriesLocation]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="SeriesLocation.name"
    )
    # Charte des couvertures (pipeline/cover_charter.py) ; None = réglages par défaut de cover_charter.yaml.
    cover_charter: Mapped[CoverCharter | None] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )


class Character(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Dossier de la fiche dans ComfyUI (`<série>/personnages/<slug>`) : tiré du nom, unique dans la série.
    slug: Mapped[str] = mapped_column(String(120), default="", server_default="")
    visual_description: Mapped[str] = mapped_column(Text, default="")
    prompt_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    lora_name: Mapped[str | None] = mapped_column(String(255), default=None)
    lora_weight: Mapped[float] = mapped_column(Float, default=0.8)
    lora_trigger_words: Mapped[str] = mapped_column(Text, default="")  # ajoutés au prompt avec le LoRA
    # Autres noms du personnage (« le petit dragon », « Urus le dragon ») : reconnus par le scénario.
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    # Ancre visuelle (≈ 15 mots, anglais : cheveux, peau, tenue) du prompt image « gabarit » ; vide = résumé de
    # la description visuelle.
    visual_anchor: Mapped[str] = mapped_column(Text, default="", server_default="")

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
    # Angle de caméra de la vue (`id` d'un angle de presets/camera_loras.yaml) : posé par « Nouvel angle » ou à
    # la main ; None = non étiquetée (la principale vaut alors `main_view`).
    angle: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    character: Mapped[Character] = relationship(back_populates="reference_images")


class AssetKind(enum.StrEnum):
    object = "object"  # objet récurrent : un robot, une épée, un sac…
    decor = "decor"  # décor récurrent : la salle de classe, le labo, la rue…
    style = "style"  # référence de style de la planche de style (une seule active par série)
    vehicle = "vehicle"  # véhicule récurrent : le vaisseau, la voiture, la moto, le mécha piloté…
    creature = "creature"  # créature récurrente : l'animal de compagnie, le monstre (ne parle pas par défaut)


# Sortes rattachées aux cases par `Panel.object_ids` (liste « objets » du scénario et de la direction
# artistique) : un véhicule ou une créature apparaît dans une case comme un objet, avec sa fiche à elle.
PANEL_OBJECT_KINDS = (AssetKind.object, AssetKind.vehicle, AssetKind.creature)


class SeriesAsset(TimestampMixin, Base):
    """Objet, décor, véhicule ou créature récurrent de la bibliothèque d'une série (mêmes champs qu'un
    personnage). Un objet, un véhicule ou une créature peut changer de sorte (`PANEL_OBJECT_KINDS`) en gardant
    ses images et ses variantes (api/assets.py).

    Une référence de style (`kind = style`) a une seule image : l'essai de la planche de style passé au
    propre ; `visual_description` garde le `$style` de la série au moment des essais.
    """

    __tablename__ = "series_assets"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind))
    name: Mapped[str] = mapped_column(String(120))
    # Dossier dans ComfyUI (`<série>/objets|decors|vehicules|creatures|style/<slug>`) : tiré du nom, unique par
    # sorte dans la série.
    slug: Mapped[str] = mapped_column(String(120), default="", server_default="")
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
    angle: Mapped[str | None] = mapped_column(String(40), default=None)  # comme CharacterImage.angle
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    asset: Mapped[SeriesAsset] = relationship(back_populates="reference_images")


class SeriesLocation(TimestampMixin, Base):
    """Lieu de la série (la clairière, la crique, le labo) : l'unité de lieu à laquelle les cases se rattachent
    (`Panel.location_id`). Son décor de la bibliothèque (`decor_id`, id de `series_assets`, sans clé étrangère
    comme `Panel.decor_id`) donne la référence de lieu de chaque case rattachée (pipeline/locations.py)."""

    __tablename__ = "series_locations"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    decor_id: Mapped[int | None] = mapped_column(Integer, default=None)

    project: Mapped[Project] = relationship(back_populates="locations")


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
    # character | object | decor | vehicle | creature ; `style` : essai de la planche de style (entry_id = id de la série).
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
    __table_args__ = (UniqueConstraint("project_id", "number"), NEVER_REUSED)

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
    # Étape « Scènes » (pipeline/scenes.py) : validation de la liste par l'auteur (l'éditeur) — None = pas validée ;
    # une retouche de la liste la retire. `scenes_deferred` : ce que le découpage en scènes reporte au chapitre
    # suivant (jamais tassé dans celui-ci).
    scenes_validated_at: Mapped[datetime | None] = mapped_column(default=None)
    scenes_validated_by: Mapped[str] = mapped_column(String(120), default="", server_default="")
    scenes_deferred: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")

    project: Mapped[Project] = relationship(back_populates="chapters")
    pages: Mapped[list[Page]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="Page.number"
    )
    scenes: Mapped[list[ChapterScene]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="ChapterScene.position"
    )


class ChapterScene(TimestampMixin, Base):
    """Scène d'un chapitre (pipeline/scenes.py) : place dans le chapitre, titre, résumé en une ou deux phrases, type
    (liste fermée de presets/scene_types.yaml, qui donne son profil de tempo), nombre de pages et lieu de la série
    facultatif. La somme des pages des scènes vaut `Chapter.target_page_count` une fois validée."""

    __tablename__ = "chapter_scenes"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    scene_type: Mapped[str] = mapped_column(String(40))
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("series_locations.id", ondelete="SET NULL"), default=None, index=True
    )
    # Distribution de la scène : fiches personnages qui y jouent (ids, dans l'ordre), proposée par l'agent et
    # validée par l'auteur ; elle descend sur les cases de la scène (pipeline/scene_cast.py). Une fiche supprimée
    # est ignorée.
    character_ids: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")

    chapter: Mapped[Chapter] = relationship(back_populates="scenes")


class Volume(TimestampMixin, Base):
    """Tome d'une série : numéro unique dans la série, chapitres inclus (dans l'ordre, un chapitre dans un seul
    tome) et couverture (format, personnages, intention, prompt, versions générées, version retenue)."""

    __tablename__ = "volumes"
    __table_args__ = (UniqueConstraint("project_id", "number"), NEVER_REUSED)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    # Format de couverture (presets/cover_formats/).
    cover_format: Mapped[str] = mapped_column(String(100))
    # Couverture : personnages choisis (ids, dans l'ordre des images de référence), intention de l'auteur
    # (français), prompt image (rédigé par l'IA ou à la main), version retenue.
    cover_character_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    cover_intent: Mapped[str] = mapped_column(Text, default="")
    cover_prompt: Mapped[str] = mapped_column(Text, default="")
    # `ai` (rédigé par l'IA, non retouché) | `manual` (saisi ou retouché) | None (pas encore de prompt).
    cover_prompt_source: Mapped[str | None] = mapped_column(String(20), default=None)
    cover_prompt_notes: Mapped[str] = mapped_column(Text, default="")
    selected_cover_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # Composition de la couverture (pipeline/cover_composition.py). Nom d'auteur du tome (vide : celui de la série).
    author: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # 1re de couverture : placement du logo {"logo": {"cx", "cy" (centre, fraction du format rogné), "scale"}}.
    cover_layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    # 4e de couverture : résumé et accroche (rédigés par l'IA ou à la main), gabarit (presets/back_layouts/),
    # petite illustration {"source": "panel" | "generated", "id": id de la version}, prompt de sa génération.
    back_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    back_tagline: Mapped[str] = mapped_column(String(300), default="", server_default="")
    back_summary_source: Mapped[str | None] = mapped_column(String(20), default=None)  # ai | manual | None
    back_summary_notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    back_layout: Mapped[str | None] = mapped_column(String(100), default=None)
    back_image: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    back_prompt: Mapped[str] = mapped_column(Text, default="", server_default="")

    project: Mapped[Project] = relationship(back_populates="volumes")
    chapter_links: Mapped[list[VolumeChapter]] = relationship(
        back_populates="volume", cascade="all, delete-orphan", order_by="VolumeChapter.position"
    )
    covers: Mapped[list[VolumeCover]] = relationship(
        back_populates="volume", cascade="all, delete-orphan", order_by="VolumeCover.id"
    )


class VolumeChapter(Base):
    """Chapitre inclus dans un tome, à sa place (`position`) ; `chapter_id` unique : un chapitre, un seul tome."""

    __tablename__ = "volume_chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    volume_id: Mapped[int] = mapped_column(ForeignKey("volumes.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), unique=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    volume: Mapped[Volume] = relationship(back_populates="chapter_links")
    chapter: Mapped[Chapter] = relationship()


class VolumeCover(Base):
    """Version générée d'une illustration de couverture d'un tome : `front` (1re de couverture, fond perdu compris,
    au DPI du format) ou `back` (petite illustration de 4e, ratio et taille de cover_composition.yaml)."""

    __tablename__ = "volume_covers"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    volume_id: Mapped[int] = mapped_column(ForeignKey("volumes.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), default=None)
    path: Mapped[str] = mapped_column(String(500))  # relatif à data/
    content_type: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer, default=None)
    cover_format: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="front", server_default="front")
    # Workflow, agrandisseur, prompts, références envoyées, taille générée, durée…
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    volume: Mapped[Volume] = relationship(back_populates="covers")


class Page(TimestampMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("chapter_id", "number"), NEVER_REUSED)

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
    # Scène du chapitre à laquelle appartient la page (None : page bonus, ou chapitre écrit sans scènes).
    scene_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapter_scenes.id", ondelete="SET NULL"), default=None, index=True
    )

    chapter: Mapped[Chapter] = relationship(back_populates="pages")
    panels: Mapped[list[Panel]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="Panel.index"
    )
    direction: Mapped[PageDirection | None] = relationship(
        back_populates="page", cascade="all, delete-orphan", uselist=False
    )
    # « Valider la name » (palier croquis, voir pipeline/name_board.py) ; None = page pas encore validée.
    name_validation: Mapped[PageNameValidation | None] = relationship(
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
    # Personnages PRÉSENTS À L'IMAGE, noms tels qu'écrits par le scénario (personnages secondaires compris) :
    # dessinés, avec leur image de référence (`character_ids` : leurs fiches).
    character_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Personnages cités par la case mais HORS CADRE (« ils voient les trafiquants » : les spectateurs d'une
    # vue subjective) : jamais dessinés ni pourvus d'image de référence (pipeline/framing.py).
    offscreen_names: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    # Choix de l'auteur sur la case, jamais écrasés par la descente de la scène (pipeline/scene_cast.py) :
    # personnages (présents / hors cadre) corrigés à la main, lieu choisi (ou retiré) à la main, et fiches
    # laissées hors cadre malgré une action visible dans le texte (« Laisser hors cadre » : plus d'alerte, et
    # l'action est retirée du prompt image).
    cast_manual: Mapped[bool] = mapped_column(default=False, server_default="0")
    location_manual: Mapped[bool] = mapped_column(default=False, server_default="0")
    offscreen_kept: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    # Point de vue d'un spectateur : {"mode": "reaction"|"subjective", "spectators": [noms],
    # "source": "direction"|"défaut"|"auteur"} ; None = case sans spectateur (ou choix pas encore fait).
    viewpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Bibliothèque de la série : décor de la case et objets visibles (ids de `series_assets`, sans clé
    # étrangère : un objet ou un décor supprimé est retiré des cases par l'API, ignoré sinon).
    decor_id: Mapped[int | None] = mapped_column(Integer, default=None)
    object_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Lieu de la série où se passe la case (unité de lieu, `SeriesLocation`) ; None = pas encore rattachée.
    # Son décor sert de décor à la case quand `decor_id` est vide (référence de lieu, pipeline/library.py).
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("series_locations.id", ondelete="SET NULL"), default=None, index=True
    )
    shot_type: Mapped[str | None] = mapped_column(String(50), default=None)
    # Donnés par le scénario (pipeline/brief.py, un rôle par champ) : décor de la case (moment et éléments visibles
    # du lieu `location_id`, jamais de plan ni de personnage) et mise en scène (pose, geste, regard, place dans
    # l'image des seuls présents) ; vides pour les cases d'avant (le prompt les omet alors).
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
    # Origine du prompt automatique : "ia" (rédigé par le LLM) | "fragments" (assemblage) ; None = jamais
    # construit. `prompt_key` : empreinte des données de la case au moment de la rédaction (le prompt
    # rédigé n'est redemandé que si elle change, ou sur « Reconstruire le prompt ») ; `prompt_warning` :
    # rédaction en échec, repli par fragments (affiché sur la case).
    prompt_source: Mapped[str | None] = mapped_column(String(20), default=None)
    prompt_key: Mapped[str | None] = mapped_column(String(64), default=None)
    prompt_warning: Mapped[str | None] = mapped_column(Text, default=None)
    # Empreinte du savoir-faire que lisait le rédacteur au moment de la rédaction (collections de l'agent
    # « image_prompt », leurs documents et passages, budget et top-k du rédacteur) : quand elle change (pack
    # importé ou mis à jour, document ajouté ou retiré, réindexation, budget réglé dans « L'équipe »), le
    # prompt rédigé est redemandé à la prochaine génération. None : rédigé avant (ou jamais).
    prompt_knowledge: Mapped[str | None] = mapped_column(String(64), default=None)
    # « Sources utilisées » du prompt rédigé : {"written_at", "query", "collections", "passages", "bible"} —
    # ce que le rédacteur a reçu pour le prompt actuel ; None : prompt jamais rédigé par l'IA.
    prompt_sources: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
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
    # Dialogue avec l'IA sur cette case (« Appliquer », voir pipeline/prompt_dialog.py) : direction
    # artistique propre à la case ({"plan", "angle", "action", "ambiance"}, par-dessus celle de la page) et
    # image de référence choisie par personnage ({"<id du personnage>": id de `character_images`}).
    # Gardées jusqu'à « Reconstruire le prompt » ; None = rien d'imposé.
    dialog_direction: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    reference_choice: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Cadrage manuel de l'image dans la case (« Recadrer », voir pipeline/crop.py) : {"x", "y", "zoom"} —
    # centre de la fenêtre en fraction de l'image et zoom sur le remplissage ; None = centrée au remplissage.
    crop: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    qc_score: Mapped[int | None] = mapped_column(Integer, default=None)
    state: Mapped[PanelState] = mapped_column(_enum(PanelState), default=PanelState.draft)

    page: Mapped[Page] = relationship(back_populates="panels")
    location: Mapped[SeriesLocation | None] = relationship()
    images: Mapped[list[PanelImage]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="PanelImage.version"
    )
    bubbles: Mapped[list[Bubble]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="Bubble.order"
    )
    dialog: Mapped[list[PanelDialogTurn]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", order_by="PanelDialogTurn.id"
    )


class PanelDialogTurn(Base):
    """Un échange du dialogue avec l'IA sur une case : la consigne de l'auteur, ce que l'IA propose
    (`proposal` : prompt, direction, références, changements lisibles), l'état de la case avant
    (`before`) et le sort de la proposition (`status` : proposed | applied | cancelled)."""

    __tablename__ = "panel_dialog_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    instruction: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    proposal: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(default=None)

    panel: Mapped[Panel] = relationship(back_populates="dialog")


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
    # `position` peut aussi porter "size_pt", la taille du texte saisie à la main (sans "manual" ni cadre
    # si la bulle reste placée automatiquement).
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
    # Pack de savoir-faire livré (presets/knowledge_packs/) qui possède la collection : réécrite par la mise à
    # jour du pack, en lecture seule dans l'UI. Nul : collection de l'utilisateur, jamais touchée par un pack.
    pack: Mapped[str | None] = mapped_column(String(100), default=None, index=True)

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
    # Document d'un pack : identifiant de la fiche dans le pack (ex. « SHOT_CU_001 », ou la section), champs
    # du bloc meta retiré du texte, et mots-clés ajoutés à l'index FTS seulement (titre, pont de vocabulaire).
    pack_key: Mapped[str | None] = mapped_column(String(120), default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    keywords: Mapped[str] = mapped_column(Text, default="")

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
    # Mots-clés du document (packs) : indexés en FTS avec le passage, jamais injectés dans un prompt.
    keywords: Mapped[str] = mapped_column(Text, default="")
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
    `applied` : copie de `values` à la dernière application (lue par la mise en page et le prompt image),
    plus les plans du scénario d'avant la première (`script_shots`) ; None tant que rien n'est appliqué.
    `status` : proposed | applied | rejected (voir `pipeline/art_direction.STATUSES` ; « accepted » :
    ancienne validation).
    """

    __tablename__ = "page_directions"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), unique=True, index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    locks: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | applied | rejected
    applied: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    applied_at: Mapped[datetime | None] = mapped_column(default=None)
    variant: Mapped[int] = mapped_column(Integer, default=0)  # « Proposer autre chose » : nombre de relances

    page: Mapped[Page] = relationship(back_populates="direction")


class PageNameValidation(Base):
    """Name validée d'une page (pipeline/name_board.py) : empreinte des cases au moment de la validation
    (`key` : ids, ordre, description, plan, croquis retenu). Une case modifiée depuis (description, plan,
    découpe, croquis) rend la validation caduque : la page n'est plus validée, sans rien effacer."""

    __tablename__ = "page_name_validations"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), unique=True, index=True)
    key: Mapped[str] = mapped_column(String(64))
    author: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    page: Mapped[Page] = relationship(back_populates="name_validation")


class GenerationLog(Base):
    """Journal des générations : une ligne par génération ComfyUI terminée ou en échec (case, croquis, passage
    au propre, réparation, angle, fiche de référence, essai de style, A/B). Jamais réécrite : une
    régénération ajoute une ligne. Les ids de la série, du chapitre, de la page, de la case et de l'image
    sont de simples entiers (pas de clé étrangère) : la ligne survit à la suppression de ce qu'elle décrit.
    Aucune donnée personnelle ni clé : prompts, réglages, mesures."""

    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # voir pipeline/journal.py : KINDS
    status: Mapped[str] = mapped_column(String(20), default="succeeded")  # succeeded | failed | cancelled
    error: Mapped[str | None] = mapped_column(Text, default=None)
    job_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    chapter_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    page_id: Mapped[int | None] = mapped_column(Integer, default=None)
    panel_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    # Image produite : version de case (`panel_image`) ou variante de fiche (`reference_variant`).
    image_kind: Mapped[str | None] = mapped_column(String(30), default=None)
    image_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    version: Mapped[int | None] = mapped_column(Integer, default=None)
    # Workflow et réglages effectivement envoyés.
    preset: Mapped[str | None] = mapped_column(String(100), default=None)
    tier: Mapped[str | None] = mapped_column(String(40), default=None)
    model: Mapped[str | None] = mapped_column(String(255), default=None)  # fichier du modèle (unet / ckpt)
    steps: Mapped[int | None] = mapped_column(Integer, default=None)
    cfg: Mapped[float | None] = mapped_column(Float, default=None)
    seed: Mapped[int | None] = mapped_column(Integer, default=None)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    denoise: Mapped[float | None] = mapped_column(Float, default=None)
    positive_prompt: Mapped[str] = mapped_column(Text, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    positive_chars: Mapped[int] = mapped_column(Integer, default=0)
    positive_words: Mapped[int] = mapped_column(Integer, default=0)
    negative_chars: Mapped[int] = mapped_column(Integer, default=0)
    negative_words: Mapped[int] = mapped_column(Integer, default=0)
    prompt_source: Mapped[str | None] = mapped_column(String(20), default=None)  # ia | fragments | manuel
    # Empreinte des consignes du rédacteur de prompt (prompts/redacteur-image.yaml + profil « L'équipe »).
    writer_hash: Mapped[str | None] = mapped_column(String(16), default=None)
    references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{kind, id, image_id}]
    loras: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{name, weight, source}]
    # Savoir-faire reçu : [{document_id, title, collection, tokens}].
    knowledge: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Garde-fou du prompt (#227) : noms de personnages absents de la case retirés du prompt envoyé
    # [{name, removed}] (pipeline/brief.py `strip_absent`) ; vide : rien retiré.
    prompt_guard: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    framing: Mapped[str | None] = mapped_column(String(100), default=None)  # plan
    angle: Mapped[str | None] = mapped_column(String(100), default=None)
    mood: Mapped[str | None] = mapped_column(String(200), default=None)  # ambiance
    finish: Mapped[str | None] = mapped_column(String(100), default=None)  # finition (si le réglage existe)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # Mesures de tonalité (presets/qc_tonality.yaml), en % ; None : génération en échec.
    dark_pct: Mapped[float | None] = mapped_column(Float, default=None)
    black_pct: Mapped[float | None] = mapped_column(Float, default=None)
    white_pct: Mapped[float | None] = mapped_column(Float, default=None)
    saturation_pct: Mapped[float | None] = mapped_column(Float, default=None)
    line_density_pct: Mapped[float | None] = mapped_column(Float, default=None)
    # Comparaison A/B : groupe commun aux deux bras, bras (A | B) et ce qui varie (prompt | tier | cfg).
    ab_group: Mapped[str | None] = mapped_column(String(40), default=None, index=True)
    ab_arm: Mapped[str | None] = mapped_column(String(1), default=None)
    ab_mode: Mapped[str | None] = mapped_column(String(20), default=None)


class GenerationEvent(Base):
    """Verdict de l'auteur sur une génération : chaque action (choisir, valider un croquis, supprimer,
    régénérer, recadrer, réparer, juger, choix d'un A/B…) ajoute un événement, jamais réécrit."""

    __tablename__ = "generation_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    log_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    panel_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    image_kind: Mapped[str | None] = mapped_column(String(30), default=None)
    image_id: Mapped[int | None] = mapped_column(Integer, default=None)
    verdict: Mapped[str] = mapped_column(String(20))  # validated | rejected | regenerated | edited
    action: Mapped[str] = mapped_column(String(30))  # select | delete | judge | crop | repair | …
    reason: Mapped[str | None] = mapped_column(String(60), default=None)  # id de journal.yaml
    note: Mapped[str] = mapped_column(Text, default="")


class ChapterStageDecision(Base):
    """Décision sur une étape vitale d'un chapitre (voir pipeline/stage_gate.py) : `validated` (l'étape était
    complète quand une action l'a franchie), `forced` (« Passer outre » de l'auteur) ou `revoked` (passer-outre
    levé). Jamais réécrite : l'état d'une étape est sa dernière décision. Ids de simples entiers (comme le
    journal) : la trace survit à la suppression du chapitre."""

    __tablename__ = "chapter_stage_decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    chapter_id: Mapped[int] = mapped_column(Integer, index=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, default=None)
    stage: Mapped[str] = mapped_column(String(30))  # voir pipeline/stage_gate.py : STAGES
    decision: Mapped[str] = mapped_column(String(20))  # validated | forced | revoked
    author: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # Éléments en faute au moment de la décision (un passer-outre garde ce qu'il a laissé passer).
    faults: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)


class ChapterCrowdMark(Base):
    """« Foule sans fiche » : une foule anonyme citée par le scénario (« des passants », « la foule ») que l'auteur
    dispense de fiche dans ce chapitre (voir pipeline/cast.py). Seule sortie de la distribution : tracée (qui,
    quand) et réversible — lever la marque remplit `revoked_at` / `revoked_by`, la ligne reste. Table ajoutée
    sans migration de données (créée vide au démarrage)."""

    __tablename__ = "chapter_crowd_marks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    project_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))  # tel qu'écrit par le scénario
    name_key: Mapped[str] = mapped_column(String(120))  # pipeline/names.py : name_key
    author: Mapped[str] = mapped_column(String(120), default="")
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_by: Mapped[str] = mapped_column(String(120), default="")


class SeriesLogo(Base):
    """Une version enregistrée du logo du titre de la série (pipeline/logo.py) : réglages complets du logo
    (police, lignes, effet, couleurs…), rendus à la demande en SVG et PNG. Jamais réécrite : le logo de la
    série est la dernière version ; reprendre une ancienne version en crée une nouvelle."""

    __tablename__ = "series_logos"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    project: Mapped[Project] = relationship(back_populates="logos")


class CoverCharter(TimestampMixin, Base):
    """Charte des couvertures d'une série (pipeline/cover_charter.py) : choix bornés de presets/cover_charter.yaml
    {"palette_mode", "mood", "shot", "back_shot", "logo_place", "subject"} et personnages admis en couverture
    (`character_ids`, dans l'ordre). Une ligne par série, créée au premier enregistrement (table ajoutée sans
    migration de données : `create_all`)."""

    __tablename__ = "cover_charters"
    __table_args__ = NEVER_REUSED

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    character_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    project: Mapped[Project] = relationship(back_populates="cover_charter")


class AppSetting(TimestampMixin, Base):
    """Réglage de l'atelier (écran Réglages), une ligne par clé — `author_name` : « Ton nom », auteur par défaut
    des validations et décisions d'étape (voir pipeline/app_settings.py). L'appli est locale et sans compte : le
    nom vit ici, pas seulement dans le navigateur. Table ajoutée sans migration de données (`create_all`)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    value: Mapped[str] = mapped_column(Text, default="")
