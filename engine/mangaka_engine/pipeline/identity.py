"""Identité visuelle de la série : palettes de couleurs et concepts de logo proposés par l'IA (mini-pipelines).

Palette et logo appartiennent à la série (les mêmes d'un tome à l'autre). Deux agents LLM (LLM du
« Directeur artistique », prompts `presets/prompts/palette.yaml` et `logo.yaml`) :

- palettes : à partir de la bible, des packs de style (genre, ton), des fiches personnages et de la référence de
  style active (sa description et les couleurs dominantes de son image), l'agent propose de 3 à 5 palettes
  (`identity.yaml › palette`) ; chaque palette : nom, 5 à 7 couleurs `#rrggbb` avec un rôle, une explication ;
- logos : à partir de la palette retenue, l'agent propose de 4 à 6 concepts typographiques — police et effet
  choisis parmi les presets, disposition du titre (une ou deux lignes, taille relative), inclinaison,
  interlettrage, couleurs (rôles de la palette ou `#rrggbb`), sous-titre. Rendu : `logo.py`.

Chaque réponse est validée (Pydantic, puis cohérence avec les presets et le titre) ; une réponse invalide est
renvoyée à l'agent avec l'erreur (`max_retries` du prompt, 2 au plus), puis `IdentityError` lisible. Un
concept dont le texte contraste trop peu avec son contour voit son contour corrigé (`fix_contrast`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..presets import PresetRegistry, PromptPreset
from ..presets.schemas import HEX_COLOR, IdentitySettings, LogoStyle
from ..providers.llm import ChatMessage, LLMError, LLMProvider
from ..store.files import FileStore
from ..store.models import AssetKind, Character, Project, SeriesAsset
from ..validation import format_errors
from .knowledge import render_bible
from .logo import LogoColors, LogoLine, LogoSpec, fix_contrast, logo_contrast, spec_problems
from .script import _render
from .style import style_brief

AGENT_ID = "directeur-artistique"  # agent dont le LLM répond (écran « L'équipe »)
PALETTE_PROMPT = "palette"
LOGO_PROMPT = "logo"
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class IdentityError(Exception):
    """L'agent n'a pas pu proposer (LLM indisponible, réponses invalides) : message lisible pour l'auteur."""


class IdentityValidationError(ValueError):
    """Réponse du LLM refusée (message renvoyé à l'agent pour qu'il corrige)."""


# --- palette ---------------------------------------------------------------------------------------------
class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def role_key(value: str) -> str:
    """« Texte clair » → « texte-clair » (rôles écrits à la main ou par le LLM)."""
    return "-".join(value.strip().casefold().replace("_", " ").split())


class PaletteColor(_Model):
    role: str
    hex: str = Field(pattern=HEX_COLOR)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        return role_key(v)

    @field_validator("hex")
    @classmethod
    def _hex(cls, v: str) -> str:
        return v.lower()


class Palette(_Model):
    name: str = Field(min_length=1, max_length=80)
    explanation: str = Field(default="", max_length=600)
    colors: list[PaletteColor] = Field(min_length=1, max_length=20)

    def by_role(self) -> dict[str, str]:
        return {c.role: c.hex for c in self.colors}


def palette_problems(palette: Palette, identity: IdentitySettings) -> list[str]:
    s = identity.palette
    problems: list[str] = []
    n = len(palette.colors)
    if not s.colors.min <= n <= s.colors.max:
        problems.append(f"« {palette.name} » : {n} couleurs, entre {s.colors.min} et {s.colors.max} attendues")
    roles = [c.role for c in palette.colors]
    unknown = sorted({r for r in roles if r not in s.roles})
    if unknown:
        problems.append(f"« {palette.name} » : rôle inconnu {', '.join(unknown)} (parmi {', '.join(s.roles)})")
    doubles = sorted({r for r in roles if roles.count(r) > 1})
    if doubles:
        problems.append(f"« {palette.name} » : rôle en double {', '.join(doubles)}")
    missing = [r for r in s.required_roles if r not in roles]
    if missing:
        problems.append(f"« {palette.name} » : rôle obligatoire absent {', '.join(missing)}")
    return problems


def check_palette(palette: Palette, identity: IdentitySettings) -> None:
    problems = palette_problems(palette, identity)
    if problems:
        raise IdentityValidationError(" ; ".join(problems))


def load_json_object(text: str) -> dict[str, Any]:
    m = _FENCE.match(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IdentityValidationError(f"JSON illisible ({exc.msg}, ligne {exc.lineno})") from None
    if not isinstance(data, dict):
        raise IdentityValidationError("la racine doit être un objet JSON")
    return data


class _PaletteAnswer(BaseModel):
    palettes: list[Palette]


def parse_palettes(text: str, identity: IdentitySettings) -> list[Palette]:
    data = load_json_object(text)
    try:
        answer = _PaletteAnswer.model_validate(data)
    except ValidationError as exc:
        raise IdentityValidationError(format_errors(exc)) from None
    count = identity.palette.count
    problems: list[str] = []
    if not count.min <= len(answer.palettes) <= count.max:
        problems.append(f"{len(answer.palettes)} palettes, entre {count.min} et {count.max} attendues")
    for p in answer.palettes:
        problems += palette_problems(p, identity)
    if problems:
        raise IdentityValidationError(" ; ".join(problems))
    return answer.palettes


# --- logo ------------------------------------------------------------------------------------------------
class _RawConcept(BaseModel):
    """Concept tel que l'agent l'écrit : couleurs en rôles de la palette ou en `#rrggbb`."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", max_length=80)
    explanation: str = Field(default="", max_length=600)
    font: str
    style: str
    lines: list[LogoLine] = Field(min_length=1, max_length=4)
    subtitle: str | None = Field(default=None, max_length=120)
    slant: float = 0.0
    letter_spacing: float = 0.0
    colors: dict[str, str] = Field(default_factory=dict)


class _LogoAnswer(BaseModel):
    concepts: list[_RawConcept]


def normalize_title(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).casefold()


def default_color(style: LogoStyle, slot: str, palette: dict[str, str]) -> str | None:
    for role in style.colors.get(slot, []):  # type: ignore[call-overload]
        if role in palette:
            return palette[role]
    return None


def resolve_colors(raw: dict[str, str], style: LogoStyle, palette: dict[str, str]) -> tuple[LogoColors, list[str]]:
    """Couleurs d'un concept : rôle de la palette ou `#rrggbb` ; une couleur absente prend celle de l'effet."""
    problems: list[str] = []
    values: dict[str, str | None] = {}
    for slot in ("fill", "fill_end", "outline", "outer", "shadow", "subtitle"):
        given = raw.get(slot)
        if given:
            if re.fullmatch(HEX_COLOR, given.strip()):
                values[slot] = given.strip().lower()
                continue
            role = role_key(given)
            if role in palette:
                values[slot] = palette[role]
                continue
            problems.append(
                f"colors.{slot} : « {given} » n'est ni un rôle de la palette ({', '.join(palette)}) ni #rrggbb"
            )
        values[slot] = default_color(style, slot, palette)
    unknown = sorted(k for k in raw if k not in values)
    if unknown:
        problems.append(f"colors : clé inconnue {', '.join(unknown)}")
    if values["fill"] is None:
        values["fill"] = next(iter(palette.values()), "#000000")
    return LogoColors.model_validate(values), problems


@dataclass
class Concept:
    spec: LogoSpec
    notes: list[str] = field(default_factory=list)


def build_concept(
    presets: PresetRegistry, raw: _RawConcept, title: str, palette: dict[str, str]
) -> tuple[Concept | None, list[str]]:
    """Concept de l'agent → logo complet (couleurs résolues, contraste corrigé) ; ou ses problèmes."""
    label = f"« {raw.name or raw.font} »"
    style = presets.logo_styles.get(raw.style)
    if style is None:
        return None, [f"{label} : style inconnu « {raw.style} » ({', '.join(presets.logo_styles)})"]
    colors, problems = resolve_colors(raw.colors, style, palette)
    joined = normalize_title(" ".join(line.text for line in raw.lines))
    if joined != normalize_title(title):
        problems.append(
            f"{label} : les lignes « {' / '.join(line.text for line in raw.lines)} » ne redonnent pas le titre « {title} »"
        )
    spec = LogoSpec(
        name=raw.name,
        explanation=raw.explanation,
        font=raw.font,
        style=raw.style,
        lines=raw.lines,
        subtitle=raw.subtitle,
        slant=raw.slant,
        letter_spacing=raw.letter_spacing,
        colors=colors,
    )
    problems += [f"{label} : {p}" for p in spec_problems(presets, spec)]
    if problems:
        return None, problems
    minimum = presets.require_identity().logo.min_contrast
    fixed, note = fix_contrast(spec, style, list(dict.fromkeys(palette.values())), minimum)
    return Concept(fixed, [note] if note else []), []


def parse_concepts(text: str, presets: PresetRegistry, title: str, palette: dict[str, str]) -> list[Concept]:
    data = load_json_object(text)
    try:
        answer = _LogoAnswer.model_validate(data)
    except ValidationError as exc:
        raise IdentityValidationError(format_errors(exc)) from None
    count = presets.require_identity().logo.count
    problems: list[str] = []
    if not count.min <= len(answer.concepts) <= count.max:
        problems.append(f"{len(answer.concepts)} concepts, entre {count.min} et {count.max} attendus")
    concepts: list[Concept] = []
    for raw in answer.concepts:
        concept, issues = build_concept(presets, raw, title, palette)
        problems += issues
        if concept is not None:
            concepts.append(concept)
    if problems:
        raise IdentityValidationError(" ; ".join(problems))
    return concepts


def concept_contrast(presets: PresetRegistry, spec: LogoSpec) -> float | None:
    style = presets.logo_styles.get(spec.style)
    return None if style is None else logo_contrast(spec, style)


# --- contexte ----------------------------------------------------------------------------------------------
def _dominant_colors(files: FileStore, path: str, count: int) -> list[str]:
    """Couleurs dominantes d'une image (quantification sur une vignette), de la plus présente à la moins."""
    if count <= 0:
        return []
    try:
        with Image.open(files.absolute(path)) as img:
            thumb = img.convert("RGB")
            thumb.thumbnail((96, 96))
    except (OSError, ValueError):
        return []
    quant = thumb.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    pal = quant.getpalette() or []
    counts = sorted(quant.getcolors() or [], reverse=True)
    return [f"#{pal[i * 3]:02x}{pal[i * 3 + 1]:02x}{pal[i * 3 + 2]:02x}" for _, i in counts]


def style_reference(session: Session, files: FileStore, project_id: int, colors: int) -> dict[str, Any] | None:
    asset = session.scalars(
        select(SeriesAsset).where(
            SeriesAsset.project_id == project_id, SeriesAsset.kind == AssetKind.style, SeriesAsset.active.is_(True)
        )
    ).first()
    if asset is None:
        return None
    image = asset.reference_images[0] if asset.reference_images else None
    return {
        "name": asset.name,
        "description": asset.visual_description,
        "colors": _dominant_colors(files, image.path, colors) if image else [],
    }


@dataclass
class IdentityBrief:
    """Ce que les agents de l'identité visuelle savent de la série."""

    title: str
    style_packs: str
    style_guidelines: str
    characters: list[dict[str, str]]
    reference: dict[str, Any] | None
    bible: str

    @classmethod
    def build(
        cls, session: Session, presets: PresetRegistry, files: FileStore, project: Project, *, bible_max_tokens: int
    ) -> IdentityBrief:
        identity = presets.require_identity()
        brief = style_brief(presets, project)
        chars = session.scalars(select(Character).where(Character.project_id == project.id).order_by(Character.name))
        bible = render_bible(session, project.id, max_tokens=bible_max_tokens)
        return cls(
            title=project.title,
            style_packs=brief.packs,
            style_guidelines=brief.guidelines,
            characters=[{"name": c.name, "description": c.visual_description.strip()} for c in chars],
            reference=style_reference(session, files, project.id, identity.palette.reference_colors),
            bible=bible.text if bible else "",
        )

    def common_values(self) -> dict[str, str]:
        chars = "\n".join(f"- {c['name']} : {c['description'] or '(pas de description)'}" for c in self.characters)
        ref = "(aucune référence de style)"
        if self.reference:
            ref = f"{self.reference['name']} — {self.reference['description'] or '(sans description)'}"
            if self.reference["colors"]:
                ref += f"\nCouleurs dominantes de son image : {', '.join(self.reference['colors'])}"
        return {
            "series_title": self.title,
            "style_packs": self.style_packs,
            "style_guidelines": self.style_guidelines,
            "characters": chars or "(aucun personnage enregistré)",
            "style_reference": ref,
            "bible": self.bible or "(pas encore de bible pour cette série)",
        }


def _previous_text(previous: list[str]) -> str:
    return "\n".join(f"- {p}" for p in previous) if previous else "(aucune)"


def palette_messages(
    prompt: PromptPreset, identity: IdentitySettings, brief: IdentityBrief, previous: list[str]
) -> list[ChatMessage]:
    s = identity.palette
    ctx = {
        "task": "palette",
        "title": brief.title,
        "roles": list(s.roles),
        "required_roles": s.required_roles,
        "count": s.count.model_dump(),
        "colors": s.colors.model_dump(),
        "characters": brief.characters,
        "reference": brief.reference,
        "previous": previous,
    }
    values = {
        **brief.common_values(),
        "roles": ", ".join(f"« {k} » ({v})" for k, v in s.roles.items()),
        "required_roles": ", ".join(s.required_roles),
        "min_palettes": str(s.count.min),
        "max_palettes": str(s.count.max),
        "min_colors": str(s.colors.min),
        "max_colors": str(s.colors.max),
        "previous": _previous_text(previous),
        "context_json": json.dumps(ctx, ensure_ascii=False),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


def logo_messages(
    prompt: PromptPreset, presets: PresetRegistry, brief: IdentityBrief, palette: Palette, previous: list[str]
) -> list[ChatMessage]:
    logo = presets.require_identity().logo
    fonts = presets.require_fonts().fonts
    styles = presets.logo_styles
    roles = palette.by_role()
    ctx = {
        "task": "logo",
        "title": brief.title,
        "fonts": logo.fonts,
        "styles": list(styles),
        "roles": list(roles),
        "count": logo.count.model_dump(),
        "max_lines": logo.max_lines,
        "previous": previous,
    }

    def style_line(st: LogoStyle) -> str:
        return f"- {st.id} : {st.name} — {st.description} (couleurs : {', '.join(st.slots())})"

    values = {
        **brief.common_values(),
        "palette": "\n".join(f"- {c.role} : {c.hex}" for c in palette.colors),
        "roles": ", ".join(roles),
        "fonts": "\n".join(f"- {f} : {fonts[f].name}" for f in logo.fonts),
        "styles": "\n".join(style_line(st) for st in styles.values()),
        "min_concepts": str(logo.count.min),
        "max_concepts": str(logo.count.max),
        "max_lines": str(logo.max_lines),
        "slant_max": f"{logo.slant_max_deg:g}",
        "min_spacing": f"{logo.letter_spacing.min:g}",
        "max_spacing": f"{logo.letter_spacing.max:g}",
        "min_scale": f"{logo.word_scale.min:g}",
        "max_scale": f"{logo.word_scale.max:g}",
        "previous": _previous_text(previous),
        "context_json": json.dumps(ctx, ensure_ascii=False),
    }
    return [
        ChatMessage("system", _render(prompt.system, values, "system")),
        ChatMessage("user", _render(prompt.user, values, "user")),
    ]


# --- appel du LLM avec relances -----------------------------------------------------------------------------
@dataclass
class Run[T]:
    output: T
    attempts: int


def ask[T](
    llm: LLMProvider, prompt: PromptPreset, messages: list[ChatMessage], parse: Callable[[str], T], what: str
) -> Run[T]:
    """Réponse validée, ou `IdentityError` après `1 + max_retries` tentatives (erreur renvoyée à l'agent)."""
    total = 1 + prompt.max_retries
    last_error = ""
    for attempt in range(1, total + 1):
        try:
            result = llm.complete(messages, json_mode=True, temperature=prompt.temperature)
        except LLMError as exc:
            if not exc.retryable or attempt == total:
                raise IdentityError(f"le LLM n'a pas pu proposer de {what} : {exc}") from exc
            last_error = str(exc)
            continue
        try:
            return Run(parse(result.text), attempt)
        except IdentityValidationError as exc:
            last_error = str(exc)
            if attempt < total:
                retry = _render(prompt.retry, {"error": last_error}, "retry")
                messages = [*messages, ChatMessage("assistant", result.text[:20000]), ChatMessage("user", retry)]
    raise IdentityError(f"réponse invalide {total} fois de suite pour les {what} ({last_error})")


def propose_palettes(
    llm: LLMProvider, presets: PresetRegistry, brief: IdentityBrief, previous: list[str]
) -> Run[list[Palette]]:
    identity = presets.require_identity()
    prompt = presets.prompt(PALETTE_PROMPT)
    messages = palette_messages(prompt, identity, brief, previous)
    return ask(llm, prompt, messages, lambda text: parse_palettes(text, identity), "palettes")


def propose_logos(
    llm: LLMProvider, presets: PresetRegistry, brief: IdentityBrief, palette: Palette, previous: list[str]
) -> Run[list[Concept]]:
    prompt = presets.prompt(LOGO_PROMPT)
    messages = logo_messages(prompt, presets, brief, palette, previous)
    roles = palette.by_role()
    return ask(llm, prompt, messages, lambda text: parse_concepts(text, presets, brief.title, roles), "logos")
