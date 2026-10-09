#!/usr/bin/env node
// Lance l'interpréteur du venv du moteur avec les arguments donnés (pytest, ruff…).
import { spawnSync } from "node:child_process";
import { ENGINE_DIR, hasVenv, venvPython } from "./lib.mjs";

if (!hasVenv()) {
  console.error("[moteur] venv absent : lance d'abord `npm install` ou `npm run setup:engine`.");
  process.exit(1);
}
const res = spawnSync(venvPython(), process.argv.slice(2), { stdio: "inherit", cwd: ENGINE_DIR });
process.exit(res.status ?? 1);
