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
        (k, label, re.findall(r'"(\w+)"', tup)) for k, label, tup in re.findall(r'ActionDef\("(\w+)", "([^"]+)", \(([^)]*)\)\)', src)
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
    for check in (check_providers, check_workflows, check_defaults, check_agents, check_queue, check_gate, check_sources, check_goulots):
        check(d)
    if errors:
        print("Écarts entre le tutoriel et le dépôt :")
        for e in errors:
            print(" -", e)
        return 1
    print(f"OK : {len(d['steps'])} étapes, {len(d['agents'])} agents, {len(d['queueSteps'])} lignes de file, tout colle au dépôt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
