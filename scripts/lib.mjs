// Helpers partagés par les scripts npm (setup du moteur, dev, exécution).
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const ENGINE_DIR = join(ROOT, "engine");
export const VENV_DIR = join(ENGINE_DIR, ".venv");

export function venvPython() {
  return process.platform === "win32"
    ? join(VENV_DIR, "Scripts", "python.exe")
    : join(VENV_DIR, "bin", "python");
}

export function hasVenv() {
  return existsSync(venvPython());
}

/** Trouve un interpréteur Python >= 3.12 sur la machine. */
export function findSystemPython() {
  const candidates = [process.env.MANGAKA_PYTHON, "python3.12", "python3.13", "python3", "python"].filter(Boolean);
  for (const cmd of candidates) {
    const res = spawnSync(cmd, ["-c", "import sys; print(sys.version_info >= (3, 12))"], { encoding: "utf8" });
    if (res.status === 0 && res.stdout.trim() === "True") return cmd;
  }
  return null;
}

/** Charge un fichier .env simple (KEY=VALUE) sans écraser l'environnement existant. */
export async function loadDotEnv(path = join(ROOT, ".env")) {
  if (!existsSync(path)) return;
  const { readFileSync } = await import("node:fs");
  for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}
