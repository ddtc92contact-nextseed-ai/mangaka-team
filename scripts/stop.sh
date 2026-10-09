#!/usr/bin/env bash
# Arrête ce que scripts/launch.sh a démarré, et seulement cela : les PID enregistrés dans
# ~/.local/state/mangaka-team/pids/. Un Ollama ou un ComfyUI qui tournait déjà avant le
# lanceur (systemd, lancé à la main…) n'a pas de PID enregistré : il n'est jamais touché.
#
#   scripts/stop.sh
set -uo pipefail

# shellcheck source=scripts/launcher-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/launcher-lib.sh"

load_config
mkdir -p "$MANGAKA_LOG_DIR" "$MANGAKA_PID_DIR"
exec > >(tee -a "$(log_file launcher)") 2>&1
say "=== $(date '+%F %T') — arrêt"

# Envoie un signal au groupe de processus du service (npm → node → next + uvicorn), ou au
# seul processus s'il n'est pas chef de groupe.
signal_service() {
  local sig="$1" pid="$2" pgid
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
  if [[ "$pgid" == "$pid" ]]; then
    kill "-$sig" -- "-$pid" 2>/dev/null
  else
    kill "-$sig" "$pid" 2>/dev/null
  fi
}

# PID des processus qui écoutent sur un port TCP local (ss -p ne montre que les nôtres).
port_listeners() {
  command -v ss >/dev/null 2>&1 || return 0
  ss -Hltnp "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
}

# Processus du moteur (port $ENGINE_PORT) qui appartiennent à la session de « npm run dev »
# démarrée par le lanceur ($1). Un moteur lancé autrement n'est jamais retenu.
engine_pids_of() {
  local session="$1" pid sid
  for pid in $(port_listeners "$ENGINE_PORT"); do
    sid="$(ps -o sid= -p "$pid" 2>/dev/null | tr -d ' ')"
    [[ "$sid" == "$session" ]] && printf '%s\n' "$pid"
  done
}

any_alive() {
  local pid
  for pid in "$@"; do
    # proc_starttime échoue pour un processus disparu ou zombie.
    proc_starttime "$pid" >/dev/null && return 0
  done
  return 1
}

stopped=()
failed=()
for name in app comfyui ollama; do
  if ! pid="$(owned_pid "$name")"; then
    say "$name : rien à arrêter (non lancé par le lanceur)"
    continue
  fi
  engine_pids=()
  if [[ "$name" == app ]]; then
    mapfile -t engine_pids < <(engine_pids_of "$pid")
  fi
  say "$name : arrêt (PID $pid)"
  signal_service TERM "$pid"
  deadline=$((SECONDS + STOP_TIMEOUT))
  while owned_pid "$name" >/dev/null && ((SECONDS < deadline)); do
    sleep 0.2
  done
  if owned_pid "$name" >/dev/null; then
    say "$name : ne répond pas à SIGTERM, SIGKILL"
    signal_service KILL "$pid"
    sleep 0.5
  fi
  # Le moteur est normalement arrêté avec le groupe de « npm run dev » ; s'il en est sorti
  # (processus détaché) et écoute encore sur ENGINE_PORT, on l'arrête explicitement.
  if any_alive "${engine_pids[@]}"; then
    say "moteur : toujours actif sur le port $ENGINE_PORT, arrêt (PID ${engine_pids[*]})"
    kill -TERM "${engine_pids[@]}" 2>/dev/null
    deadline=$((SECONDS + STOP_TIMEOUT))
    while any_alive "${engine_pids[@]}" && ((SECONDS < deadline)); do
      sleep 0.2
    done
    any_alive "${engine_pids[@]}" && kill -KILL "${engine_pids[@]}" 2>/dev/null && sleep 0.5
    if any_alive "${engine_pids[@]}"; then
      failed+=("moteur (port $ENGINE_PORT)")
    fi
  fi
  if owned_pid "$name" >/dev/null; then
    failed+=("$name")
  else
    rm -f "$(pid_file "$name")"
    stopped+=("$name")
  fi
  if [[ "$name" == app ]] && port_open 127.0.0.1 "$ENGINE_PORT" && engine_is_ours 3; then
    say "moteur : un moteur non lancé par le lanceur répond encore sur le port $ENGINE_PORT (non touché)"
  fi
done

if ((${#failed[@]})); then
  notify critical "Mangaka Team" "Impossible d'arrêter : ${failed[*]} — journal : $(log_file launcher)"
  exit 1
fi
if ((${#stopped[@]})); then
  notify normal "Mangaka Team" "Arrêté : ${stopped[*]}"
else
  notify normal "Mangaka Team" "Rien à arrêter"
fi
exit 0
