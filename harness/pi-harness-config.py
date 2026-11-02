"""Configuration centralisée, lue depuis l'environnement (jamais de secret en dur).

Le harness charge automatiquement ~/.pi-harness.env au démarrage (format
KEY=VALUE, lignes `export` acceptées) : plus besoin de sourcer le fichier
manuellement — les variables déjà présentes dans l'environnement ne sont
jamais écrasées.
"""
import os
from pathlib import Path


def load_env_file(path: Path) -> None:
    """Mini-loader dotenv en stdlib. Sert surtout à reprendre la clé Mistral
    déjà présente sur le serveur sans jamais l'afficher ni la copier."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export").strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


class Config:
    """Toutes les options se surchargent par variables d'environnement."""

    def __init__(self) -> None:
        # Charger ~/.pi-harness.env avant de lire les variables.
        load_env_file(Path.home() / ".pi-harness.env")

        # --- API Mistral (étape 1 : le modèle nu) ---
        self.api_key: str = os.environ.get("MISTRAL_API_KEY", "")
        self.api_url: str = os.environ.get(
            "MISTRAL_API_URL", "https://api.mistral.ai/v1/chat/completions"
        )
        self.model: str = os.environ.get("HARNESS_MODEL", "mistral-small-latest")
        self.summary_model: str = os.environ.get(
            "HARNESS_SUMMARY_MODEL", "open-mistral-nemo"
        )
        self.temperature: float = float(os.environ.get("HARNESS_TEMPERATURE", "0.2"))

        # --- Espace de travail du harness ---
        base = Path(os.environ.get("HARNESS_HOME", str(Path.home() / ".pi-harness")))
        self.home: Path = base
        self.conversations_dir: Path = base / "conversations"
        self.log_file: Path = base / "harness.log"

        # --- Gardes-fous (étape 5) ---
        self.max_tool_calls: int = int(os.environ.get("HARNESS_MAX_TOOL_CALLS", "15"))
        # Commandes autorisées : whitelist stricte, tout le reste est refusé.
        self.allowed_commands: list[str] = [
            w.strip()
            for w in os.environ.get(
                "HARNESS_ALLOWED_COMMANDS",
                "ls,cat,head,tail,grep,find,du,df,free,uptime,uname,whoami,"
                "systemctl status,docker ps,docker logs,docker stats,"
                "pg_isready,psql,git status,git log,git diff,python3 --version",
            ).split(",")
            if w.strip()
        ]
        # Commandes qui demandent une confirmation interactive avant exécution.
        self.confirm_patterns: list[str] = [
            w.strip()
            for w in os.environ.get(
                "HARNESS_CONFIRM_COMMANDS", "rm,mv,systemctl restart,docker restart"
            ).split(",")
            if w.strip()
        ]
        # Fichiers/répertoires jamais lisibles ni modifiables par l'agent.
        self.blocked_paths: list[str] = [
            p.strip()
            for p in os.environ.get(
                "HARNESS_BLOCKED_PATHS",
                ".env,id_rsa,id_ed25519,shadow,sudoers,authorized_keys,"
                "known_hosts,.git-credentials,.ssh,.gnupg",
            ).split(",")
            if p.strip()
        ]
        # Racine autorisée pour read_file / write_file.
        self.files_root: Path = Path(
            os.environ.get("HARNESS_FILES_ROOT", "/")
        ).resolve()

        # --- Contexte géré (étape 8) ---
        self.max_context_messages: int = int(
            os.environ.get("HARNESS_MAX_CONTEXT_MESSAGES", "30")
        )
        # Budget approximatif en caractères (4 chars ~ 1 token) avant compaction.
        self.max_context_chars: int = int(
            os.environ.get("HARNESS_MAX_CONTEXT_CHARS", "48000")
        )

        # --- Rappels (étape 7) : fichier AGENTS.md rechargé à chaque tour ---
        self.reminders_file: Path = Path(
            os.environ.get("HARNESS_REMINDERS_FILE", "AGENTS.md")
        )

        # --- Divers ---
        self.request_timeout: int = int(os.environ.get("HARNESS_TIMEOUT", "120"))

        for d in (self.home, self.conversations_dir):
            d.mkdir(parents=True, exist_ok=True)
