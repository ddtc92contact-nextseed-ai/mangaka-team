"""Tests du lanceur en un clic (scripts/launch.sh, stop.sh, install-desktop.sh).

Aucun GPU, aucun vrai ComfyUI ni Ollama : les services sont de faux serveurs HTTP sur des ports
aléatoires et les commandes de démarrage (ollama, python de ComfyUI, npm) sont des stubs placés
en tête du PATH. HOME pointe vers un dossier temporaire.
"""

import os
import shutil
import socket
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

from fake_server import serve  # noqa: E402

ROOT = TESTS_DIR.parent.parent
LAUNCH = ROOT / "scripts" / "launch.sh"
STOP = ROOT / "scripts" / "stop.sh"
INSTALL = ROOT / "scripts" / "install-desktop.sh"
FAKE_SERVER = TESTS_DIR / "fake_server.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_exe(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip())
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[0]
    except (FileNotFoundError, IndexError):
        return False
    return state != "Z"


class Env:
    """Un HOME temporaire, des stubs dans le PATH et la configuration du lanceur."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.calls = tmp / "calls"
        self.comfy_dir = self.home / "ComfyUI"
        for d in (self.home, self.bin, self.calls, self.comfy_dir):
            d.mkdir(parents=True)
        (self.comfy_dir / "main.py").write_text("# faux ComfyUI\n")
        self.token = f"mangaka-test-{tmp.name}-{os.getpid()}"
        self.ports = {"ollama": free_port(), "comfyui": free_port(), "app": free_port()}
        self._servers: list = []
        self._procs: list[subprocess.Popen] = []

        # Chaque stub note son appel puis, selon STUB_<NOM> : serve (défaut), hang ou crash.
        behaviour = f"""
            case "${{STUB_MODE:-serve}}" in
              hang) exec python3 -c 'import time; time.sleep(300)' {self.token} ;;
              crash) echo "plantage simulé" >&2; exit 3 ;;
            esac
        """
        write_exe(
            self.bin / "ollama",
            f"""#!/usr/bin/env bash
            echo "$* OLLAMA_HOST=$OLLAMA_HOST" >> {self.calls}/ollama
            STUB_MODE="${{STUB_OLLAMA:-serve}}"
            {behaviour}
            exec python3 {FAKE_SERVER} "${{OLLAMA_HOST##*:}}" '{{"version":"0.0.0"}}' {self.token}
            """,
        )
        write_exe(
            self.bin / "comfy-python",
            f"""#!/usr/bin/env bash
            echo "$PWD $*" >> {self.calls}/comfyui
            STUB_MODE="${{STUB_COMFYUI:-serve}}"
            {behaviour}
            while [[ $# -gt 0 && "$1" != --port ]]; do shift; done
            exec python3 {FAKE_SERVER} "$2" '{{"system":{{}}}}' {self.token}
            """,
        )
        write_exe(
            self.bin / "npm",
            f"""#!/usr/bin/env bash
            echo "$PWD $* PORT=$PORT" >> {self.calls}/npm
            STUB_MODE="${{STUB_APP:-serve}}"
            {behaviour}
            exec python3 {FAKE_SERVER} "$PORT" '<title>mangaka-team</title>' {self.token}
            """,
        )
        for name in ("notify-send", "xdg-open", "gio"):
            write_exe(self.bin / name, f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> {self.calls}/{name}\n')

        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "LANG": "C.UTF-8",
            "MANGAKA_LAUNCHER_ENV_FILES": "",
            "COMFYUI_DIR": str(self.comfy_dir),
            "COMFYUI_PYTHON": str(self.bin / "comfy-python"),
            "COMFYUI_URL": f"http://127.0.0.1:{self.ports['comfyui']}",
            "OLLAMA_URL": f"http://127.0.0.1:{self.ports['ollama']}",
            "PORT": str(self.ports["app"]),
            "OLLAMA_TIMEOUT": "15",
            "COMFYUI_TIMEOUT": "15",
            "APP_TIMEOUT": "15",
            "MANGAKA_POLL_S": "0.2",
            "STOP_TIMEOUT": "5",
        }

    @property
    def state(self) -> Path:
        return self.home / ".local" / "state" / "mangaka-team"

    def pid(self, name: str) -> int | None:
        f = self.state / "pids" / f"{name}.pid"
        return int(f.read_text().split()[0]) if f.exists() else None

    def calls_of(self, name: str) -> list[str]:
        f = self.calls / name
        return f.read_text().splitlines() if f.exists() else []

    def wait_calls(self, name: str) -> list[str]:
        """Appels d'un stub lancé en arrière-plan (xdg-open) : attend qu'il ait écrit."""
        deadline = time.time() + 5
        while not self.calls_of(name) and time.time() < deadline:
            time.sleep(0.05)
        return self.calls_of(name)

    def run(self, script: Path, *args: str, timeout: float = 60, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(script), *args],
            env={**self.env, **extra},
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def already_running(self, name: str, body: str = "ok") -> None:
        """Un service qui tournait avant le lanceur (serveur dans le processus de test)."""
        server = serve(self.ports[name], body)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)

    def external_process(self, name: str, body: str = "ok") -> subprocess.Popen:
        """Un service qui tournait avant le lanceur, dans son propre processus."""
        proc = subprocess.Popen([sys.executable, str(FAKE_SERVER), str(self.ports[name]), body, self.token])
        self._procs.append(proc)
        deadline = time.time() + 10
        while time.time() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.ports[name])) == 0:
                    return proc
            time.sleep(0.05)
        raise RuntimeError("faux serveur externe pas prêt")

    def cleanup(self) -> None:
        self.run(STOP, timeout=30)
        for server in self._servers:
            server.shutdown()
            server.server_close()
        for proc in self._procs:
            proc.kill()
            proc.wait()
        subprocess.run(["pkill", "-KILL", "-f", self.token], check=False)


@pytest.fixture
def env(tmp_path: Path):
    e = Env(tmp_path)
    try:
        yield e
    finally:
        e.cleanup()


# --- launch.sh --------------------------------------------------------------------------


def test_services_deja_en_ligne_ne_sont_pas_relances(env: Env) -> None:
    env.already_running("ollama")
    env.already_running("comfyui")
    env.already_running("app", "<html><title>mangaka-team</title></html>")

    res = env.run(LAUNCH)

    assert res.returncode == 0, res.stdout + res.stderr
    assert env.calls_of("ollama") == []
    assert env.calls_of("comfyui") == []
    assert env.calls_of("npm") == []
    assert not list((env.state / "pids").glob("*.pid"))
    assert "déjà en ligne" in res.stdout
    assert env.wait_calls("xdg-open") == [f"http://localhost:{env.ports['app']}"]


def test_services_absents_sont_demarres_avec_la_commande_configuree(env: Env) -> None:
    res = env.run(LAUNCH)

    assert res.returncode == 0, res.stdout + res.stderr
    assert env.calls_of("ollama") == [f"serve OLLAMA_HOST=127.0.0.1:{env.ports['ollama']}"]
    assert env.calls_of("comfyui") == [f"{env.comfy_dir} main.py --listen 127.0.0.1 --port {env.ports['comfyui']}"]
    assert env.calls_of("npm") == [f"{ROOT} run dev PORT={env.ports['app']}"]
    for name in ("ollama", "comfyui", "app"):
        pid = env.pid(name)
        assert pid is not None and alive(pid), name
        assert (env.state / "logs" / f"{name}.log").exists()
    assert env.wait_calls("xdg-open") == [f"http://localhost:{env.ports['app']}"]

    # Deuxième clic : tout répond, rien n'est relancé.
    res = env.run(LAUNCH)
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(env.calls_of("ollama")) == 1
    assert len(env.calls_of("comfyui")) == 1
    assert len(env.calls_of("npm")) == 1

    pids = {name: env.pid(name) for name in ("ollama", "comfyui", "app")}
    res = env.run(STOP)
    assert res.returncode == 0, res.stdout + res.stderr
    for name, pid in pids.items():
        assert pid is not None and not alive(pid), name
    assert not list((env.state / "pids").glob("*.pid"))


def test_arguments_et_desactivation_depuis_launcher_env(env: Env, tmp_path: Path) -> None:
    conf = tmp_path / "launcher.env"
    conf.write_text(
        textwrap.dedent(
            """
            # commentaire
            COMFYUI_DIR=$HOME/ComfyUI
            COMFYUI_ARGS="--highvram --preview-method auto"
            START_OLLAMA=false
            """
        )
    )
    env.env.pop("COMFYUI_DIR")
    env.already_running("app", "mangaka-team")

    res = env.run(LAUNCH, "--no-browser", MANGAKA_LAUNCHER_ENV_FILES=str(conf))

    assert res.returncode == 0, res.stdout + res.stderr
    assert env.calls_of("ollama") == []
    assert env.calls_of("comfyui") == [
        f"{env.home}/ComfyUI main.py --listen 127.0.0.1 --port {env.ports['comfyui']} --highvram --preview-method auto"
    ]
    assert env.calls_of("xdg-open") == []


def test_delai_depasse_donne_une_erreur_et_le_journal(env: Env) -> None:
    env.already_running("comfyui")
    env.already_running("app", "mangaka-team")

    start = time.time()
    res = env.run(LAUNCH, OLLAMA_TIMEOUT="2", STUB_OLLAMA="hang")

    assert res.returncode == 1
    assert time.time() - start < 15
    log = env.state / "logs" / "ollama.log"
    assert log.exists()
    assert "pas de réponse après 2 s" in res.stdout
    assert str(log) in res.stdout
    notifications = "\n".join(env.calls_of("notify-send"))
    assert "échec de Ollama" in notifications
    assert str(log) in notifications
    # L'interface est en ligne : elle s'ouvre quand même (ComfyUI/Ollama hors ligne y sont signalés).
    assert env.wait_calls("xdg-open")


def test_service_qui_plante_au_demarrage_echoue_sans_attendre(env: Env) -> None:
    env.already_running("ollama")
    env.already_running("app", "mangaka-team")

    start = time.time()
    res = env.run(LAUNCH, COMFYUI_TIMEOUT="30", STUB_COMFYUI="crash")

    assert res.returncode == 1
    assert time.time() - start < 15
    assert "s'est arrêté au démarrage" in res.stdout
    log = env.state / "logs" / "comfyui.log"
    assert "plantage simulé" in log.read_text()
    assert str(log) in "\n".join(env.calls_of("notify-send"))


def test_port_occupe_par_un_autre_programme(env: Env) -> None:
    env.already_running("ollama")
    env.already_running("comfyui")
    env.already_running("app", "<title>autre chose</title>")

    res = env.run(LAUNCH)

    assert res.returncode == 1
    assert f"le port {env.ports['app']} est occupé par un autre programme" in res.stdout
    assert env.calls_of("npm") == []
    assert env.calls_of("xdg-open") == []
    assert "app.log" in "\n".join(env.calls_of("notify-send"))


def test_comfyui_introuvable(env: Env) -> None:
    env.already_running("ollama")
    env.already_running("app", "mangaka-team")

    res = env.run(LAUNCH, COMFYUI_DIR=str(env.tmp / "absent"))

    assert res.returncode == 1
    assert "main.py introuvable" in res.stdout
    assert env.calls_of("comfyui") == []


# --- stop.sh ----------------------------------------------------------------------------


def test_stop_n_arrete_que_ce_que_le_lanceur_a_demarre(env: Env) -> None:
    external = env.external_process("comfyui")
    env.already_running("app", "mangaka-team")

    res = env.run(LAUNCH)
    assert res.returncode == 0, res.stdout + res.stderr
    assert env.calls_of("comfyui") == []
    ollama_pid = env.pid("ollama")
    assert ollama_pid is not None and alive(ollama_pid)
    assert env.pid("comfyui") is None

    res = env.run(STOP)

    assert res.returncode == 0, res.stdout + res.stderr
    assert not alive(ollama_pid)
    assert external.poll() is None, "le ComfyUI qui tournait déjà a été arrêté"
    assert "comfyui : rien à arrêter" in res.stdout


def test_stop_ignore_un_pid_reutilise_par_un_autre_programme(env: Env) -> None:
    external = env.external_process("comfyui")
    pids = env.state / "pids"
    pids.mkdir(parents=True)
    # Même PID, mais date de démarrage différente : ce n'est pas le processus du lanceur.
    (pids / "comfyui.pid").write_text(f"{external.pid} 1\n")

    res = env.run(STOP)

    assert res.returncode == 0, res.stdout + res.stderr
    assert external.poll() is None
    assert not (pids / "comfyui.pid").exists()


def test_stop_sans_rien_a_arreter(env: Env) -> None:
    res = env.run(STOP)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Rien à arrêter" in res.stdout


# --- install-desktop.sh -----------------------------------------------------------------


def desktop_env(env: Env) -> dict[str, str]:
    config = env.home / ".config"
    config.mkdir(exist_ok=True)
    (config / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Bureau"\n')
    return {"XDG_CONFIG_HOME": str(config), "XDG_DATA_HOME": str(env.home / ".local" / "share")}


def validate(path: Path) -> None:
    if shutil.which("desktop-file-validate"):
        res = subprocess.run(["desktop-file-validate", str(path)], capture_output=True, text=True)
        assert res.returncode == 0, res.stdout + res.stderr


def test_install_desktop_cree_les_deux_copies_sans_doublon(env: Env) -> None:
    extra = desktop_env(env)
    apps = env.home / ".local" / "share" / "applications"
    desk = env.home / "Bureau"

    res = env.run(INSTALL, **extra)
    assert res.returncode == 0, res.stdout + res.stderr

    menu, bureau = apps / "mangaka-team.desktop", desk / "mangaka-team.desktop"
    assert menu.exists() and bureau.exists()
    content = menu.read_text()
    assert bureau.read_text() == content
    assert "Name=Mangaka Team\n" in content
    assert "Terminal=false\n" in content
    assert f'Exec="{ROOT}/scripts/launch.sh"\n' in content
    assert f"Icon={ROOT}/assets/icon/mangaka-team-512.png\n" in content
    assert "[Desktop Action arreter]\nName=Arrêter\n" in content
    assert f'Exec="{ROOT}/scripts/stop.sh"\n' in content
    assert os.access(bureau, os.X_OK)
    validate(menu)
    assert f"set {bureau} metadata::trusted true" in env.calls_of("gio")

    res = env.run(INSTALL, **extra)
    assert res.returncode == 0, res.stdout + res.stderr
    assert sorted(p.name for p in apps.glob("*.desktop")) == ["mangaka-team.desktop"]
    assert sorted(p.name for p in desk.iterdir()) == ["mangaka-team.desktop"]
    assert menu.read_text() == content

    res = env.run(INSTALL, "--uninstall", **extra)
    assert res.returncode == 0, res.stdout + res.stderr
    assert not menu.exists() and not bureau.exists()


def test_install_desktop_chemin_avec_espaces_et_caracteres_speciaux(env: Env) -> None:
    repo = env.tmp / 'mon dépôt "$x"'
    shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copytree(ROOT / "assets", repo / "assets")
    extra = desktop_env(env)

    res = subprocess.run(
        ["bash", str(repo / "scripts" / "install-desktop.sh")],
        env={**env.env, **extra},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert res.returncode == 0, res.stdout + res.stderr
    menu = env.home / ".local" / "share" / "applications" / "mangaka-team.desktop"
    validate(menu)
    assert 'Exec="' + str(repo).replace('"', '\\\\"').replace("$", "\\\\$") + '/scripts/launch.sh"' in menu.read_text()
