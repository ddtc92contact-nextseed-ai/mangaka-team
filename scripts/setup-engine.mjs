#!/usr/bin/env node
// Crée engine/.venv et installe le moteur Python (appelé par `npm install`).
// Ignoré si MANGAKA_SKIP_ENGINE_SETUP=1 (ex. job CI web).
import { spawnSync } from "node:child_process";
import { ENGINE_DIR, VENV_DIR, findSystemPython, hasVenv, venvPython } from "./lib.mjs";

if (process.env.MANGAKA_SKIP_ENGINE_SETUP === "1") {
  console.log("[moteur] installation ignorée (MANGAKA_SKIP_ENGINE_SETUP=1)");
  process.exit(0);
}

function run(cmd, args) {
  console.log(`[moteur] ${cmd} ${args.join(" ")}`);
  const res = spawnSync(cmd, args, { stdio: "inherit", cwd: ENGINE_DIR });
  if (res.status !== 0) {
    console.error(`[moteur] échec : ${cmd} ${args.join(" ")}`);
    process.exit(res.status ?? 1);
  }
}

if (!hasVenv()) {
  const python = findSystemPython();
  if (!python) {
    console.error("[moteur] Python >= 3.12 introuvable. Installe-le (apt install python3.12 python3.12-venv) puis relance `npm run setup:engine`.");
    process.exit(1);
  }
  run(python, ["-m", "venv", VENV_DIR]);
}

run(venvPython(), ["-m", "pip", "install", "--quiet", "--upgrade", "pip"]);
run(venvPython(), ["-m", "pip", "install", "--quiet", "-e", ".[dev]"]);
console.log("[moteur] prêt.");
