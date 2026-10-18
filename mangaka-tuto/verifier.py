#!/usr/bin/env python3
"""Vérifie que le tutoriel (assets/data.js) colle encore au dépôt.

Usage, depuis la racine du dépôt : python3 mangaka-tuto/verifier.py
Il faut PyYAML (présent dans le venv du moteur : engine/.venv/bin/python) et Node (pour lire data.js).

Contrôles : modèles (providers.yaml), flux cités (presets/workflows), défauts (defaults.yaml), agents et leurs
variables de prompt (presets/agents), étapes de la file ComfyUI (main.py), garde d'étapes (stage_gate.py),
fichiers source cités. Code de sortie 1 s'il y a un écart.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

TUTO = Path(__file__).resolve().parent
ROOT = TUTO.parent
ENGINE = ROOT / "engine" / "mangaka_engine"
PRESETS = ROOT / "presets"

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load_data(name: str = "data.js", var: str = "TUTO") -> dict:
    script = (
        "const fs=require('fs');global.window={};"
        f"eval(fs.readFileSync({json.dumps(str(TUTO / 'assets' / name))},'utf8'));"
        f"process.stdout.write(JSON.stringify(window.{var}));"
    )
    out = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def yml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def check_providers(d: dict) -> None:
    prov = yml(PRESETS / "providers.yaml")
    p = d["providers"]
    if p["defaultModel"] != prov["deepseek"]["model"]:
        fail(f"modèle par défaut : tuto {p['defaultModel']!r} ≠ providers.yaml {prov['deepseek']['model']!r}")
    known = {m["id"]: bool(m.get("reasoning")) for m in prov["deepseek"].get("models", [])}
    tuto = {k: bool(v.get("reasoning")) for k, v in p["models"].items()}
    if known != tuto:
        fail(f"modèles DeepSeek : tuto {tuto} ≠ providers.yaml {known}")
    if p["visionModel"] != prov["ollama"]["vision_model"]:
        fail(f"vision : tuto {p['visionModel']!r} ≠ providers.yaml {prov['ollama']['vision_model']!r}")
    if p["embeddingModel"] != prov["ollama"].get("embedding_model"):
        fail("modèle d'embeddings différent de providers.yaml")


def check_workflows(d: dict) -> None:
    for wid, w in d["workflows"].items():
        path = PRESETS / "workflows" / f"{wid}.yaml"
        if not path.exists():
            fail(f"flux absent : {path.relative_to(ROOT)}")
            continue
        y = yml(path)
        tier = (y.get("tier") or {}).get("name")
        for key, real in (("name", y.get("name")), ("engine", y.get("engine")), ("tier", tier)):
            if w[key] != real:
                fail(f"flux {wid} : {key} tuto {w[key]!r} ≠ preset {real!r}")
    used = {wid for s in d["steps"] for w in s["who"] for wid in w.get("workflows", [])}
    for wid in used - set(d["workflows"]):
        fail(f"flux cité par une étape mais absent de TUTO.workflows : {wid}")
    for engine in {w["engine"] for w in d["workflows"].values()} - set(d["engines"]):
        fail(f"moteur sans libellé : {engine}")


def check_defaults(d: dict) -> None:
    real = yml(PRESETS / "defaults.yaml")
    for key, value in d["defaults"].items():
        if real.get(key) != value:
            fail(f"defaults.yaml › {key} : tuto {value!r} ≠ preset {real.get(key)!r}")
    if d["defaults"]["upscaler"] and not (PRESETS / "upscalers" / f"{d['defaults']['upscaler']}.yaml").exists():
        fail("agrandisseur par défaut introuvable dans presets/upscalers/")


def check_agents(d: dict) -> None:
    files = {yml(p)["id"]: yml(p) for p in sorted((PRESETS / "agents").glob("*.yaml"))}
    tuto = {a["id"]: a for a in d["agents"]}
    if set(files) != set(tuto):
        fail(f"agents : tuto {sorted(tuto)} ≠ presets/agents {sorted(files)}")
    for aid, real in files.items():
        a = tuto.get(aid)
        if a is None:
            continue
        for key, rkey in (("name", "name"), ("icon", "icon"), ("step", "step"), ("stepLabel", "step_label")):
            if a[key] != real.get(rkey):
                fail(f"agent {aid} : {key} tuto {a[key]!r} ≠ preset {real.get(rkey)!r}")
        if " ".join(a["role"].split()) != " ".join(str(real.get("role", "")).split()):
            fail(f"agent {aid} : rôle différent du preset")
        if a["jobSteps"] != list(real.get("job_steps") or []):
            fail(f"agent {aid} : job_steps tuto {a['jobSteps']} ≠ preset {real.get('job_steps')}")
        if a["llm"] != ("llm" in (real.get("providers") or [])):
            fail(f"agent {aid} : présence d'un LLM différente du preset")
        # Variables : chaque prompt du tuto = variables d'un réglage du preset dont la source commence pareil.
        settings = [s for s in real.get("settings", []) if s.get("variables") and s.get("key") != "retry"]
        for p in a.get("prompts", []):
            match = [s for s in settings if s.get("source", "").startswith(p["file"])]
            if not match:
                fail(f"agent {aid} : aucun réglage du preset ne pointe vers {p['file']}")
            elif all(list(s["variables"]) != p["variables"] for s in match):
                fail(f"agent {aid} : variables de {p['file']} différentes du preset")
    for s in d["steps"]:
        for w in s["who"]:
            if w.get("agent") and w["agent"] not in files:
                fail(f"étape {s['id']} : agent inconnu {w['agent']}")


def check_queue(d: dict) -> None:
    main = (ENGINE / "main.py").read_text(encoding="utf-8")
    consts = dict(re.findall(r"from \.pipeline\.(\w+) import STEP as (\w+)", main))
    steps = set()
    for module, alias in consts.items():
        if re.search(rf"\b{alias}\b", main.split("def build_context", 1)[1]):
            src = (ENGINE / "pipeline" / f"{module}.py").read_text(encoding="utf-8")
            m = re.search(r'^STEP = "(\w+)"', src, re.M)
            alias_of = re.search(r"^from \.(\w+) import (\w+) as STEP$", src, re.M)
            if m:
                steps.add(m.group(1))
            elif alias_of:  # qc.py : `from .generation import QC_STEP as STEP`
                other = (ENGINE / "pipeline" / f"{alias_of.group(1)}.py").read_text(encoding="utf-8")
                m = re.search(rf'^{alias_of.group(2)} = "(\w+)"', other, re.M)
                if m:
                    steps.add(m.group(1))
            else:
                fail(f"STEP introuvable dans pipeline/{module}.py")
    if "TRIAL_STEP" in main:
        m = re.search(r'^STEP = "(\w+)"', (ENGINE / "pipeline" / "comfy_trial.py").read_text(encoding="utf-8"), re.M)
        steps.add(m.group(1))
    tuto = {q["step"] for q in d["queueSteps"]}
    if steps != tuto:
        fail(f"file ComfyUI : tuto {sorted(tuto)} ≠ main.py {sorted(steps)}")
    for p in d["poolSteps"]:
        if not any(p["step"] in (ROOT / f).read_text(encoding="utf-8") for f in p["src"]):
            fail(f"pool : étape {p['step']!r} introuvable dans {p['src']}")


def check_gate(d: dict) -> None:
    src = (ENGINE / "pipeline" / "stage_gate.py").read_text(encoding="utf-8")
    stages = re.findall(r'StageDef\(\s*"(\w+)",\s*"([^"]+)"', src)
    if [(s["key"], s["label"]) for s in d["gate"]["stages"]] != stages:
        fail(f"garde d'étapes : étapes différentes de stage_gate.py {stages}")
    actions = [
        (k, label, re.findall(r'"(\w+)"', tup))
        for k, label, tup in re.findall(r'ActionDef\("(\w+)", "([^"]+)", \(([^)]*)\)\)', src)
    ]
    if [(a["key"], a["label"], a["stages"]) for a in d["gate"]["actions"]] != actions:
        fail(f"garde d'étapes : actions différentes de stage_gate.py {actions}")


def check_sources(d: dict) -> None:
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "src":
                    yield from v
                else:
                    yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    cited = set(walk(d))
    for page in TUTO.glob("*.html"):
        cited |= set(re.findall(r'class="src"[^>]*>([^<(]+)', page.read_text(encoding="utf-8")))
    for path in sorted(cited):
        clean = path.split(" (")[0].split("#")[0].strip()
        if not (ROOT / clean).exists():
            fail(f"fichier source cité introuvable : {clean}")
    for s in d["steps"]:
        if not s["src"]:
            fail(f"étape {s['id']} sans fichier source")
    print(f"{len(cited)} fichiers source cités vérifiés")


# --- Chaîne des prompts (prompts.html) ------------------------------------------------------------------------------
# Points où le code assemble un prompt image : chacun doit être cité par une fiche (ligne de sa définition comprise).
IMAGE_PROMPT_POINTS = [
    ("pipeline/prompt.py", "build_prompt"),
    ("pipeline/prompt.py", "build_negative_prompt"),
    ("pipeline/prompt.py", "frame_references"),
    ("pipeline/prompt.py", "with_single_instance"),
    ("pipeline/prompt.py", "append_instruction"),
    ("pipeline/prompt_writer.py", "write_prompt"),
    ("pipeline/prompt_writer.py", "finish_paragraph"),
    ("pipeline/prompt_dialog.py", "propose"),
    ("pipeline/generation.py", "build_panel_prompt"),
    ("pipeline/generation.py", "sent_prompt"),
    ("pipeline/generation.py", "panel_brief"),
    ("pipeline/covers.py", "finish_cover_prompt"),
    ("pipeline/reference_sheets.py", "sheet_prompt"),
    ("pipeline/style_board.py", "board_prompt"),
    ("pipeline/repair.py", "repair_prompt"),
    ("pipeline/camera.py", "angle_prompt"),
]
CITE = re.compile(r"^(?P<path>[^:]+?)(?::(?P<a>\d+)(?:-(?P<b>\d+))?)?$")


def load_globals(*names: str) -> dict:
    files = [TUTO / "assets" / f for f in ("prompts-gabarits.js", "prompts-data.js")]
    script = "const fs=require('fs');global.window={};" + "".join(
        f"eval(fs.readFileSync({json.dumps(str(f))},'utf8'));" for f in files
    )
    script += "process.stdout.write(JSON.stringify({" + ",".join(f"{n}:window.{n}" for n in names) + "}));"
    out = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def cited(src) -> list[str]:
    return [src] if isinstance(src, str) else list(src or [])


def check_cite(ref: str, where: str) -> None:
    m = CITE.match(ref.strip())
    path = ROOT / m.group("path") if m else None
    if path is None or not path.exists():
        fail(f"{where} : fichier cité introuvable {ref!r}")
        return
    last = int(m.group("b") or m.group("a") or 0)
    if last and (not path.is_file() or last > len(path.read_text(encoding="utf-8").splitlines())):
        fail(f"{where} : ligne au-delà de la fin du fichier {ref!r}")


def check_prompts(d: dict) -> None:
    """prompts.html : gabarits relevés à jour, tous les agents, gabarits, variables et prompts image couverts."""
    python = ROOT / "engine" / ".venv" / "bin" / "python"
    run = subprocess.run(
        [str(python if python.exists() else sys.executable), str(TUTO / "extraire_prompts.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if run.returncode != 0:
        fail(f"prompts-gabarits.js : {(run.stdout + run.stderr).strip().splitlines()[-1]}")
    g = load_globals("TUTO_GABARITS", "TUTO_PROMPTS")
    gab, data = g["TUTO_GABARITS"], g["TUTO_PROMPTS"]
    nodes = {n["id"]: n for n in data["nodes"]}
    fiches = {f["id"]: f for f in data["fiches"]}
    findings = {f["id"]: f for f in data["findings"]}
    common = data["commonVars"]

    # Agents : chacun a un nœud ou une fiche, ou figure parmi les agents sans prompt.
    agents = {yml(p)["id"]: yml(p) for p in sorted((PRESETS / "agents").glob("*.yaml"))}
    shown = {n.get("agent") for n in nodes.values()} | {f.get("agent") for f in fiches.values()}
    shown |= {a["id"] for a in data["agentsWithoutPrompt"]}
    for aid in sorted(set(agents) - shown):
        fail(f"prompts.html : agent {aid} absent du graphe et des fiches")
    for aid in sorted(shown - set(agents) - {None}):
        fail(f"prompts.html : agent inconnu {aid}")

    # Gabarits : une fiche par fichier de presets/prompts ; chaque variable utilisée ou déclarée a sa provenance.
    by_gabarit = {f["gabarit"]: f for f in fiches.values() if f.get("gabarit")}
    for pid in sorted(set(gab["prompts"]) - set(by_gabarit)):
        fail(f"prompts.html : aucune fiche pour presets/prompts/{pid}.yaml")
    dead: list[str] = []
    for pid, fiche in by_gabarit.items():
        if pid not in gab["prompts"]:
            fail(f"fiche {fiche['id']} : gabarit inconnu {pid}")
            continue
        used = {v for part in gab["prompts"][pid]["parts"] for v in part["used"]}
        declared = set()
        for a in gab["agents"]:
            for s in a["settings"]:
                if s["source"].startswith(f"prompts/{pid}.yaml#"):
                    declared |= set(s["variables"])
        for v in sorted(used | declared):
            if v not in fiche["vars"] and v not in common:
                fail(f"fiche {fiche['id']} : provenance de ${v} non documentée")
        for v in sorted(set(fiche["vars"]) - used - declared):
            fail(f"fiche {fiche['id']} : ${v} documentée mais ni utilisée ni déclarée (gabarit changé ?)")
        dead += [f"{pid}:${v}" for v in sorted(declared - used)]
        if fiche.get("agent") and fiche["agent"] not in agents:
            fail(f"fiche {fiche['id']} : agent inconnu {fiche['agent']}")
    # Gabarits d'un agent qui ne sont pas des presets/prompts (morceaux d'image_prompt.yaml, vision du QC).
    special = {
        "image_parts": {v for p in gab["imagePrompt"]["parts"] for v in p["used"]},
        "qc": set(gab["qcVision"]["used"]),
    }
    for a in gab["agents"]:
        for s in a["settings"]:
            if s["source"] == "image_prompt.yaml#parts":
                special["image_parts"] |= set(s["variables"])
            if s["source"] == "qc.yaml#vision.prompt":
                special["qc"] |= set(s["variables"])
            m = re.match(r"prompts/([\w-]+)\.yaml#", s["source"])
            if m and m.group(1) not in by_gabarit:
                fail(f"agent {a['id']} : réglage {s['key']} vers {s['source']} sans fiche")
    for kind, wanted in special.items():
        fiche = next((f for f in fiches.values() if f.get("special") == kind), None)
        if fiche is None:
            fail(f"prompts.html : aucune fiche « {kind} »")
            continue
        for v in sorted(wanted - set(fiche["vars"])):
            fail(f"fiche {fiche['id']} : provenance de ${v} non documentée")
        for v in sorted(set(fiche["vars"]) - wanted):
            fail(f"fiche {fiche['id']} : ${v} documentée mais absente du preset")

    # Traçage : chaque variable surlignée a son auteur.
    for seg in [*gab["trace"]["segments"], *gab["trace"]["sentSegments"]]:
        if seg.get("var") and seg["var"] not in data["traceVars"]:
            fail(f"traçage : ${seg['var']} sans auteur dans traceVars")
        if seg["src"] not in {s["id"] for s in data["sources"]}:
            fail(f"traçage : source inconnue {seg['src']}")

    # Liens internes : nœuds, fiches, constats, étapes de la carte.
    for e in data["edges"]:
        for end in (e["from"], e["to"]):
            if end not in nodes:
                fail(f"graphe : flèche vers un nœud inconnu {end}")
    for n in nodes.values():
        for fid in n.get("fiches", []):
            if fid not in fiches:
                fail(f"nœud {n['id']} : fiche inconnue {fid}")
    for f in fiches.values():
        if f.get("node") and f["node"] not in nodes:
            fail(f"fiche {f['id']} : nœud inconnu {f['node']}")
        for fid in f.get("findings", []):
            if fid not in findings:
                fail(f"fiche {f['id']} : constat inconnu {fid}")
        if not f.get("calledBy"):
            fail(f"fiche {f['id']} sans fichier source")
    grouped = [fid for grp in data["ficheGroups"] for fid in grp["fiches"]]
    if sorted(grouped) != sorted(fiches):
        fail("prompts.html : ficheGroups ne liste pas chaque fiche une fois")
    cats = {c["id"] for c in data["findingCats"]}
    for f in findings.values():
        if not f.get("src"):
            fail(f"constat {f['id']} sans fichier source")
        if f["cat"] not in cats or f["effect"] not in (1, 2, 3):
            fail(f"constat {f['id']} : catégorie ou effet inconnu")
        for fid in f.get("fiches", []):
            if fid not in fiches:
                fail(f"constat {f['id']} : fiche inconnue {fid}")
    for v in data["traceVars"].values():
        if v["node"] not in nodes or v.get("fiche", "redacteur-image") not in fiches:
            fail(f"traceVars : auteur inconnu {v}")
    steps = {s["id"] for s in d["steps"]}
    if set(d.get("stepPrompts", {})) != steps:
        fail("data.js : stepPrompts doit lier chaque étape de la carte")
    for sid, nid in d.get("stepPrompts", {}).items():
        if nid is not None and nid not in nodes:
            fail(f"stepPrompts : étape {sid} vers un nœud inconnu {nid}")

    # Chaque fichier cité existe, et la ligne citée aussi.
    def refs(obj, where):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("src", "calledBy"):
                    for r in cited(v):
                        yield r, where
                else:
                    yield from refs(v, f"{where}.{k}" if k in ("id",) else where)
        elif isinstance(obj, list):
            for v in obj:
                yield from refs(v, where if not isinstance(v, dict) else f"prompts-data {v.get('id', '')}".strip())

    all_refs = list(refs(data, "prompts-data"))
    for r, where in all_refs:
        check_cite(r, where)

    # Points d'assemblage d'un prompt image : la définition de chaque fonction est citée par une fiche.
    spans: dict[str, list[tuple[int, int]]] = {}
    for f in fiches.values():
        for r in [*cited(f.get("calledBy")), *(s for c in f.get("code", []) for s in cited(c["src"]))]:
            m = CITE.match(r)
            if m and m.group("a"):
                spans.setdefault(m.group("path"), []).append((int(m.group("a")), int(m.group("b") or m.group("a"))))
    for module, fn in IMAGE_PROMPT_POINTS:
        rel = f"engine/mangaka_engine/{module}"
        src = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        line = next((i for i, text in enumerate(src, 1) if text.startswith(f"def {fn}(")), None)
        if line is None:
            fail(f"point de prompt image introuvable : {module} › {fn}")
        elif not any(a <= line <= b for a, b in spans.get(rel, [])):
            fail(f"prompts.html : {module} › {fn} (ligne {line}) n'est cité par aucune fiche")
    print(
        f"chaîne des prompts : {len(fiches)} fiches, {len(findings)} constats, {len(all_refs)} citations ; "
        f"variables déclarées absentes de leur gabarit : {', '.join(dead) or 'aucune'}"
    )


def check_goulots(d: dict) -> None:
    """goulots-data.js : chaque citation (fichier, ligne, extrait) colle au code ; étapes de job connues."""
    g = load_data("goulots-data.js", "GOULOTS")
    cites = [c for bloc in g["structure"] for item in bloc["items"] for c in item["src"]]
    cites += [c for f in g["faiblesses"] for c in f["src"]]
    for c in cites:
        path = ROOT / c["f"]
        if not path.is_file():
            fail(f"goulots : fichier cité introuvable : {c['f']}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if not any(c["x"] in line for line in lines[c["l"] - 1 : c["l"] + 3]):
            fail(f"goulots : « {c['x']} » absent de {c['f']}:{c['l']} (ou des 3 lignes suivantes)")
    jobs = {q["step"] for q in d["queueSteps"]} | {p["step"] for p in d["poolSteps"]}
    ids = {s["id"] for s in d["steps"]}
    for job, step in g["jobToStep"].items():
        if job not in jobs:
            fail(f"goulots : étape de job inconnue {job!r}")
        if step not in ids:
            fail(f"goulots : étape de la carte inconnue {step!r}")
    for step in g["logKindToStep"].values():
        if step not in ids:
            fail(f"goulots : étape de la carte inconnue {step!r}")
    # mesurer.py range dans la file ComfyUI les mêmes étapes que la carte.
    src = (TUTO / "mesurer.py").read_text(encoding="utf-8")
    block = re.search(r"ETAPES_FILE_COMFY = \(([^)]*)\)", src)
    comfy = set(re.findall(r'"(\w+)"', block.group(1))) if block else set()
    if comfy != {q["step"] for q in d["queueSteps"]}:
        fail(f"mesurer.py : ETAPES_FILE_COMFY {sorted(comfy)} ≠ file ComfyUI de data.js")
    print(f"{len(cites)} citations de goulots-data.js vérifiées")


def main() -> int:
    d = load_data()
    for check in (
        check_providers,
        check_workflows,
        check_defaults,
        check_agents,
        check_queue,
        check_gate,
        check_sources,
        check_goulots,
        check_prompts,
    ):
        check(d)
    if errors:
        print("Écarts entre le tutoriel et le dépôt :")
        for e in errors:
            print(" -", e)
        return 1
    print(
        f"OK : {len(d['steps'])} étapes, {len(d['agents'])} agents, {len(d['queueSteps'])} lignes de file, tout colle au dépôt."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
