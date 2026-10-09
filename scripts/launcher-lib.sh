# shellcheck shell=bash
# Fonctions partagées par launch.sh et stop.sh (sourcé, jamais exécuté seul).
#
# Configuration (par ordre de priorité) :
#   1. variables d'environnement déjà définies ;
#   2. launcher.env à la racine du dépôt (gitignoré, voir launcher.env.example) ;
#   3. .env à la racine du dépôt ;
#   4. valeurs par défaut ci-dessous.
# MANGAKA_LAUNCHER_ENV_FILES (liste séparée par « : ») remplace la liste des fichiers lus
# (utilisé par les tests).

MANGAKA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MANGAKA_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mangaka-team"
MANGAKA_LOG_DIR="$MANGAKA_STATE_DIR/logs"
MANGAKA_PID_DIR="$MANGAKA_STATE_DIR/pids"

# Clés lues dans launcher.env / .env. Les autres clés de .env sont ignorées ici
# (scripts/dev.mjs relit .env lui-même pour le moteur).
LAUNCHER_KEYS=(
  COMFYUI_DIR COMFYUI_PYTHON COMFYUI_URL COMFYUI_ARGS COMFYUI_TIMEOUT
  OLLAMA_URL OLLAMA_BIN OLLAMA_TIMEOUT
  PORT ENGINE_PORT NPM_BIN APP_TIMEOUT
  START_OLLAMA START_COMFYUI OPEN_BROWSER
  MANGAKA_POLL_S STOP_TIMEOUT
)

# Remplace $HOME, ${HOME} et un « ~ » initial par le dossier personnel.
expand_home() {
  local v="$1"
  v="${v//\$\{HOME\}/$HOME}"
  v="${v//\$HOME/$HOME}"
  [[ "$v" == \~ || "$v" == \~/* ]] && v="$HOME${v:1}"
  printf '%s' "$v"
}

# Lit un fichier KEY=VALUE simple (sans l'exécuter) et remplit FILE_CONF.
read_env_file() {
  local file="$1" line key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${line#*=}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ${#value} -ge 2 && ( ("$value" == \"*\") || ("$value" == \'*\') ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    FILE_CONF["$key"]="$(expand_home "$value")"
  done <"$file"
}

load_config() {
  declare -gA FILE_CONF=()
  local files=() f key
  if [[ -n "${MANGAKA_LAUNCHER_ENV_FILES+x}" ]]; then
    IFS=: read -ra files <<<"$MANGAKA_LAUNCHER_ENV_FILES"
  else
    files=("$MANGAKA_ROOT/.env" "$MANGAKA_ROOT/launcher.env")
  fi
  # Le dernier fichier lu gagne : launcher.env prime sur .env.
  for f in "${files[@]}"; do
    [[ -n "$f" ]] && read_env_file "$f"
  done
  for key in "${LAUNCHER_KEYS[@]}"; do
    if [[ -z "${!key+x}" && -n "${FILE_CONF[$key]+x}" ]]; then
      printf -v "$key" '%s' "${FILE_CONF[$key]}"
    fi
  done

  COMFYUI_DIR="$(expand_home "${COMFYUI_DIR:-$HOME/ComfyUI}")"
  COMFYUI_PYTHON="$(expand_home "${COMFYUI_PYTHON:-$HOME/comfyui-env/bin/python}")"
  COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"
  COMFYUI_URL="${COMFYUI_URL%/}"
  COMFYUI_ARGS="${COMFYUI_ARGS:-}"
  COMFYUI_TIMEOUT="${COMFYUI_TIMEOUT:-180}"
  OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
  OLLAMA_URL="${OLLAMA_URL%/}"
  OLLAMA_BIN="$(expand_home "${OLLAMA_BIN:-ollama}")"
  OLLAMA_TIMEOUT="${OLLAMA_TIMEOUT:-30}"
  PORT="${PORT:-3000}"
  ENGINE_PORT="${ENGINE_PORT:-8765}"
  NPM_BIN="$(expand_home "${NPM_BIN:-npm}")"
  APP_TIMEOUT="${APP_TIMEOUT:-180}"
  START_OLLAMA="${START_OLLAMA:-true}"
  START_COMFYUI="${START_COMFYUI:-true}"
  OPEN_BROWSER="${OPEN_BROWSER:-true}"
  MANGAKA_POLL_S="${MANGAKA_POLL_S:-1}"
  STOP_TIMEOUT="${STOP_TIMEOUT:-15}"
  # Transmis à « npm run dev » : ils priment sur .env, relu par scripts/dev.mjs.
  export PORT ENGINE_PORT COMFYUI_URL
}

is_true() {
  case "${1,,}" in
    1 | true | yes | oui | on) return 0 ;;
    *) return 1 ;;
  esac
}

# « http://hote:port/chemin » → « hote port » (port 80/443 par défaut selon le schéma).
url_host_port() {
  local url="$1" scheme="http" rest host port
  [[ "$url" == *://* ]] && scheme="${url%%://*}" && rest="${url#*://}" || rest="$url"
  rest="${rest%%/*}"
  host="${rest%:*}"
  port="${rest##*:}"
  if [[ "$host" == "$rest" ]]; then
    port=80
    [[ "$scheme" == https ]] && port=443
  fi
  printf '%s %s\n' "$host" "$port"
}

# Code HTTP renvoyé par une URL (« 000 » si rien ne répond). $2 : délai max en secondes.
http_code() {
  local url="$1" max="${2:-3}"
  if command -v curl >/dev/null 2>&1; then
    curl -s -o /dev/null -m "$max" -w '%{http_code}' "$url" 2>/dev/null || true
  else
    python3 - "$url" "$max" <<'PY' 2>/dev/null || printf '000'
import sys, urllib.error, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=float(sys.argv[2])) as r:
        print(r.status, end="")
except urllib.error.HTTPError as e:
    print(e.code, end="")
except Exception:
    print("000", end="")
PY
  fi
}

# Corps d'une réponse HTTP (vide si rien ne répond).
http_body() {
  local url="$1" max="${2:-3}"
  if command -v curl >/dev/null 2>&1; then
    curl -s -m "$max" "$url" 2>/dev/null || true
  else
    python3 -c 'import sys, urllib.request; print(urllib.request.urlopen(sys.argv[1], timeout=float(sys.argv[2])).read().decode(errors="replace"))' \
      "$url" "$max" 2>/dev/null || true
  fi
}

# Le port TCP accepte-t-il des connexions ?
port_open() {
  timeout 2 bash -c ": >/dev/tcp/$1/$2" 2>/dev/null
}

# La réponse de GET /health sur le port du moteur vient-elle bien de notre moteur FastAPI ?
# (corps de la forme {"engine":{"status":"ok",…},…}, que les fournisseurs soient verts ou non).
ENGINE_HEALTH_RE='"engine"[[:space:]]*:[[:space:]]*\{[[:space:]]*"status"'
engine_is_ours() {
  http_body "http://127.0.0.1:$ENGINE_PORT/health" "${1:-10}" | grep -Eq "$ENGINE_HEALTH_RE"
}

pid_file() { printf '%s/%s.pid' "$MANGAKA_PID_DIR" "$1"; }
log_file() { printf '%s/%s.log' "$MANGAKA_LOG_DIR" "$1"; }

# Date de démarrage d'un processus (champ 22 de /proc/PID/stat) : protège contre la
# réutilisation d'un PID par un autre programme.
proc_starttime() {
  local stat
  stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
  stat="${stat##*) }"
  # Après « ) », le champ 3 (état) est en position 1 → le champ 22 est en position 20.
  # shellcheck disable=SC2086
  set -- $stat
  # Un zombie (arrêté, pas encore récolté) ne compte pas comme vivant.
  [[ "$1" == Z ]] && return 1
  printf '%s' "${20}"
}

# Enregistre « PID date_de_démarrage » pour un service lancé par le lanceur.
record_pid() {
  local name="$1" pid="$2" start
  start="$(proc_starttime "$pid")" || start=""
  printf '%s %s\n' "$pid" "$start" >"$(pid_file "$name")"
}

# Affiche le PID du service s'il a été lancé par le lanceur et tourne toujours.
# Supprime le fichier PID s'il est périmé.
owned_pid() {
  local name="$1" file pid start current
  file="$(pid_file "$name")"
  [[ -f "$file" ]] || return 1
  read -r pid start <"$file" || true
  if [[ "$pid" =~ ^[0-9]+$ ]] && current="$(proc_starttime "$pid")" && [[ -z "$start" || "$current" == "$start" ]]; then
    printf '%s' "$pid"
    return 0
  fi
  rm -f "$file"
  return 1
}

say() { printf '[mangaka-team] %s\n' "$*"; }

# Notification de bureau (si notify-send est disponible), toujours doublée sur la sortie.
NOTIFY_ID=""
notify() {
  local urgency="$1" title="$2" body="$3" id
  say "$title — $body"
  command -v notify-send >/dev/null 2>&1 || return 0
  local args=(-a "Mangaka Team" -u "$urgency" -i "$MANGAKA_ROOT/assets/icon/mangaka-team-256.png")
  if [[ "$urgency" != critical ]]; then
    # Remplace la notification de progression précédente au lieu d'en empiler.
    [[ -n "$NOTIFY_ID" ]] && args+=(-r "$NOTIFY_ID")
    id="$(notify-send "${args[@]}" -p "$title" "$body" 2>/dev/null)" || notify-send "${args[@]}" "$title" "$body" 2>/dev/null || true
    [[ "$id" =~ ^[0-9]+$ ]] && NOTIFY_ID="$id"
  else
    notify-send "${args[@]}" "$title" "$body" 2>/dev/null || true
  fi
  return 0
}
