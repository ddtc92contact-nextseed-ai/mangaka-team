"""Packs de savoir-faire livrés (`presets/knowledge_packs/*.yaml` + leur fichier Markdown).

Un pack est un gros fichier Markdown de fiches (`## section` › `### ID — titre`, chaque fiche ouverte par une
ligne `path:` et un bloc ```` ```meta ```` en JSON) et un manifeste YAML qui range les sections en collections.

- **une fiche `###` = un document**, titré par le titre de la fiche ; une section `##` sans fiche est un seul
  document ; le chapeau d'une section à fiches, les sections de `skip` et l'en-tête du fichier ne sont pas
  importés ;
- le bloc meta (et la ligne `path:`) est **retiré du texte** embarqué et injecté ; ses champs sont gardés sur
  le document (`meta`) et donnent ses étiquettes. Un autre bloc JSON (exemple de format) devient une liste
  « champ : valeur » : aucun JSON n'arrive dans un prompt ;
- **pont de vocabulaire** : les codes `shot_scale` / `camera_angle` du meta sont traduits dans les termes de
  l'appli (`art_direction.PLANS` / `ANGLES`) et ajoutés, avec le titre, aux **mots-clés** du document : indexés
  en FTS, jamais injectés. Une case en « gros plan » « en contre-plongée » retrouve ainsi les bonnes fiches ;
- **idempotent** : un fichier inchangé ne change rien ; une fiche modifiée est seule réécrite et réindexée.
  Les collections et documents d'un pack (`pack` / `pack_key`) sont réécrits par une mise à jour ; ceux de
  l'utilisateur ne sont jamais touchés.

Lancé au démarrage du moteur et par « Mettre à jour les packs » (`POST /knowledge/packs/update`).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import KnowledgeSettings
from ..providers.embedding import EmbeddingError, EmbeddingProvider
from ..store.models import KnowledgeCollection, KnowledgeDocument
from .art_direction import ANGLES, PLANS
from .knowledge import fused_term, index_document

log = logging.getLogger("mangaka_engine")

PACKS_DIR = "knowledge_packs"


# --- manifeste ---------------------------------------------------------------------
class PackCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    sections: list[str] = Field(min_length=1)


class PackVocabulary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_scale: dict[str, str] = Field(default_factory=dict)
    camera_angle: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> PackVocabulary:
        known = set(PLANS) | set(ANGLES)
        unknown = sorted({t for t in [*self.shot_scale.values(), *self.camera_angle.values()] if t not in known})
        if unknown:
            raise ValueError(f"termes inconnus de l'appli (plans / angles de la direction artistique) : {unknown}")
        return self


class PackManifest(BaseModel):
    """Manifeste d'un pack (`presets/knowledge_packs/<id>.yaml`)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=100)
    file: str = Field(min_length=1)
    collections: list[PackCollection] = Field(min_length=1)
    skip: list[str] = Field(default_factory=list)
    vocabulary: PackVocabulary = Field(default_factory=PackVocabulary)

    @model_validator(mode="after")
    def _check(self) -> PackManifest:
        names = [c.name.casefold() for c in self.collections]
        if len(set(names)) != len(names):
            raise ValueError("deux collections du pack portent le même nom")
        sections = [s for c in self.collections for s in c.sections] + self.skip
        dupes = sorted({s for s in sections if sections.count(s) > 1})
        if dupes:
            raise ValueError(f"sections rangées deux fois : {dupes}")
        return self

    def collection_for(self, heading: str) -> PackCollection | None | bool:
        """Collection d'une section `##` ; False si elle est à ignorer ; None si le manifeste ne la cite pas."""
        for col in self.collections:
            if any(_matches(heading, s) for s in col.sections):
                return col
        return False if any(_matches(heading, s) for s in self.skip) else None


def _matches(heading: str, key: str) -> bool:
    return heading == key or heading.startswith(f"{key} ")


# --- lecture du fichier --------------------------------------------------------------
_FENCE = re.compile(r"^\s*(```+|~~~+)\s*([\w-]*)\s*$")
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H3 = re.compile(r"^###\s+(.+?)\s*$")
_PATH = re.compile(r"^\s*`?path:\s*([^`]+?)`?\s*$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_TITLE_SEP = re.compile(r"\s+[—–-]\s+")
_FICHE_ID = re.compile(r"^([A-Z][A-Z0-9_]*\d)\s+[—–-]\s+")


@dataclass
class PackEntry:
    """Un document à importer : fiche `###` ou section entière."""

    key: str  # identifiant stable dans le pack : id de la fiche, sinon titre de la section
    title: str
    collection: str
    content: str
    meta: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    keywords: str = ""


def _strip_front_matter(lines: list[str]) -> list[str]:
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return lines[i + 1 :]
    return lines


def _split(lines: list[str], pattern: re.Pattern[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(chapeau, [(titre, lignes)]) au niveau de titre `pattern`, hors blocs de code."""
    head: list[str] = []
    parts: list[tuple[str, list[str]]] = []
    fence: str | None = None
    for line in lines:
        m_fence = _FENCE.match(line)
        if m_fence and (fence is None or m_fence.group(1)[0] == fence):
            fence = None if fence else m_fence.group(1)[0]
        m = None if fence else pattern.match(line)
        if m:
            parts.append((m.group(1), []))
        elif parts:
            parts[-1][1].append(line)
        else:
            head.append(line)
    return head, parts


def _json_as_fields(raw: str) -> str | None:
    """Un bloc JSON objet → « - champ : valeur » (None si ce n'est pas un objet JSON)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    out = []
    for key, value in data.items():
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = ", ".join(f"{k} = {v}" for k, v in value.items())
        out.append(f"- {key} : {value}")
    return "\n".join(out)


def clean_body(lines: list[str]) -> tuple[str, dict[str, Any], str | None]:
    """(texte, meta, path) d'une fiche ou d'une section : bloc meta et ligne `path:` retirés, filets
    horizontaux enlevés, autres blocs JSON réécrits en liste de champs."""
    meta: dict[str, Any] = {}
    path: str | None = None
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE.match(line)
        if m:
            end = next((j for j in range(i + 1, len(lines)) if lines[j].strip().startswith(m.group(1))), len(lines))
            block = "\n".join(lines[i + 1 : end])
            lang = m.group(2).lower()
            if lang == "meta":
                try:
                    value = json.loads(block)
                except ValueError as exc:
                    raise PackError(f"bloc meta illisible ({exc})") from None
                if isinstance(value, dict):
                    meta.update(value)
            elif lang == "json" and (fields := _json_as_fields(block)) is not None:
                out += fields.splitlines()
            else:
                out += lines[i : end + 1]
            i = end + 1
            continue
        m_path = _PATH.match(line)
        if m_path and path is None and not any(o.strip() for o in out):
            path = m_path.group(1).strip()
        elif not _RULE.match(line):
            out.append(line)
        i += 1
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return text, meta, path


def _keywords(title: str, meta: dict[str, Any], vocabulary: PackVocabulary) -> str:
    """Titre de la fiche + termes de l'appli de son plan et de son angle, ces derniers aussi en un seul jeton
    (« gros plan grosplan ») pour que la requête « gros plan » le préfère aux fiches qui disent juste « plan »."""
    terms = [title]
    for code, table in (
        (meta.get("shot_scale"), vocabulary.shot_scale),
        (meta.get("camera_angle"), vocabulary.camera_angle),
    ):
        if isinstance(code, str) and code in table:
            terms += [table[code], fused_term(table[code])]
    return " · ".join(dict.fromkeys(t for t in terms if t))


def _tags(meta: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key in ("id", "type", "shot_scale", "camera_angle"):
        value = meta.get(key)
        if isinstance(value, str) and value and value != "variable":
            tags.append(value)
    intent = meta.get("intent")
    if isinstance(intent, list):
        tags += [str(t) for t in intent if str(t).strip()]
    return list(dict.fromkeys(t[:40] for t in tags))


class PackError(Exception):
    """Pack illisible (message en français)."""


@dataclass
class ParsedPack:
    entries: list[PackEntry]
    skipped: list[str]  # sections ignorées (skip du manifeste)
    unknown: list[str]  # sections que le manifeste ne cite pas (ignorées, signalées)


def parse_pack(content: str, manifest: PackManifest) -> ParsedPack:
    lines = _strip_front_matter(content.replace("\r\n", "\n").replace("\r", "\n").splitlines())
    _, sections = _split(lines, _H2)
    entries: list[PackEntry] = []
    skipped: list[str] = []
    unknown: list[str] = []
    for heading, body in sections:
        col = manifest.collection_for(heading)
        if col is False:
            skipped.append(heading)
            continue
        if col is None:
            unknown.append(heading)
            continue
        assert isinstance(col, PackCollection)
        _, fiches = _split(body, _H3)
        if not fiches:
            text, meta, _ = clean_body(body)
            if text:
                key = _TITLE_SEP.split(heading, maxsplit=1)[0].strip()[:120]
                entries.append(
                    PackEntry(key=key, title=heading[:200], collection=col.name, content=text, keywords=heading)
                )
            continue
        for title, fiche in fiches:
            try:
                text, meta, path = clean_body(fiche)
            except PackError as exc:
                raise PackError(f"« {title} » : {exc}") from None
            if not text:
                continue
            m_id = _FICHE_ID.match(title)
            key = str(meta.get("id") or (m_id.group(1) if m_id else title))[:120]
            if path:
                meta.setdefault("path", path)
            entries.append(
                PackEntry(
                    key=key,
                    title=title[:200],
                    collection=col.name,
                    content=text,
                    meta=meta,
                    tags=_tags(meta),
                    keywords=_keywords(title, meta, manifest.vocabulary),
                )
            )
    keys = [e.key for e in entries]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise PackError(f"identifiants de fiche en double : {dupes}")
    return ParsedPack(entries, skipped, unknown)


@dataclass
class LoadedPack:
    manifest: PackManifest
    parsed: ParsedPack


def load_manifest(path: Path) -> PackManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PackManifest.model_validate(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise PackError(f"manifeste illisible ({exc})") from None
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(x) for x in e['loc']) or 'manifeste'} : {e['msg']}" for e in exc.errors())
        raise PackError(f"manifeste invalide — {details}") from None


def load_pack(path: Path) -> LoadedPack:
    manifest = load_manifest(path)
    source = path.parent / manifest.file
    try:
        content = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackError(f"fichier du pack illisible : {manifest.file} ({exc.strerror or exc})") from None
    return LoadedPack(manifest, parse_pack(content, manifest))


# --- import --------------------------------------------------------------------------
@dataclass
class PackReport:
    pack: str
    collections: int = 0
    documents: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    skipped_sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


class _Embedder:
    """Embeddings partagés par tout un import : après une panne, on n'insiste pas (démarrage rapide si Ollama
    est éteint) ; les documents restent cherchables par mots-clés, « Réindexer » rattrapera les vecteurs."""

    def __init__(self, inner: EmbeddingProvider | None) -> None:
        self.inner = inner
        self.down: str | None = None
        self.name = inner.name if inner else "none"
        self.model_id = inner.model_id if inner else ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.inner is None:
            raise EmbeddingError("fournisseur d'embeddings indisponible")
        if self.down:
            raise EmbeddingError(self.down)
        try:
            return self.inner.embed(texts)
        except EmbeddingError as exc:
            self.down = str(exc)
            raise


def import_pack(
    session: Session, pack: LoadedPack, embedder: EmbeddingProvider | None, settings: KnowledgeSettings
) -> PackReport:
    """Synchronise la base avec un pack. Ne touche qu'aux collections `pack == id` et à leurs documents de pack."""
    manifest = pack.manifest
    report = PackReport(pack=manifest.id, skipped_sections=pack.parsed.skipped)
    report.warnings += [f"section non rangée par le manifeste (ignorée) : « {s} »" for s in pack.parsed.unknown]
    shared = _Embedder(embedder)
    owned = {
        c.name.casefold(): c
        for c in session.scalars(select(KnowledgeCollection).where(KnowledgeCollection.pack == manifest.id))
    }
    user_names = {
        n.strip().casefold()
        for n in session.scalars(
            select(KnowledgeCollection.name).where(
                KnowledgeCollection.project_id.is_(None), KnowledgeCollection.pack.is_(None)
            )
        )
    }
    collections: dict[str, KnowledgeCollection] = {}
    for spec in manifest.collections:
        key = spec.name.casefold()
        col = owned.pop(key, None)
        if col is None:
            if key in user_names:
                report.warnings.append(
                    f"une collection « {spec.name} » existe déjà (créée à la main) : elle n'est pas touchée, "
                    "ses fiches du pack ne sont pas importées"
                )
                continue
            col = KnowledgeCollection(name=spec.name, description=spec.description, project_id=None, pack=manifest.id)
            session.add(col)
            session.flush()
        elif col.name != spec.name or col.description != spec.description or col.project_id is not None:
            col.name, col.description, col.project_id = spec.name, spec.description, None
        collections[key] = col
    for stale in owned.values():  # collection retirée du manifeste
        report.deleted += sum(1 for d in stale.documents if d.pack_key)
        session.delete(stale)
    session.flush()

    existing: dict[str, KnowledgeDocument] = {
        d.pack_key: d
        for d in session.scalars(
            select(KnowledgeDocument)
            .join(KnowledgeCollection, KnowledgeDocument.collection_id == KnowledgeCollection.id)
            .where(KnowledgeCollection.pack == manifest.id, KnowledgeDocument.pack_key.is_not(None))
        )
        if d.pack_key
    }
    for entry in pack.parsed.entries:
        col = collections.get(entry.collection.casefold())
        if col is None:
            continue
        doc = existing.pop(entry.key, None)
        if doc is None:
            doc = KnowledgeDocument(source="md", original_name=manifest.file, pack_key=entry.key)
            col.documents.append(doc)
            _fill(doc, entry, manifest.file)
            session.flush()
            index_document(session, doc, shared, settings)  # type: ignore[arg-type]
            report.created += 1
        elif _differs(doc, entry, col, manifest.file):
            reindex = (doc.title, doc.content, doc.keywords) != (entry.title, entry.content, entry.keywords)
            moved = doc.collection_id != col.id
            if moved:
                doc.collection = col
            _fill(doc, entry, manifest.file)
            session.flush()
            if reindex or moved:
                index_document(session, doc, shared, settings)  # type: ignore[arg-type]
            report.updated += 1
        else:
            report.unchanged += 1
    for gone in existing.values():  # fiche retirée du fichier
        session.delete(gone)
        report.deleted += 1
    session.flush()
    report.collections = len(collections)
    report.documents = report.created + report.updated + report.unchanged
    if shared.down:
        report.warnings.append(
            f"vecteurs non calculés : {shared.down} (recherche par mots-clés ; « Réindexer » ensuite)"
        )
    return report


def _fill(doc: KnowledgeDocument, entry: PackEntry, filename: str) -> None:
    doc.title = entry.title
    doc.content = entry.content
    doc.meta = dict(entry.meta)
    doc.tags = list(entry.tags)
    doc.keywords = entry.keywords
    doc.source = "md"
    doc.original_name = filename


def _differs(doc: KnowledgeDocument, entry: PackEntry, col: KnowledgeCollection, filename: str) -> bool:
    return (
        doc.collection_id != col.id
        or doc.title != entry.title
        or doc.content != entry.content
        or (doc.meta or {}) != entry.meta
        or list(doc.tags or []) != entry.tags
        or (doc.keywords or "") != entry.keywords
        or doc.original_name != filename
    )


def manifests(presets_dir: Path) -> list[Path]:
    folder = presets_dir / PACKS_DIR
    return sorted(folder.glob("*.y*ml")) if folder.is_dir() else []


def update_packs(
    session: Session, presets_dir: Path, embedder: EmbeddingProvider | None, settings: KnowledgeSettings
) -> list[PackReport]:
    """Importe (ou met à jour) tous les packs de `presets/knowledge_packs/`. Un pack illisible est signalé et
    laissé tel quel en base ; les autres sont importés."""
    reports = []
    for path in manifests(presets_dir):
        try:
            pack = load_pack(path)
        except PackError as exc:
            reports.append(PackReport(pack=path.stem, error=str(exc)))
            log.warning("pack de savoir-faire ignoré — %s : %s", path.name, exc)
            continue
        report = import_pack(session, pack, embedder, settings)
        for warning in report.warnings:
            log.warning("pack de savoir-faire %s : %s", report.pack, warning)
        reports.append(report)
    return reports
