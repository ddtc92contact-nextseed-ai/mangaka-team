#!/usr/bin/env node
// `npm run dev` : démarre le moteur FastAPI et l'UI Next.js ensemble.
// - UI sur $PORT (3000 par défaut), moteur sur $ENGINE_PORT (8765 par défaut).
// - Sans .env, tout tourne en mode mock (aucun appel réseau, aucun GPU).
// - Si le moteur plante, l'UI reste en ligne et affiche « moteur hors ligne ».
import { spawn } from "node:child_process";
import { join } from "node:path";
import { ENGINE_DIR, ROOT, hasVenv, loadDotEnv, venvPython } from "./lib.mjs";

await loadDotEnv();

const port = process.env.PORT || "3000";
const enginePort = process.env.ENGINE_PORT || "8765";
const engineHost = process.env.ENGINE_HOST || "127.0.0.1";
const env = { ...process.env, PORT: port, ENGINE_PORT: enginePort, ENGINE_HOST: engineHost };

const children = [];

function start(name, color, cmd, args, cwd) {
  const child = spawn(cmd, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
  const prefix = `\x1b[${color}m[${name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = "";
    stream.on("data", (chunk) => {
      buf += chunk.toString();
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) out.write(prefix + line + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code, signal) => {
    console.log(`${prefix}arrêté (${signal ?? code})`);
    if (name === "web") shutdown(code ?? 0);
  });
  children.push(child);
  return child;
}

function shutdown(code = 0) {
  for (const c of children) if (c.exitCode === null) c.kill("SIGTERM");
  setTimeout(() => process.exit(code), 300);
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

if (hasVenv()) {
  start(
    "moteur",
    "35",
    venvPython(),
    ["-m", "uvicorn", "mangaka_engine.main:app", "--host", engineHost, "--port", enginePort, "--reload", "--reload-dir", "mangaka_engine"],
    ENGINE_DIR,
  );
} else {
  console.error("\x1b[31m[moteur] venv absent : lance `npm run setup:engine`. L'UI démarre quand même (moteur hors ligne).\x1b[0m");
}

start("web", "36", process.execPath, [join(ROOT, "node_modules", "next", "dist", "bin", "next"), "dev", "-p", port], join(ROOT, "web"));
