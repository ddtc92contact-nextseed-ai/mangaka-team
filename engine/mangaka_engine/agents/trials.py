"""« Essayer » : chaque agent sur une petite entrée d'exemple, sans toucher aux séries.

Un essai reçoit les presets du formulaire (non enregistrés) et renvoie l'entrée et la sortie,
découpées en sections que l'UI affiche côte à côte :

    {"title": "…", "kind": "text" | "json" | "layout" | "bubbles", "text"/"data": …}

En mode mock, l'essai du scénariste passe par le LLM factice ; aucun essai n'appelle ComfyUI ni
les modèles du contrôle qualité (le contrôleur est essayé sur des détections et des scores types).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..presets import PresetError, PresetRegistry
from ..providers.llm import LLMProvider
from ..providers.qc import Box as DetBox
from ..providers.qc import Detections

Section = dict[str, Any]


class TrialError(Exception):
    """Essai impossible (message lisible)."""


@dataclass
class TrialContext:
    presets: PresetRegistry
    values: dict[str, Any]  # réglages effectifs du formulaire (clé → valeur)
    llm: Callable[[], tuple[LLMProvider | None, str | None]]


def text(title: str, value: str) -> Section:
    return {"title": title, "kind": "text", "text": value}


def data(title: str, value: Any) -> Section:
    return {"title": title, "kind": "json", "data": value}


# --- exemple commun ------------------------------------------------------------------------------
SERIES = {
    "title": "La Lame du vent (série d'essai)",
    "reading_direction": "rtl",
}
# Packs de style de la série d'essai (presets/style_*/) ; un pack absent est remplacé par le premier.
SERIES_STYLE = {"genre": "shonen", "rendering": "nb-trames", "tone": "lumineux", "options": {"trames": "legeres"}}


def _trial_project(presets: PresetRegistry) -> Any:
    from ..store.models import Project

    def pick(packs: dict[str, Any], wanted: str) -> str | None:
        return wanted if wanted in packs else next(iter(packs), None)

    genre = pick(presets.style_genres, SERIES_STYLE["genre"])  # type: ignore[arg-type]
    rendering = pick(presets.style_renderings, SERIES_STYLE["rendering"])  # type: ignore[arg-type]
    tone = pick(presets.style_tones, SERIES_STYLE["tone"])  # type: ignore[arg-type]
    allowed = presets.style_genres[genre].allowed_tones if genre else None
    if allowed is not None and tone not in allowed:
        tone = allowed[0]
    r = presets.style_renderings.get(rendering or "")
    options = SERIES_STYLE["options"] if r is not None and r.monochrome else {}
    return Project(
        title=SERIES["title"],
        legacy_style="",
        style_genre=genre,
        style_rendering=rendering,
        style_tone=tone,
        style_options=dict(options),  # type: ignore[arg-type]
    )


def trial_series(presets: PresetRegistry) -> dict[str, Any]:
    """Série d'essai telle que la reçoivent les LLM : packs de style et consignes compris."""
    from ..pipeline.style import style_brief

    brief = style_brief(presets, _trial_project(presets))
    return {**SERIES, "style": brief.packs, "style_guidelines": brief.guidelines}


def trial_style(presets: PresetRegistry) -> str:
    """`$style` de la série d'essai."""
    from ..pipeline.style import series_style

    return series_style(presets, _trial_project(presets))


CHARACTERS = [
    {"name": "Aiko", "description": "lycéenne, cheveux courts noirs, bandeau rouge, sabre de bois"},
    {"name": "Ren", "description": "rival au regard froid, long manteau gris, cicatrice à la joue"},
]
PREVIOUS = [
    {
        "number": 1,
        "title": "Le bandeau rouge",
        "summary": "Aiko intègre le club de kendo et découvre le sabre de sa mère.",
    },
    {"number": 2, "title": "Le nouveau", "summary": "Ren arrive au lycée et bat tout le club en une après-midi."},
    {"number": 3, "title": "La promesse", "summary": "Aiko jure de battre Ren avant la fin du trimestre."},
]
CHAPTER = {
    "number": 4,
    "title": "Le défi",
    "synopsis": (
        "Aiko retrouve Ren sur le toit du lycée. Il la provoque et lui lance un défi pour le coucher du soleil. "
        "Elle accepte, malgré la peur."
    ),
    "target_pages": 1,
}


# --- 1. scénario ---------------------------------------------------------------------------------
def trial_script(ctx: TrialContext) -> dict[str, Any]:
    from ..pipeline.script import ScriptContext, ScriptError, render_messages, run_script

    prompt = ctx.presets.prompt("script")
    previous = PREVIOUS[-prompt.max_previous_chapters :] if prompt.max_previous_chapters else []
    script_ctx = ScriptContext(
        series=trial_series(ctx.presets), characters=CHARACTERS, previous_chapters=previous, chapter=CHAPTER
    )
    try:
        messages = render_messages(prompt, script_ctx)
    except PresetError as exc:
        raise TrialError(str(exc)) from None
    inputs = [
        data(
            "Chapitre d'essai",
            {"série": SERIES["title"], "chapitre": f"{CHAPTER['number']} — {CHAPTER['title']}", "pages": 1},
        ),
        text("Consignes système", messages[0].content),
        text("Message envoyé", messages[1].content),
        data("Paramètres", {"température": prompt.temperature, "nouveaux essais": prompt.max_retries}),
    ]
    llm, error = ctx.llm()
    if llm is None:
        return {"input": inputs, "output": [], "error": f"LLM indisponible : {error or 'non configuré'}"}
    try:
        run = run_script(llm, prompt, script_ctx, lambda _p, _m: None)
    except ScriptError as exc:
        return {"input": inputs, "output": [], "error": str(exc)}
    out = run.output
    pages = [
        {
            "page": i + 1,
            "cases": [
                {
                    "description": p.description,
                    "plan": p.shot_type,
                    "importance": p.importance,
                    "personnages": p.characters,
                    "dialogues": [f"{d.speaker or '—'} ({d.kind}) : {d.text}" for d in p.dialogues],
                }
                for p in page.panels
            ],
        }
        for i, page in enumerate(out.pages)
    ]
    n_panels = sum(len(p.panels) for p in out.pages)
    return {
        "input": inputs,
        "output": [
            text(
                "Résultat",
                f"{len(out.pages)} page(s), {n_panels} case(s)"
                + (f", en {run.attempts} essais" if run.attempts > 1 else "")
                + f" — fournisseur : {getattr(llm, 'name', '?')}",
            ),
            text("Résumé du chapitre", out.summary),
            data("Découpage", pages),
        ],
    }


# --- 2. mise en page -----------------------------------------------------------------------------
PANELS = [(3, 160), (2, 60), (2, 0), (1, 240)]  # (importance, longueur des dialogues)


def _page_format(presets: PresetRegistry):  # type: ignore[no-untyped-def]
    fmt_id = presets.defaults.page_format if presets.defaults else next(iter(presets.page_formats), None)
    if fmt_id is None:
        raise TrialError("aucun format de page disponible")
    try:
        return presets.page_format(fmt_id)
    except PresetError as exc:
        raise TrialError(str(exc)) from None


def trial_layout(ctx: TrialContext) -> dict[str, Any]:
    from ..pipeline.layout import LayoutError, PanelSpec, choose_template, compute_layout

    fmt = _page_format(ctx.presets)
    specs = [PanelSpec(importance=imp, dialogue_chars=chars) for imp, chars in PANELS]
    try:
        template_id, tree = choose_template(list(ctx.presets.layout_templates.values()), [s.importance for s in specs])
        layout = compute_layout(
            fmt, ctx.presets.layout, tree, specs, direction="rtl", page_number=1, template_id=template_id
        )
    except LayoutError as exc:
        raise TrialError(str(exc)) from None
    tpl = ctx.presets.layout_templates.get(template_id)
    return {
        "input": [
            data(
                "Planche d'essai",
                {
                    "format": fmt.name,
                    "sens de lecture": "manga (droite à gauche)",
                    "cases": [
                        {"case": i + 1, "importance": imp, "dialogues (caractères)": chars}
                        for i, (imp, chars) in enumerate(PANELS)
                    ],
                },
            )
        ],
        "output": [
            text("Gabarit choisi", f"{tpl.name if tpl else template_id} ({template_id})"),
            {"title": "Planche", "kind": "layout", "data": {"page": layout["page"], "panels": layout["panels"]}},
            data(
                "Cases",
                [
                    {
                        "case": p["reading_order"],
                        "taille (px)": f"{p['width']} × {p['height']}",
                        "image générée (px)": f"{p['target']['width']} × {p['target']['height']}",
                        "zone de bulles": p["bubble_zone"],
                    }
                    for p in layout["panels"]
                ],
            ),
        ],
    }


# --- 3. prompt d'une case ------------------------------------------------------------------------
PANEL = {
    "description": "Aiko lève son sabre face à Ren sur le toit, le vent soulève son bandeau. « Je n'ai pas peur ! »",
    "shot_type": "contre-plongée",
    "setting": "toit d'un lycée au crépuscule, château d'eau, antennes, ville en contrebas",
    "staging": "Aiko au premier plan à gauche, sabre levé ; Ren à droite, en retrait, bras croisés",
    # Direction artistique appliquée à la case d'essai ($plan, $angle, $ambiance).
    "plan": "gros plan",
    "angle": "en contre-plongée",
    "ambiance": "contre-jour orangé, vent violent",
    "size": (1400, 900),
}


def trial_image_prompt(ctx: TrialContext) -> dict[str, Any]:
    from ..pipeline.layout import target_size
    from ..pipeline.prompt import PromptCharacter, ReferenceSlot, build_negative_prompt, build_prompt, frame_references

    presets = ctx.presets
    characters = [
        PromptCharacter("Aiko", CHARACTERS[0]["description"], ("anime girl", "red headband")),
        PromptCharacter("Ren", CHARACTERS[1]["description"], ("anime boy", "grey coat")),
    ]
    positive = build_prompt(
        description=PANEL["description"],  # type: ignore[arg-type]
        setting=PANEL["setting"],  # type: ignore[arg-type]
        staging=PANEL["staging"],  # type: ignore[arg-type]
        shot_type=PANEL["shot_type"],  # type: ignore[arg-type]
        plan=PANEL["plan"],  # type: ignore[arg-type]
        angle=PANEL["angle"],  # type: ignore[arg-type]
        ambiance=PANEL["ambiance"],  # type: ignore[arg-type]
        characters=characters,
        style=trial_style(presets),
        settings=presets.image_prompt,
    )
    wf_id = presets.defaults.workflow if presets.defaults else next(iter(presets.workflows), None)
    if wf_id is None:
        raise TrialError("aucun workflow ComfyUI disponible")
    try:
        wf = presets.workflow(wf_id)
    except PresetError as exc:
        raise TrialError(str(exc)) from None
    negative = build_negative_prompt(str(wf.preset.defaults.get("negative_prompt", "")), presets.image_prompt)
    w, h = PANEL["size"]  # type: ignore[misc]
    size = target_size(w, h, presets.layout)
    params = {k: v for k, v in wf.preset.defaults.items() if k in ("steps", "cfg")}
    written, written_info = _trial_written_prompt(ctx, characters)
    return {
        "input": [
            data(
                "Case d'essai",
                {
                    "description": PANEL["description"],
                    "plan": PANEL["shot_type"],
                    "lieu": PANEL["setting"],
                    "mise en scène": PANEL["staging"],
                    "personnages": [f"{c.name} : {c.visual_description}" for c in characters],
                    "style de la série": trial_style(presets),
                    "case (px)": f"{w} × {h}",
                },
            )
        ],
        "output": [
            text("Prompt rédigé par l'IA", written),
            *([data("Rédaction", written_info)] if written_info else []),
            text("Prompt par fragments", positive),
            text(
                "Avec images de référence (une par personnage)",
                frame_references(
                    positive, [ReferenceSlot("character", c.name) for c in characters], presets.image_prompt
                ),
            ),
            text("Prompt négatif", negative),
            data("Envoyé à ComfyUI", {"workflow": wf.preset.name, **params, **size}),
        ],
    }


def _trial_written_prompt(ctx: TrialContext, characters: list[Any]) -> tuple[str, dict[str, Any]]:
    """Prompt de la case d'essai rédigé par le LLM du formulaire (une référence par personnage), ou l'erreur
    qui ferait retomber une vraie case sur les fragments."""
    from ..pipeline.prompt import ReferenceSlot
    from ..pipeline.prompt_writer import PROMPT_ID, PromptBrief, PromptWriterError, write_prompt

    presets = ctx.presets
    prompt = presets.prompts.get(PROMPT_ID)
    if prompt is None:
        return f"(presets/prompts/{PROMPT_ID}.yaml absent : seul le prompt par fragments est disponible)", {}
    brief = PromptBrief.build(
        description=PANEL["description"],  # type: ignore[arg-type]
        setting=PANEL["setting"],  # type: ignore[arg-type]
        staging=PANEL["staging"],  # type: ignore[arg-type]
        shot_type=PANEL["shot_type"],  # type: ignore[arg-type]
        plan=PANEL["plan"],  # type: ignore[arg-type]
        angle=PANEL["angle"],  # type: ignore[arg-type]
        ambiance=PANEL["ambiance"],  # type: ignore[arg-type]
        characters=characters,
        absent=["Sensei Okada"],
        references=[ReferenceSlot("character", c.name) for c in characters],
        style=trial_style(presets),
        prompt=prompt,
    )
    llm, error = ctx.llm()
    if llm is None:
        return f"LLM indisponible ({error or 'non configuré'}) : une vraie case retomberait sur les fragments.", {}
    try:
        run = write_prompt(llm, prompt, brief)
    except (PromptWriterError, PresetError) as exc:
        return f"Rédaction en échec ({exc}) : une vraie case retomberait sur les fragments.", {}
    out = run.output
    info: dict[str, Any] = {
        "langue": out.language,
        "mots": len(out.prompt.split()),
        "longueur visée": f"{brief.min_words} à {brief.max_words} mots",
        "essais": run.attempts,
        "modèle": getattr(llm, "model", llm.name),
    }
    if out.notes:
        info["notes"] = out.notes
    return out.prompt, info


# --- 4. contrôle qualité -------------------------------------------------------------------------
QC_CASES = [
    {
        "nom": "Case réussie",
        "faces": [0.92, 0.86],
        "hands": [0.81],
        "text": [],
        "similarities": {"Aiko": 0.91, "Ren": 0.88},
        "vision": 88,
    },
    {
        "nom": "Case douteuse",
        "faces": [0.71],
        "hands": [0.42, 0.77],
        "text": [],
        "similarities": {"Aiko": 0.84},
        "vision": 64,
    },
    {
        "nom": "Case ratée",
        "faces": [0.88, 0.8],
        "hands": [],
        "text": [0.61],
        "similarities": {"Aiko": 0.62, "Ren": 0.79},
        "vision": 31,
    },
]


def _boxes(scores: list[float]) -> list[DetBox]:
    return [DetBox(10 + 60 * i, 10, 60 + 60 * i, 60, s) for i, s in enumerate(scores)]


def trial_qc(ctx: TrialContext) -> dict[str, Any]:
    from ..pipeline.qc import (
        VERDICT_LABEL,
        LayerResult,
        combine,
        evaluate_detections,
        evaluate_identity,
        filter_detections,
        vision_decision,
        vision_prompt,
    )

    try:
        cfg = ctx.presets.require_qc()
    except PresetError as exc:
        raise TrialError(str(exc)) from None
    results = []
    for case in QC_CASES:
        det = filter_detections(
            Detections(512, 512, _boxes(case["faces"]), _boxes(case["hands"]), _boxes(case["text"])),  # type: ignore[arg-type]
            cfg.detectors,
        )
        layers = {
            "detectors": evaluate_detections(det, expected_faces=2, shot_type="plan moyen", cfg=cfg.detectors),
            "identity": evaluate_identity(case["similarities"], without_references=[], cfg=cfg.identity),  # type: ignore[arg-type]
        }
        prelim = combine(layers, cfg.weights, cfg.verdict)
        run, why = vision_decision(prelim, cfg.vision, "auto")
        if run:
            layers["vision"] = LayerResult("done", score=int(case["vision"]))  # type: ignore[call-overload]
        else:
            layers["vision"] = LayerResult("skipped", message=why)
        result = combine(layers, cfg.weights, cfg.verdict)
        results.append(
            {
                "case": case["nom"],
                "verdict": VERDICT_LABEL[result.verdict] if result else "—",
                "score": result.score if result else None,
                "couches": {
                    name: (r.score if r.score is not None else f"sautée ({r.message})") for name, r in layers.items()
                },
                "raisons": result.reasons if result else [],
            }
        )
    prompt = vision_prompt(
        cfg.vision,
        description="Aiko lève son sabre face à Ren sur le toit",
        characters=["Aiko", "Ren"],
        shot="contre-plongée",
    )
    return {
        "input": [
            data(
                "Cases types (2 personnages attendus)",
                [
                    {
                        "case": c["nom"],
                        "visages (confiance)": c["faces"],
                        "mains (confiance)": c["hands"],
                        "texte parasite (confiance)": c["text"],
                        "ressemblance": c["similarities"],
                        "score de la vision (si consultée)": c["vision"],
                    }
                    for c in QC_CASES
                ],
            ),
            text("Consigne envoyée au modèle de vision", prompt),
        ],
        "output": [
            text(
                "Seuils",
                f"ok à partir de {cfg.verdict.ok_min}, rejet sous {cfg.verdict.reject_below} ; "
                f"poids détecteurs {cfg.weights.detectors:g}, ressemblance {cfg.weights.identity:g}, "
                f"vision {cfg.weights.vision:g}",
            ),
            data("Verdicts", results),
        ],
    }


# --- 5. lettrage ---------------------------------------------------------------------------------
BUBBLES = [
    ("speech", "Aiko", "On se retrouve enfin, Ren. Cette fois, je ne reculerai pas."),
    ("thought", "Aiko", "Mes mains tremblent…"),
    ("shout", "Ren", "EN GARDE !"),
    ("narration", "", "Le lendemain, sur le toit du lycée."),
    ("off", "Professeur", "Aiko ! Redescends tout de suite !"),
]
KIND_LABELS = {"speech": "Parole", "thought": "Pensée", "shout": "Cri", "narration": "Récitatif", "off": "Hors-champ"}


def trial_lettering(ctx: TrialContext) -> dict[str, Any]:
    from ..pipeline.fonts import FontBook
    from ..pipeline.lettering import Box, BubbleSpec, Letterer, LetteringError, PanelSpec

    presets = ctx.presets
    try:
        fonts = FontBook(presets)
    except PresetError as exc:
        raise TrialError(str(exc)) from None
    fmt = _page_format(presets)
    w, h = fmt.mm_to_px(170), fmt.mm_to_px(110)
    spec = PanelSpec(
        id=1,
        index=0,
        box=Box(0, 0, w, h),
        characters=["Aiko", "Ren"],
        bubbles=[BubbleSpec(id=i + 1, kind=k, text=t, speaker=s, order=i) for i, (k, s, t) in enumerate(BUBBLES)],
    )
    try:
        lettering = Letterer(fonts, presets.lettering, fmt.dpi).letter_page([spec], "rtl")
    except (LetteringError, PresetError) as exc:
        raise TrialError(str(exc)) from None
    bubbles = [b.to_json() for b in lettering.bubbles]
    names = {kind: fonts.name(fonts.style(kind)) for kind in KIND_LABELS}
    return {
        "input": [
            data(
                "Case d'essai",
                {
                    "taille": f"170 × 110 mm ({w} × {h} px à {fmt.dpi} DPI)",
                    "bulles": [f"{KIND_LABELS[k]} — {s or 'narrateur'} : {t}" for k, s, t in BUBBLES],
                },
            )
        ],
        "output": [
            {"title": "Case lettrée", "kind": "bubbles", "data": {"width": w, "height": h, "bubbles": bubbles}},
            data(
                "Bulles",
                [
                    {
                        "type": KIND_LABELS.get(b["kind"], b["kind"]),
                        "police": names.get(b["kind"], b["font"]["family"]),
                        "taille (pt)": b["font"]["size_pt"],
                        "lignes": [ln["text"] for ln in b["lines"]],
                        "texte trop long": b["overflow"],
                    }
                    for b in bubbles
                ],
            ),
            *([data("Avertissements", [w_.message for w_ in lettering.warnings])] if lettering.warnings else []),
        ],
    }


TRIALS: dict[str, Callable[[TrialContext], dict[str, Any]]] = {
    "script": trial_script,
    "layout": trial_layout,
    "image_prompt": trial_image_prompt,
    "qc": trial_qc,
    "lettering": trial_lettering,
}


def run_trial(name: str, ctx: TrialContext) -> dict[str, Any]:
    trial = TRIALS.get(name)
    if trial is None:
        raise TrialError(f"essai inconnu : « {name} »")
    result = trial(ctx)
    json.dumps(result)  # sérialisable (l'API le renvoie tel quel)
    return result
