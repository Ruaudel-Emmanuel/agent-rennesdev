from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os
import subprocess
import shlex
import re
import json
import httpx
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Agent RennesDev API", description="Interface conversationnelle du VPS rennesdev.fr — remplace PuTTY")

# --- Dossiers --------------------------------------------------------------
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/home/ubuntu/uploads")
CONVERSATIONS_FOLDER = os.getenv("CONVERSATIONS_FOLDER", "/home/ubuntu/communication-web/conversations")
TEMPLATES_FOLDER = os.getenv("TEMPLATES_FOLDER", "/home/ubuntu/communication-web/templates")
STATIC_FOLDER = os.getenv("STATIC_FOLDER", "/home/ubuntu/communication-web/static")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERSATIONS_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_FOLDER), name="static")

# --- Sécurité & agent IA ---------------------------------------------------
# Token d'accès : si défini dans le .env, tous les endpoints (sauf / et /docs)
# exigent l'en-tête X-Agent-Token. FORTEMENT recommandé en production.
AGENT_AUTH_TOKEN = os.getenv("AGENT_AUTH_TOKEN")

# API Mistral : si la clé est absente, l'agent retombe sur le mode mots-clés.
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "30"))
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "30"))

SYSTEM_PROMPT = (
    "Tu es Pi Agent, l'assistant d'administration du VPS rennesdev.fr. "
    "Tu remplaces PuTTY : l'utilisateur te parle en français et tu pilotes le serveur. "
    "Utilise l'outil execute_command quand une action système est nécessaire, "
    "puis explique le résultat de façon concise et opérationnelle. "
    "Ne jamais demander à l'utilisateur d'ouvrir un terminal : c'est toi l'interface."
)

class MessageRequest(BaseModel):
    message: str

# --- Whitelist des commandes ----------------------------------------------
ALLOWED_COMMANDS = [
    'date', 'whoami', 'pwd', 'ls', 'cat', 'head', 'tail', 'grep', 'echo',
    'kopia', 'tailscale', 'df', 'free', 'uname', 'uptime', 'w', 'ps',
    'ss', 'dig', 'nslookup', 'journalctl', 'fail2ban-client', 'ping'
]
# NOTE sécurité : docker, systemctl, curl, service, nginx, caddy, ufw
# retirés de la whitelist (pouvoir quasi-root ou SSRF). À réintroduire
# un par un avec des sous-commandes précises si besoin.

FORBIDDEN_PATTERNS = [
    r'rm\s+', r'mv\s+', r'chmod\s+', r'chown\s+', r'dd\s+',
    r'mkfs\s+', r'fdisk\s+', r'parted\s+', r'apt\s+', r'yum\s+', r'dnf\s+', r'pip\s+',
    r'wget\s+', r'curl\s', r'\|\s*sh', r';', r'&&', r'\|\|', r'\x60', r'\$\(',
    r'kill\s+', r'pkill\s+', r'killall\s+', r'reboot', r'shutdown',
    r'nano\s+', r'vim\s+', r'emacs\s+', r'sed\s+-i',
    r'\.env\b', r'id_rsa', r'authorized_keys', r'shadow'
]

ALLOWED_DIRS = [
    '/home/ubuntu/',
    '/etc/caddy/',
    '/opt/monitoring/',
    '/var/log/'
]

# --- Middleware : auth + ID de conversation --------------------------------
PUBLIC_PATHS = ("/", "/docs", "/openapi.json", "/redoc", "/favicon.ico")

@app.middleware("http")
async def security_and_conversation_middleware(request: Request, call_next):
    # Authentification par token (si configurée)
    if AGENT_AUTH_TOKEN:
        path = request.url.path
        if path not in PUBLIC_PATHS and not path.startswith("/static"):
            if request.headers.get("x-agent-token") != AGENT_AUTH_TOKEN:
                return JSONResponse({"error": "unauthorized"}, status_code=401)

    # ID de conversation persisté dans un cookie
    conv_id = request.cookies.get("conversation_id") or str(uuid.uuid4())
    request.state.conversation_id = conv_id
    response = await call_next(request)
    response.set_cookie(key="conversation_id", value=conv_id, httponly=True, max_age=3600 * 24 * 30)
    return response

def get_conversation_id(request: Request) -> str:
    return request.state.conversation_id

# --- Persistance des conversations (suivi type Vibe) ------------------------
# Structure : { "title", "started_at", "updated_at", "messages": [...] }
# Message : { "timestamp", "role": user|assistant|action, "content", "status" }
# Action  : { "timestamp", "role": "action", "action", "result", "status" }

def get_conversation_file(conv_id: str) -> str:
    return os.path.join(CONVERSATIONS_FOLDER, conv_id + ".json")

def load_conversation(conv_id: str) -> Dict[str, Any]:
    try:
        with open(get_conversation_file(conv_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"title": None, "messages": [], "started_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat()}

def save_conversation(conv_id: str, conversation: Dict[str, Any]):
    conversation["updated_at"] = datetime.now().isoformat()
    with open(get_conversation_file(conv_id), "w", encoding="utf-8") as f:
        json.dump(conversation, f, indent=2, ensure_ascii=False)

def add_message_to_conversation(conv_id: str, role: str, content: str, **extra):
    conversation = load_conversation(conv_id)
    entry = {"timestamp": datetime.now().isoformat(), "role": role, "content": content, "status": "done"}
    entry.update(extra)
    conversation["messages"].append(entry)
    # Titre automatique : premier message utilisateur, tronqué
    if role == "user" and not conversation.get("title"):
        conversation["title"] = content[:60] + ("..." if len(content) > 60 else "")
    save_conversation(conv_id, conversation)

def record_action(conv_id: str, action: str, result: str, status: str):
    """Traçabilité type Vibe : chaque action de l'agent est enregistrée
    dans la conversation et affichable sous la réponse (fait / refusé)."""
    conversation = load_conversation(conv_id)
    conversation["messages"].append({
        "timestamp": datetime.now().isoformat(),
        "role": "action",
        "action": action,
        "result": result[:4000],
        "status": status,
        "content": "[" + status + "] " + action
    })
    save_conversation(conv_id, conversation)

def get_all_conversations() -> List[Dict[str, Any]]:
    conversations = []
    if not os.path.isdir(CONVERSATIONS_FOLDER):
        return conversations
    for filename in os.listdir(CONVERSATIONS_FOLDER):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(CONVERSATIONS_FOLDER, filename), "r", encoding="utf-8") as f:
                conv = json.load(f)
            msgs = conv.get("messages", [])
            last_text = ""
            for m in reversed(msgs):
                if m.get("role") in ("user", "assistant") and m.get("content"):
                    last_text = m["content"]
                    break
            conversations.append({
                "id": filename[:-5],
                "title": conv.get("title") or (msgs[0]["content"][:60] if msgs else "Conversation"),
                "started_at": conv.get("started_at", ""),
                "updated_at": conv.get("updated_at", conv.get("started_at", "")),
                "message_count": len(msgs),
                "last_message": last_text[:80] + ("..." if len(last_text) > 80 else "")
            })
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return sorted(conversations, key=lambda x: x.get("updated_at", ""), reverse=True)

# --- Validation et exécution des commandes ----------------------------------
def is_command_allowed(command: str) -> bool:
    tokens = command.split()
    if not tokens or tokens[0] not in ALLOWED_COMMANDS:
        return False
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False
    if tokens[0] in ("cat", "ls", "head", "tail", "grep"):
        for arg in tokens[1:]:
            if arg.startswith("/") and not any(arg.startswith(d) for d in ALLOWED_DIRS):
                return False
    return True

def execute_command(command: str) -> str:
    """Exécute une commande de la whitelist. shlex + liste d'arguments :
    aucune injection possible via ; && || $(...) ou backticks."""
    try:
        args = shlex.split(command)
        if not args:
            return "Erreur : commande vide."
        result = subprocess.run(
            args, capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT, cwd="/home/ubuntu"
        )
        if result.returncode != 0:
            return "Erreur (code " + str(result.returncode) + ") :\n" + result.stderr
        return result.stdout if result.stdout else "Commande exécutée avec succès."
    except subprocess.TimeoutExpired:
        return "Erreur : timeout (" + str(COMMAND_TIMEOUT) + "s dépassées)."
    except Exception as e:
        return "Erreur : " + str(e)

# --- Agent Mistral (tool-calling) --------------------------------------------
TOOLS = [{
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": "Exécute une commande autorisée sur le VPS rennesdev.fr "
                       "(liste blanche : " + ", ".join(ALLOWED_COMMANDS) + ").",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "La commande à exécuter, ex: 'df -h'"}},
            "required": ["command"]
        }
    }
}]

def mistral_history(conv_id: str) -> List[Dict[str, str]]:
    conv = load_conversation(conv_id)
    history = []
    for m in conv.get("messages", []):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            history.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]})
    return history[-MAX_HISTORY_MESSAGES:]

def ask_mistral(conv_id: str, user_message: str) -> str:
    """Boucle d'agent : Mistral décide d'exécuter des commandes (via la whitelist),
    puis rédige la réponse finale. Chaque action est tracée dans la conversation."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + mistral_history(conv_id)
    messages.append({"role": "user", "content": user_message})

    with httpx.Client(timeout=90) as client:
        for _ in range(4):  # max 4 tours d'outils par message
            resp = client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": "Bearer " + MISTRAL_API_KEY},
                json={"model": MISTRAL_MODEL, "messages": messages, "tools": TOOLS},
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content") or "Je n'ai pas de réponse à te proposer."

            messages.append(msg)
            for tc in tool_calls:
                try:
                    cmd = json.loads(tc["function"]["arguments"]).get("command", "").strip()
                except json.JSONDecodeError:
                    cmd = ""
                if cmd and is_command_allowed(cmd):
                    output = execute_command(cmd)
                    record_action(conv_id, cmd, output, "done")
                else:
                    output = "Commande non autorisée (whitelist) : " + cmd
                    record_action(conv_id, cmd, output, "refused")
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": output[:4000]})

    return "Trop d'appels d'outils pour ce message — reformule ta demande."

# --- Traitement d'un message -------------------------------------------------
def process_message(conv_id: str, user_message: str) -> str:
    add_message_to_conversation(conv_id, "user", user_message)

    # 1. Commande directe autorisée (sans LLM, réponse immédiate)
    if is_command_allowed(user_message):
        response = execute_command(user_message)
        record_action(conv_id, user_message, response, "done")

    # 2. Agent IA (Mistral + tool-calling)
    elif MISTRAL_API_KEY:
        try:
            response = ask_mistral(conv_id, user_message)
        except Exception as e:
            response = "Erreur de l'agent IA : " + str(e)

    # 3. Fallback sans LLM (mode mots-clés historique)
    else:
        low = user_message.lower()
        if low in ("bonjour", "salut", "hello", "coucou"):
            response = "Bonjour ! Je suis Pi Agent sur le VPS rennesdev.fr. Comment puis-je t'aider ?"
        elif "aide" in low or "help" in low:
            response = ("Je peux lire des fichiers, exécuter des commandes autorisées "
                        "('df -h', 'uptime', 'tailscale status')… Sans clé MISTRAL_API_KEY, "
                        "je fonctionne en mode commandes directes uniquement.")
        else:
            response = ("Commande non reconnue et agent IA non configuré. "
                        "Ajoute MISTRAL_API_KEY dans le .env pour activer le mode conversationnel complet.")

    add_message_to_conversation(conv_id, "assistant", response)
    return response

# --- Routes -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        with open(os.path.join(TEMPLATES_FOLDER, "index.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Erreur : index.html introuvable</h1>", status_code=404)

@app.post("/send_message")
async def send_message(request: Request, message_request: MessageRequest):
    conv_id = get_conversation_id(request)
    response = process_message(conv_id, message_request.message)
    return JSONResponse({"response": response, "conversation_id": conv_id})

@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    conv_id = get_conversation_id(request)
    # Nom de fichier assaini : aucun path traversal possible
    safe_name = os.path.basename(file.filename or "sans-nom")
    filepath = os.path.join(UPLOAD_FOLDER, safe_name)
    with open(filepath, "wb") as buffer:
        buffer.write(await file.read())
    msg = "Fichier " + safe_name + " uploadé avec succès !"
    add_message_to_conversation(conv_id, "user", "[Upload] " + safe_name)
    add_message_to_conversation(conv_id, "assistant", msg)
    return JSONResponse({"message": msg, "filename": safe_name})

@app.post("/new_conversation")
async def new_conversation(request: Request):
    new_id = str(uuid.uuid4())
    response = JSONResponse({"status": "ok", "conversation_id": new_id})
    response.set_cookie(key="conversation_id", value=new_id, httponly=True, max_age=3600 * 24 * 30)
    return response

@app.get("/list_conversations")
async def list_conversations():
    return JSONResponse({"conversations": get_all_conversations()})

@app.get("/conversation/{conv_id}")
async def get_conversation(conv_id: str):
    """Fil complet d'une conversation (messages + actions tracées)."""
    conv_file = get_conversation_file(conv_id)
    try:
        with open(conv_file, "r", encoding="utf-8") as f:
            conv = json.load(f)
        return JSONResponse({
            "status": "ok", "id": conv_id, "title": conv.get("title"),
            "started_at": conv.get("started_at"), "updated_at": conv.get("updated_at"),
            "messages": conv.get("messages", [])
        })
    except (FileNotFoundError, json.JSONDecodeError):
        return JSONResponse({"status": "error", "message": "Conversation introuvable."}, status_code=404)

@app.post("/load_conversation/{conv_id}")
async def load_conversation_route(conv_id: str, request: Request):
    """Compatibilité avec le front existant : charge et active une conversation."""
    result = await get_conversation(conv_id)
    if result.status_code == 200:
        response = JSONResponse(json.loads(result.body), status_code=200)
        response.set_cookie(key="conversation_id", value=conv_id, httponly=True, max_age=3600 * 24 * 30)
        return response
    return result

@app.get("/uploads/{filename}")
async def uploaded_file(filename: str):
    # realpath + basename : aucun accès hors du dossier uploads
    safe_name = os.path.basename(filename)
    filepath = os.path.realpath(os.path.join(UPLOAD_FOLDER, safe_name))
    uploads_root = os.path.realpath(UPLOAD_FOLDER) + os.sep
    if not filepath.startswith(uploads_root):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return FileResponse(filepath)
