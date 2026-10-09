#!/usr/bin/env bash
# Installe l'icône « Mangaka Team » : menu des applications et bureau.
#
#   scripts/install-desktop.sh              installe (ou met à jour, sans doublon)
#   scripts/install-desktop.sh --uninstall  retire les deux copies
#
# - ~/.local/share/applications/mangaka-team.desktop (ou $XDG_DATA_HOME/applications)
# - <dossier Bureau>/mangaka-team.desktop (xdg-user-dir DESKTOP, ~/Bureau en français),
#   exécutable et marqué « de confiance » pour que GNOME le lance sans avertissement.
# MANGAKA_DESKTOP_DIR remplace le dossier du bureau détecté.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FILE_NAME="mangaka-team.desktop"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON="$ROOT/assets/icon/mangaka-team-512.png"

say() { printf '[mangaka-team] %s\n' "$*"; }

# Dossier du bureau : xdg-user-dir, sinon user-dirs.dirs, sinon ~/Desktop.
desktop_dir() {
  local dir=""
  if [[ -n "${MANGAKA_DESKTOP_DIR:-}" ]]; then
    printf '%s' "$MANGAKA_DESKTOP_DIR"
    return
  fi
  if command -v xdg-user-dir >/dev/null 2>&1; then
    dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
  fi
  if [[ -z "$dir" ]]; then
    local conf="${XDG_CONFIG_HOME:-$HOME/.config}/user-dirs.dirs" line
    if [[ -f "$conf" ]] && line="$(grep -E '^XDG_DESKTOP_DIR=' "$conf" | tail -n1)"; then
      dir="${line#*=}"
      dir="${dir//\"/}"
      dir="${dir//\$HOME/$HOME}"
    fi
  fi
  # xdg-user-dir renvoie $HOME quand le bureau est désactivé : pas de copie dans ce cas.
  [[ -z "$dir" ]] && dir="$HOME/Desktop"
  printf '%s' "$dir"
}

# Argument de la clé Exec (spécification Desktop Entry) : entre guillemets, avec " ` $ \
# échappés, puis les \ doublés pour la chaîne du fichier.
exec_arg() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//\`/\\\`}"
  s="${s//\$/\\\$}"
  s="${s//\\/\\\\}"
  printf '"%s"' "$s"
}

render() {
  cat <<EOF
[Desktop Entry]
Type=Application
Version=1.5
Name=Mangaka Team
GenericName=Studio manga et BD
Comment=Studio local de planches manga et BD assisté par IA : démarre Ollama, ComfyUI et l'atelier, puis ouvre l'interface
Exec=$(exec_arg "$ROOT/scripts/launch.sh")
Path=$ROOT
Icon=$ICON
Terminal=false
StartupNotify=false
Categories=Graphics;2DGraphics;
Keywords=manga;BD;bande dessinée;planche;ComfyUI;
Actions=arreter;

[Desktop Action arreter]
Name=Arrêter
Exec=$(exec_arg "$ROOT/scripts/stop.sh")
EOF
}

do_uninstall() {
  local desk
  desk="$(desktop_dir)"
  for f in "$APPS_DIR/$FILE_NAME" "$desk/$FILE_NAME"; do
    if [[ -e "$f" ]]; then
      rm -f "$f"
      say "supprimé : $f"
    fi
  done
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true
  say "icône désinstallée"
}

do_install() {
  local desk tmpdir tmp
  [[ -f "$ICON" ]] || say "attention : icône absente ($ICON)"
  chmod +x "$ROOT/scripts/launch.sh" "$ROOT/scripts/stop.sh"

  tmpdir="$(mktemp -d)"
  # shellcheck disable=SC2064 # chemin figé volontairement
  trap "rm -rf '$tmpdir'" EXIT
  tmp="$tmpdir/$FILE_NAME"
  render >"$tmp"
  if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$tmp" || { say "fichier .desktop invalide"; exit 1; }
  fi

  # install(1) remplace le fichier : relancer le script ne crée jamais de doublon.
  mkdir -p "$APPS_DIR"
  install -m 0755 "$tmp" "$APPS_DIR/$FILE_NAME"
  say "menu des applications : $APPS_DIR/$FILE_NAME"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true

  desk="$(desktop_dir)"
  if [[ "$desk" == "$HOME" || "$desk" == "$HOME/" ]]; then
    say "pas de dossier Bureau configuré : icône installée seulement dans le menu"
    return
  fi
  mkdir -p "$desk"
  install -m 0755 "$tmp" "$desk/$FILE_NAME"
  # GNOME (Desktop Icons NG) exige un lanceur exécutable et marqué de confiance.
  if command -v gio >/dev/null 2>&1; then
    gio set "$desk/$FILE_NAME" metadata::trusted true 2>/dev/null ||
      say "gio n'a pas pu marquer l'icône de confiance : clic droit → « Autoriser l'exécution »"
  fi
  say "bureau : $desk/$FILE_NAME"
  say "icône installée — double-clic sur « Mangaka Team » pour tout démarrer"
}

case "${1:-}" in
  "") do_install ;;
  --uninstall) do_uninstall ;;
  -h | --help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *)
    echo "Option inconnue : $1" >&2
    exit 2
    ;;
esac
