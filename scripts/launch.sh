#!/usr/bin/env bash
# Lanceur en un clic : démarre Ollama, ComfyUI et l'application (moteur + UI), puis ouvre
# l'interface dans le navigateur.
#
# Idempotent : chaque service n'est démarré que si sa sonde de santé ne répond pas. Un service
# déjà en ligne (systemd, lancé à la main…) n'est jamais relancé ni enregistré : stop.sh n'y
# touchera pas. Ne fait jamais appel à sudo ni à systemd.
#
#   scripts/launch.sh [--no-browser]
#
# Journaux : ~/.local/state/mangaka-team/logs/<service>.log ; PID : …/mangaka-team/pids/.
# Configuration : launcher.env (voir launcher.env.example) ou .env.
set -uo pipefail

# shellcheck source=scripts/launcher-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/launcher-lib.sh"

for arg in "$@"; do
  case "$arg" in
    --no-browser) OPEN_BROWSER=false ;;
    -h | --help)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Option inconnue : $arg" >&2
      exit 2
      ;;
  esac
done

load_config
mkdir -p "$MANGAKA_LOG_DIR" "$MANGAKA_PID_DIR"
# Lancé depuis l'icône, il n'y a pas de terminal : on garde une trace de tout.
exec > >(tee -a "$(log_file launcher)") 2>&1
say "=== $(date '+%F %T') — lancement depuis $MANGAKA_ROOT"

# Un seul lanceur à la fois (double-clic sur l'icône).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$MANGAKA_STATE_DIR/launch.lock"
  if ! flock -n 9; then
    notify normal "Mangaka Team" "Démarrage déjà en cours…"
    exit 0
  fi
fi

FAILURES=()
declare -A STARTED=()
APP_OK=true

# « de Ollama », « de l'application », mais « du moteur ».
de() {
  if [[ "$1" == "le "* ]]; then printf 'du %s' "${1#le }"; else printf 'de %s' "$1"; fi
}

fail() {
  local name="$1" reason="$2"
  FAILURES+=("$name")
  notify critical "Mangaka Team : échec $(de "$name")" "$reason — journal : $(log_file "$3")"
}

# Démarre une commande en arrière-plan, détachée (nouvelle session : survit au lanceur et
# stop.sh peut arrêter tout son groupe de processus). Journal en ajout, PID enregistré.
start_service() {
  local name="$1" dir="$2"
  shift 2
  local log
  log="$(log_file "$name")"
  printf '\n=== %s — démarrage par le lanceur : %s\n' "$(date '+%F %T')" "$*" >>"$log"
  # 9>&- : le verrou du lanceur ne doit pas rester tenu par les services.
  (cd "$dir" && exec setsid "$@" </dev/null >>"$log" 2>&1 9>&-) &
  local pid=$!
  STARTED[$name]=1
  # Laisse le temps à setsid de s'exécuter avant de lire la date de démarrage.
  sleep 0.1
  record_pid "$name" "$pid"
  say "$name démarré (PID $pid), journal : $log"
}

# Attend qu'une sonde réponde. $1 nom affiché, $2 clé du service, $3 délai, $4… sonde.
# DEAD_CHECK (facultatif) : fonction qui réussit si le service est mort au démarrage alors que
# son processus tourne encore (le moteur sous « npm run dev »), DEAD_REASON : message associé.
DEAD_CHECK=""
DEAD_REASON=""
wait_healthy() {
  local label="$1" name="$2" timeout="$3"
  shift 3
  local start=$SECONDS
  notify normal "Mangaka Team" "Attente $(de "$label")…"
  while true; do
    if "$@"; then
      say "$label en ligne ($((SECONDS - start)) s)"
      return 0
    fi
    # Un service lancé par nous qui meurt pendant l'attente : inutile d'attendre la fin du délai.
    if [[ -n "${STARTED[$name]:-}" ]] && ! owned_pid "$name" >/dev/null; then
      fail "$label" "le processus s'est arrêté au démarrage" "$name"
      return 1
    fi
    if [[ -n "$DEAD_CHECK" ]] && "$DEAD_CHECK"; then
      fail "$label" "$DEAD_REASON" "$name"
      return 1
    fi
    if ((SECONDS - start >= timeout)); then
      fail "$label" "pas de réponse après ${timeout} s" "$name"
      return 1
    fi
    sleep "$MANGAKA_POLL_S"
  done
}

ollama_up() { [[ "$(http_code "$OLLAMA_URL/api/version")" == 200 ]]; }
comfyui_up() { [[ "$(http_code "$COMFYUI_URL/system_stats")" == 200 ]]; }
APP_URL="http://127.0.0.1:$PORT"
# shellcheck disable=SC2317,SC2329 # appelée via wait_healthy
app_up() { [[ "$(http_code "$APP_URL/" 10)" != 000 ]]; }
# Une page qui répond sur le port est-elle bien la nôtre (lancée à la main avec npm run dev) ?
app_is_ours() { http_body "$APP_URL/" 30 | grep -q "mangaka-team"; }
# Le moteur compte comme prêt dès que /health répond, fournisseurs verts ou non.
# shellcheck disable=SC2317,SC2329 # appelée via wait_healthy
engine_up() { engine_is_ours 5; }
# scripts/dev.mjs écrit cette ligne dans app.log quand le moteur meurt au démarrage ; seules les
# lignes écrites depuis notre lancement comptent (le journal est en ajout).
APP_LOG_OFFSET=0
# shellcheck disable=SC2317,SC2329 # appelée via wait_healthy
engine_died() { tail -c "+$((APP_LOG_OFFSET + 1))" "$(log_file app)" 2>/dev/null | grep -q "le moteur n'a pas démarré"; }
ENGINE_PORT_HINT="change ENGINE_PORT dans .env ou launcher.env"

# --- Ollama -----------------------------------------------------------------------------
WAIT_OLLAMA=false
if is_true "$START_OLLAMA"; then
  if ollama_up; then
    say "Ollama déjà en ligne sur $OLLAMA_URL"
  elif owned_pid ollama >/dev/null; then
    WAIT_OLLAMA=true
  elif ! command -v "$OLLAMA_BIN" >/dev/null 2>&1; then
    fail "Ollama" "commande « $OLLAMA_BIN » introuvable (OLLAMA_BIN)" ollama
  else
    read -r host port < <(url_host_port "$OLLAMA_URL")
    notify normal "Mangaka Team" "Démarrage d'Ollama…"
    OLLAMA_HOST="$host:$port" start_service ollama "$HOME" "$OLLAMA_BIN" serve
    WAIT_OLLAMA=true
  fi
fi

# --- ComfyUI ----------------------------------------------------------------------------
WAIT_COMFYUI=false
if is_true "$START_COMFYUI"; then
  if comfyui_up; then
    say "ComfyUI déjà en ligne sur $COMFYUI_URL"
  elif owned_pid comfyui >/dev/null; then
    WAIT_COMFYUI=true
  elif [[ ! -f "$COMFYUI_DIR/main.py" ]]; then
    fail "ComfyUI" "main.py introuvable dans $COMFYUI_DIR (COMFYUI_DIR)" comfyui
  elif [[ ! -x "$COMFYUI_PYTHON" ]]; then
    fail "ComfyUI" "python du venv introuvable : $COMFYUI_PYTHON (COMFYUI_PYTHON)" comfyui
  else
    read -r host port < <(url_host_port "$COMFYUI_URL")
    extra=()
    [[ -n "$COMFYUI_ARGS" ]] && read -ra extra <<<"$COMFYUI_ARGS"
    notify normal "Mangaka Team" "Démarrage de ComfyUI…"
    start_service comfyui "$COMFYUI_DIR" "$COMFYUI_PYTHON" main.py --listen "$host" --port "$port" "${extra[@]}"
    WAIT_COMFYUI=true
  fi
fi

# --- Application (moteur + UI) ----------------------------------------------------------
# « npm run dev » sert l'interface sur $PORT et le moteur sur $ENGINE_PORT : les deux ports
# sont vérifiés avant de démarrer quoi que ce soit.
WAIT_APP=false
WAIT_ENGINE=false
if owned_pid app >/dev/null; then
  WAIT_APP=true
  WAIT_ENGINE=true
else
  ui_busy=false
  engine_busy=false
  port_open 127.0.0.1 "$PORT" && ui_busy=true
  port_open 127.0.0.1 "$ENGINE_PORT" && engine_busy=true
  if $ui_busy && ! app_is_ours; then
    fail "l'application" "le port $PORT est occupé par un autre programme (change PORT dans .env ou launcher.env)" app
    APP_OK=false
  fi
  if $engine_busy && ! engine_is_ours; then
    fail "le moteur (port $ENGINE_PORT)" "le port $ENGINE_PORT du moteur est occupé par un autre programme ($ENGINE_PORT_HINT)" app
    APP_OK=false
  fi
  if ! $APP_OK; then
    :
  elif $ui_busy; then
    say "Application déjà en ligne sur $APP_URL"
    if $engine_busy; then
      say "Moteur déjà en ligne sur le port $ENGINE_PORT"
    else
      # Interface lancée à la main mais moteur absent (ou encore en train de démarrer).
      WAIT_ENGINE=true
    fi
  elif ! command -v "$NPM_BIN" >/dev/null 2>&1; then
    fail "l'application" "commande « $NPM_BIN » introuvable (NPM_BIN)" app
    APP_OK=false
  else
    $engine_busy && say "Moteur déjà en ligne sur le port $ENGINE_PORT : réutilisé"
    APP_LOG_OFFSET="$(stat -c %s "$(log_file app)" 2>/dev/null || echo 0)"
    notify normal "Mangaka Team" "Démarrage de l'atelier…"
    start_service app "$MANGAKA_ROOT" "$NPM_BIN" run dev
    WAIT_APP=true
    WAIT_ENGINE=true
  fi
fi

# --- Attente des sondes -----------------------------------------------------------------
$WAIT_OLLAMA && wait_healthy "Ollama" ollama "$OLLAMA_TIMEOUT" ollama_up
$WAIT_COMFYUI && wait_healthy "ComfyUI" comfyui "$COMFYUI_TIMEOUT" comfyui_up
# L'application n'est prête que si l'interface ET le moteur (/health) répondent, le tout dans
# APP_TIMEOUT. Moteur absent : échec, mais l'interface s'ouvre (« moteur hors ligne » y est affiché).
app_start=$SECONDS
if $WAIT_APP; then
  wait_healthy "l'application" app "$APP_TIMEOUT" app_up || { APP_OK=false; WAIT_ENGINE=false; }
fi
if $WAIT_ENGINE; then
  remaining=$((APP_TIMEOUT - (SECONDS - app_start)))
  ((remaining < 1)) && remaining=1
  DEAD_CHECK=engine_died
  DEAD_REASON="le moteur s'est arrêté au démarrage (port $ENGINE_PORT déjà pris ? $ENGINE_PORT_HINT)"
  wait_healthy "le moteur (port $ENGINE_PORT)" app "$remaining" engine_up
  DEAD_CHECK=""
fi

# --- Navigateur -------------------------------------------------------------------------
if $APP_OK && is_true "$OPEN_BROWSER"; then
  url="http://localhost:$PORT"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" </dev/null >/dev/null 2>&1 9>&- &
  else
    notify normal "Mangaka Team" "Ouvre $url dans ton navigateur"
  fi
fi

if ((${#FAILURES[@]})); then
  say "Échec : ${FAILURES[*]} (journaux dans $MANGAKA_LOG_DIR)"
  exit 1
fi
notify normal "Mangaka Team" "Tout est prêt : http://localhost:$PORT"
exit 0
