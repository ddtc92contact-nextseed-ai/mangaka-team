#!/usr/bin/env python3
"""Relève dans les presets les gabarits de prompts réels et le traçage d'une case d'essai → assets/prompts-gabarits.js.

Usage, depuis la racine du dépôt (il faut le moteur et son venv) :

    engine/.venv/bin/python mangaka-tuto/extraire_prompts.py           # réécrit le fichier
    engine/.venv/bin/python mangaka-tuto/extraire_prompts.py --check   # code 1 si le fichier n'est plus à jour

Ce qui est relevé, sans appel LLM ni base : le texte de chaque gabarit de `presets/prompts/` (et sa ligne), les
variables qu'il utilise, les variables déclarées par les agents (`presets/agents/*.yaml`), les morceaux du prompt par
fragments (`presets/image_prompt.yaml`), la consigne de vision du QC (`presets/qc.yaml`), les modèles
(`presets/providers.yaml`), et le prompt de la case d'essai de l'appli (`agents/trials.py`) construit par le vrai
code (`pipeline/prompt.py`), découpé morceau par morceau avec la source de chaque morceau.
"""

from __future__ import annotations

import json
import re
import string
import sys
from pathlib import Path
from typing import Any

import yaml

TUTO = Path(__file__).resolve().parent
ROOT = TUTO.parent
PRESETS = ROOT / "presets"
OUT = TUTO / "assets" / "prompts-gabarits.js"
sys.path.insert(0, str(ROOT / "engine"))

from mangaka_engine.agents import trials  # noqa: E402
from mangaka_engine.pipeline import prompt as P  # noqa: E402
from mangaka_engine.pipeline import style as S  # noqa: E402
from mangaka_engine.pipeline.prompt_layout import LayoutSubject, cite_boxes, layout_boxes  # noqa: E402
from mangaka_engine.pipeline.prompt_writer import PromptBrief, render_messages  # noqa: E402
from mangaka_engine.presets.loader import PresetRegistry  # noqa: E402

VAR = re.compile(r"\$(?:(\w+)|\{(\w+)\})")
TEMPLATE_KEYS = ("system", "user", "retry")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def node_lines(path: Path) -> dict[str, int]:
    """Ligne (1 = première) de chaque clé du YAML, par chemin pointé (« vision.prompt », « parts.3 »)."""
    out: dict[str, int] = {}

    def walk(node: yaml.Node, prefix: str) -> None:
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                key = f"{prefix}.{k.value}" if prefix else str(k.value)
                out[key] = k.start_mark.line + 1
                walk(v, key)
        elif isinstance(node, yaml.SequenceNode):
            for i, v in enumerate(node.value):
                key = f"{prefix}.{i}"
                out[key] = v.start_mark.line + 1
                walk(v, key)

    root = yaml.compose(path.read_text(encoding="utf-8"))
    if root is not None:
        walk(root, "")
    return out


def used_vars(text: str) -> list[str]:
    return list(dict.fromkeys(a or b for a, b in VAR.findall(text.replace("$$", ""))))


def prompt_files() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in sorted((PRESETS / "prompts").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        lines = node_lines(path)
        parts = [
            {"key": k, "line": lines[k] + 1, "text": data[k], "used": used_vars(data[k])}
            for k in TEMPLATE_KEYS
            if isinstance(data.get(k), str)
        ]
        extra = {
            k: data[k]
            for k in ("language", "min_words", "max_words", "enabled", "variety", "max_previous_chapters")
            if k in data
        }
        out[data["id"]] = {
            "id": data["id"],
            "file": rel(path),
            "description": data.get("description", ""),
            "temperature": data.get("temperature"),
            "temperatureLine": lines.get("temperature"),
            "maxRetries": data.get("max_retries"),
            "maxRetriesLine": lines.get("max_retries"),
            "extra": extra,
            "parts": parts,
        }
    return out


def agents() -> list[dict[str, Any]]:
    out = []
    for path in sorted((PRESETS / "agents").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        lines = node_lines(path)
        settings = []
        for i, s in enumerate(data.get("settings") or []):
            if not s.get("variables"):
                continue
            settings.append(
                {
                    "key": s["key"],
                    "label": s.get("label", ""),
                    "source": s.get("source", ""),
                    "line": lines.get(f"settings.{i}"),
                    "variables": list(s["variables"]),
                }
            )
        out.append(
            {
                "id": data["id"],
                "name": data.get("name", ""),
                "icon": data.get("icon", ""),
                "file": rel(path),
                "providers": list(data.get("providers") or []),
                "llm": "llm" in (data.get("providers") or []),
                "knowledgeRole": data.get("knowledge_role"),
                "settings": settings,
            }
        )
    return out


def providers() -> dict[str, Any]:
    path = PRESETS / "providers.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    lines = node_lines(path)
    return {
        "file": rel(path),
        "defaultModel": data["deepseek"]["model"],
        "defaultModelLine": lines["deepseek.model"],
        "models": {m["id"]: bool(m.get("reasoning")) for m in data["deepseek"].get("models", [])},
        "visionModel": data["ollama"]["vision_model"],
        "visionModelLine": lines["ollama.vision_model"],
    }


def image_prompt_preset() -> dict[str, Any]:
    path = PRESETS / "image_prompt.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    lines = node_lines(path)
    return {
        "file": rel(path),
        "parts": [{"line": lines[f"parts.{i}"], "text": t, "used": used_vars(t)} for i, t in enumerate(data["parts"])],
        "styleMaxChars": data.get("style_max_chars"),
        "styleMaxCharsLine": lines.get("style_max_chars"),
        "lines": {
            k: lines[k]
            for k in (
                "parts",
                "character",
                "style_lead",
                "style_max_chars",
                "strip_quotes",
                "references",
                "references.character",
                "references.sorting",
                "references.after",
                "references.monochrome",
                "monochrome_forbidden_terms",
                "monochrome_writer_rule",
                "mood_conflicts",
                "camera_terms",
                "tight_shots",
                "mentions",
                "single_instance",
                "framing",
                "forbidden_text_terms",
                "negative_photo_terms",
                "forbidden_photo_terms",
            )
            if k in lines
        },
    }


def qc_vision() -> dict[str, Any]:
    path = PRESETS / "qc.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    lines = node_lines(path)
    text = data["vision"]["prompt"]
    return {"file": rel(path), "line": lines["vision.prompt"] + 1, "text": text, "used": used_vars(text)}


# --- traçage de la case d'essai -------------------------------------------------------------------------------------
# Source de chaque variable du prompt par fragments (couleur de la page).
VAR_SOURCE = {
    "style_lead": "style",
    "finition": "style",
    "style": "style",
    "plan": "da",
    "angle": "da",
    "ambiance": "da",
    "action": "da",
    "framing": "code",
    "description": "script",
    "setting": "script",
    "staging": "script",
    "shot": "script",
    "character_count": "code",
    "characters": "fiche",
    "decor": "fiche",
    "objects": "fiche",
    "bible": "bible",
    "savoir_faire": "savoir",
}
# Fiche de la bible et passage de savoir-faire factices (la case d'essai de l'appli n'en a pas) : marqués comme tels.
TRIAL_BIBLE = "Aiko: always wears her mother's red headband"
TRIAL_SAVOIR = "Low-angle panels exaggerate the foreshortening of the raised arm"


def segments_of(template: str, values: dict[str, str], tpl_src: dict[str, Any]) -> list[dict[str, Any]]:
    """Morceau du preset → segments (texte littéral du gabarit, valeur de chaque variable)."""
    out: list[dict[str, Any]] = []
    pos = 0
    for m in VAR.finditer(template):
        if m.start() > pos:
            out.append({"t": template[pos : m.start()], **tpl_src})
        var = m.group(1) or m.group(2)
        out.append({"t": values[var], "src": VAR_SOURCE[var], "var": var})
        pos = m.end()
    if pos < len(template):
        out.append({"t": template[pos:], **tpl_src})
    return out


def trace(presets: PresetRegistry) -> dict[str, Any]:
    ip = presets.image_prompt
    lines = node_lines(PRESETS / "image_prompt.yaml")
    panel = trials.PANEL
    project = trials._trial_project(presets)
    characters = [
        P.PromptCharacter("Aiko", trials.CHARACTERS[0]["description"], ("anime girl", "red headband")),
        P.PromptCharacter("Ren", trials.CHARACTERS[1]["description"], ("anime boy", "grey coat")),
    ]
    style = S.series_style(presets, project)
    style_lead = S.series_style_lead(presets, project)
    finition = S.series_finition(presets, project)
    kwargs = dict(
        description=panel["description"],
        setting=panel["setting"],
        staging=panel["staging"],
        shot_type=panel["shot_type"],
        plan=panel["plan"],
        angle=panel["angle"],
        ambiance=panel["ambiance"],
        action=panel["action"],
        characters=characters,
        style=style,
        style_lead=style_lead,
        finition=finition,
        bible=TRIAL_BIBLE,
        savoir_faire=TRIAL_SAVOIR,
        settings=ip,
    )
    stored = P.build_prompt(**kwargs)

    # Les mêmes valeurs que build_prompt (pipeline/prompt.py), recalculées pour les rendre visibles une à une.
    def q(text: str) -> str:
        return P.strip_quoted(text) if ip.strip_quotes else text

    described = [P.describe_character(c, ip) for c in characters]
    shot = P.camera_term(panel["shot_type"], ip)
    chosen = P.camera_term(panel["plan"], ip) or shot
    values = {
        "shot": shot[:1].upper() + shot[1:],
        "plan": chosen[:1].upper() + chosen[1:],
        "angle": P.camera_term(panel["angle"], ip),
        "ambiance": P._clean(q(panel["ambiance"])),
        "action": P._clean(q(panel["action"])),
        "description": P._clean(q(panel["description"])),
        "framing": "",
        "setting": P._clean(q(panel["setting"])),
        "staging": P._clean(q(panel["staging"])),
        "character_count": P.character_count(len(described)),
        "characters": ip.character_separator.join(described),
        "decor": "",
        "objects": "",
        "style": P._clean(style),
        "style_lead": P._clean(style_lead),
        "finition": P._clean(finition),
        "savoir_faire": P._clean(q(TRIAL_SAVOIR)),
        "bible": P._clean(q(TRIAL_BIBLE)),
    }
    who = [c.name for c in characters]
    for key in ("action", "ambiance", "description", "setting", "staging", "characters", "decor", "objects", "bible"):
        values[key] = P.cap_mentions(values[key], who, ip.mentions.max_per_field, ip.mentions.replacement)

    segs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, part in enumerate(ip.parts):
        ids = string.Template(part).get_identifiers()
        empty = [v for v in ids if not values[v]]
        src = {"src": "preset", "file": "presets/image_prompt.yaml", "line": lines[f"parts.{i}"]}
        if empty:
            skipped.append({"part": part, "line": lines[f"parts.{i}"], "empty": empty})
            continue
        if segs:
            segs.append({"t": " ", "src": "sep"})
        segs.extend(segments_of(part, values, src))
    joined = "".join(s["t"] for s in segs)
    if joined != stored:
        raise SystemExit(f"traçage ≠ build_prompt :\n{joined}\n{stored}")

    # Envoi à ComfyUI (generation.py) : rôles des images, tri, consigne « identité seulement », anti-doublon, tonalité.
    rendering = S.series_rendering(presets, project)
    monochrome = bool(rendering and rendering.monochrome)
    slots = [P.ReferenceSlot("character", c.name) for c in characters]
    refs = ip.references.for_palette(monochrome)
    pal = "references.monochrome" if monochrome else "references"
    ref_src = {
        "src": "preset",
        "file": "presets/image_prompt.yaml",
        "line": lines.get(f"{pal}.character", lines["references"]),
    }
    before = [
        {"t": P.reference_line(refs, s, n) + ("" if n == len(slots) else refs.separator), **ref_src}
        for n, s in enumerate(slots, 1)
    ]
    sorting = P.sorting_lines(slots, ip, monochrome=monochrome)
    sort_src = {"src": "preset", "file": "presets/image_prompt.yaml", "line": lines["references.sorting"]}
    after_src = {
        "src": "preset",
        "file": "presets/image_prompt.yaml",
        "line": lines.get(f"{pal}.after", lines["references.after"]),
    }
    after = [{"t": " ", "src": "sep"}, {"t": refs.separator.join(sorting), **sort_src}]
    after += [
        {"t": " " + string.Template(t).substitute(images="", count=str(len(slots)), sorting="").strip(), **after_src}
        for t in refs.after[1:]
    ]
    single = {
        "t": " " + ip.single_instance.strip().rstrip(".") + ".",
        "src": "preset",
        "file": "presets/image_prompt.yaml",
        "line": lines["single_instance"],
    }
    tone = (
        {
            "t": " " + rendering.tonality.strip().rstrip(".") + ".",
            "src": "style",
            "var": "tonality",
            "file": f"presets/style_renderings/{project.style_rendering}.yaml",
        }
        if rendering and rendering.tonality
        else None
    )
    body = [*segs]
    if body and not body[-1]["t"].rstrip().endswith((".", "!", "?", "…")):
        body.append({"t": ".", "src": "code"})
    sent_segs = [*before, {"t": " ", "src": "sep"}, *body, *after, single, *([tone] if tone else [])]
    framed = P.frame_references(stored, slots, ip, monochrome=monochrome)
    framed = P.with_single_instance(framed, ip.single_instance)
    framed = P.append_instruction(framed, rendering.tonality if rendering else "")
    if "".join(s["t"] for s in sent_segs) != framed:
        raise SystemExit(f"traçage de l'envoi ≠ frame_references :\n{''.join(s['t'] for s in sent_segs)}\n{framed}")
    # Mots retirés au moment de l'envoi (série en noir et blanc, ambiance contre ton de la série) : barrés.
    removed_terms = list(P.mood_dropped_terms(panel["ambiance"], ip))
    if monochrome:
        removed_terms += list(ip.monochrome_forbidden_terms)
    keep = who
    struck: list[dict[str, Any]] = []
    for s in sent_segs:
        found = [
            t
            for t in P.found_terms(s["t"], removed_terms)
            if not any(set(t.casefold().split()) <= set(n.casefold().split()) for n in keep)
        ]
        if not found:
            struck.append(s)
            continue
        pattern = re.compile(
            "|".join(P.term_pattern(t).pattern for t in sorted(found, key=len, reverse=True)), re.IGNORECASE
        )
        pos = 0
        for m in pattern.finditer(s["t"]):
            if m.start() > pos:
                struck.append({**s, "t": s["t"][pos : m.start()]})
            struck.append({**s, "t": m.group(0), "removed": True})
            pos = m.end()
        if pos < len(s["t"]):
            struck.append({**s, "t": s["t"][pos:]})
    final = P.remove_terms(
        P.remove_terms(framed, P.mood_dropped_terms(panel["ambiance"], ip)),
        ip.monochrome_forbidden_terms if monochrome else [],
        keep=keep,
    )

    # Prompt négatif (workflow avec références par défaut + termes ajoutés par le code et le preset).
    wf_id = presets.defaults.workflow_with_references
    wf = presets.workflow(wf_id)
    base = str(wf.preset.defaults.get("negative_prompt", ""))
    negative = P.build_negative_prompt(base, ip, plan=panel["plan"], monochrome=monochrome)
    if rendering is not None:
        negative = P.merge_negative(negative, rendering.tonality_negative)
    base_terms = {t.strip().casefold() for t in base.split(",")}
    origin = [
        (ip.forbidden_text_terms, "forbidden_text_terms"),
        (ip.negative_photo_terms, "negative_photo_terms"),
        (ip.tight_shots.negative, "tight_shots"),
        (ip.monochrome_negative_terms, "monochrome_negative_terms"),
    ]
    neg_terms = []
    for term in [t.strip() for t in negative.split(",") if t.strip()]:
        if term.casefold() in base_terms:
            neg_terms.append({"t": term, "src": "workflow", "file": f"presets/workflows/{wf_id}.yaml"})
            continue
        key = next((k for terms, k in origin if term.casefold() in {x.casefold() for x in terms}), None)
        if key:
            neg_terms.append({"t": term, "src": "preset", "file": "presets/image_prompt.yaml", "line": lines.get(key)})
        else:
            neg_terms.append(
                {"t": term, "src": "style", "file": f"presets/style_renderings/{project.style_rendering}.yaml"}
            )

    # FLUX 3 Klein, grille de composition : boîtes et <obj_N> (prompt_layout.py).
    boxes = layout_boxes([LayoutSubject(c.name, tuple(c.prompt_keywords)) for c in characters], panel["staging"])
    flux = cite_boxes(final, boxes)

    # Rédacteur de prompt : le message utilisateur réellement rendu pour la même case.
    brief = PromptBrief.build(
        description=panel["description"],
        setting=panel["setting"],
        staging=panel["staging"],
        shot_type=panel["shot_type"],
        plan=panel["plan"],
        angle=panel["angle"],
        ambiance=panel["ambiance"],
        action=panel["action"],
        characters=characters,
        references=slots,
        style=style,
        style_lead=style_lead,
        finition=finition,
        bible=TRIAL_BIBLE,
        savoir_faire=TRIAL_SAVOIR,
        prompt=presets.prompts.get("redacteur-image"),
        settings=ip,
        monochrome=monochrome,
    )
    messages = render_messages(presets.prompt("redacteur-image"), brief)
    user = messages[1].content.split("<contexte>")[0].rstrip()

    return {
        "series": {
            "title": trials.SERIES["title"],
            "genre": project.style_genre,
            "rendering": project.style_rendering,
            "tone": project.style_tone,
            "monochrome": monochrome,
        },
        "panel": {k: v for k, v in panel.items() if k != "size"},
        "characters": [
            {"name": c.name, "details": c.visual_description, "keywords": list(c.prompt_keywords)} for c in characters
        ],
        "factice": {"bible": TRIAL_BIBLE, "savoir_faire": TRIAL_SAVOIR},
        "stored": stored,
        "segments": segs,
        "skipped": skipped,
        "sentSegments": struck,
        "sent": final,
        "negative": neg_terms,
        "negativeWorkflow": wf_id,
        "flux": {"prompt": flux, "boxes": [b.as_dict() for b in boxes]},
        "writerUser": user,
        "style": {"value": style, "length": len(style), "cap": ip.style_max_chars, "cut": style_cut(presets, project)},
    }


def style_cut(presets: PresetRegistry, project: Any) -> list[str]:
    """Mots-clés des packs de la série que le plafond `style_max_chars` écarte de `$style` (style.py)."""
    earlier: list[str] = []
    for _, group in S.style_groups(presets, project):
        for word in group:
            if not S._redundant(word, earlier):
                earlier.append(word)
    kept = set(S.style_keywords(presets, project))
    return [w for w in earlier if w not in kept]


def style_cuts(presets: PresetRegistry) -> dict[str, Any]:
    """Toutes les séries possibles sans réglage fin (genre × rendu × ton permis) : combien perdent des mots-clés."""
    from mangaka_engine.store.models import Project

    combos = []
    for genre_id, genre in sorted(presets.style_genres.items()):
        tones = genre.allowed_tones or sorted(presets.style_tones)
        for rendering_id in sorted(presets.style_renderings):
            for tone_id in tones:
                project = Project(
                    title="",
                    legacy_style="",
                    style_genre=genre_id,
                    style_rendering=rendering_id,
                    style_tone=tone_id,
                    style_options={},
                )
                cut = style_cut(presets, project)
                combos.append(
                    {
                        "genre": genre_id,
                        "rendering": rendering_id,
                        "tone": tone_id,
                        "cut": cut,
                        "length": len(S.series_style(presets, project)),
                    }
                )
    hit = [c for c in combos if c["cut"]]
    worst = max(combos, key=lambda c: len(c["cut"]))
    return {"total": len(combos), "truncated": len(hit), "worst": worst, "maxCut": max(len(c["cut"]) for c in combos)}


def build() -> str:
    presets = PresetRegistry.load(PRESETS)
    if presets.issues:
        raise SystemExit(f"presets invalides : {presets.issues[:3]}")
    data = {
        "providers": providers(),
        "agents": agents(),
        "prompts": prompt_files(),
        "imagePrompt": image_prompt_preset(),
        "qcVision": qc_vision(),
        "trace": trace(presets),
        "styleCuts": style_cuts(presets),
    }
    body = json.dumps(data, ensure_ascii=False, indent=1)
    return (
        "// Généré par mangaka-tuto/extraire_prompts.py depuis presets/ et le moteur — ne pas modifier à la main.\n"
        f"window.TUTO_GABARITS = {body};\n"
    )


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{rel(OUT)} n'est plus à jour : relance engine/.venv/bin/python mangaka-tuto/extraire_prompts.py")
            return 1
        print(f"{rel(OUT)} à jour")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"{rel(OUT)} écrit ({len(text) // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
