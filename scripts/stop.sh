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

stopped=()
failed=()
for name in app comfyui ollama; do
  if ! pid="$(owned_pid "$name")"; then
    say "$name : rien à arrêter (non lancé par le lanceur)"
    continue
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
  if owned_pid "$name" >/dev/null; then
    failed+=("$name")
  else
    rm -f "$(pid_file "$name")"
    stopped+=("$name")
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
