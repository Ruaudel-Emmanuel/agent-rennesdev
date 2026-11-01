from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os
import subprocess
import secrets
import re
import json
from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel
import uuid

app = FastAPI(title="Agent RennesDev API", description="Backend pour l'interface web de communication avec le VPS")

# Dossiers
UPLOAD_FOLDER = '/home/ubuntu/uploads'
CONVERSATIONS_FOLDER = '/home/ubuntu/communication-web/conversations'
TEMPLATES_FOLDER = '/home/ubuntu/communication-web/templates'
STATIC_FOLDER = '/home/ubuntu/communication-web/static'

# Créer les dossiers si ils n'existent pas
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERSATIONS_FOLDER, exist_ok=True)

# Montage des fichiers statiques
app.mount("/static", StaticFiles(directory=STATIC_FOLDER), name="static")

# Modèles Pydantic
class MessageRequest(BaseModel):
    message: str

class ConversationRequest(BaseModel):
    id: str

# Liste blanche des commandes autorisées
ALLOWED_COMMANDS = [
    'date', 'whoami', 'pwd', 'ls', 'cat', 'head', 'tail', 'grep', 'echo',
    'kopia', 'tailscale', 'docker', 'systemctl', 'curl', 'ping', 'netstat',
    'df', 'free', 'uname', 'uptime', 'w', 'ps', 'ss', 'dig', 'nslookup',
    'journalctl', 'service', 'nginx', 'caddy', 'fail2ban', 'ufw'
]

# Commandes interdites
FORBIDDEN_PATTERNS = [
    r'rm\s+', r'mv\s+', r'chmod\s+', r'chown\s+', r'dd\s+',
    r'format\s+', r'mkfs\s+', r'fdisk\s+', r'parted\s+',
    r'apt\s+', r'yum\s+', r'dnf\s+', r'pip\s+',
    r'wget\s+', r'curl.*--output', r'\|\s*sh', r';\s*rm',
    r'kill\s+', r'pkill\s+', r'killall\s+', r'reboot', r'shutdown',
    r'nano\s+', r'vim\s+', r'vi\s+', r'emacs\s+', r'sed\s+-i'
]

# Dossiers autorisés
ALLOWED_DIRS = [
    '/home/ubuntu/',
    '/home/ubuntu/uploads/',
    '/home/ubuntu/projects/',
    '/home/ubuntu/communication-web/',
    '/etc/caddy/',
    '/opt/monitoring/',
    '/var/log/'
]

# Session simulation (FastAPI n'a pas de session native comme Flask)
# On utilise des cookies ou des headers pour gérer les conversations
# Pour simplifier, on va utiliser un cookie pour stocker l'ID de conversation

@app.middleware("http")
async def add_conversation_id(request: Request, call_next):
    """Ajoute un ID de conversation si ce n'est pas déjà fait."""
    conv_id = request.cookies.get("conversation_id")
    if not conv_id:
        conv_id = str(uuid.uuid4())
    response = await call_next(request)
    response.set_cookie(key="conversation_id", value=conv_id, httponly=True, max_age=3600*24*30)
    return response

def get_conversation_id(request: Request) -> str:
    """Récupère l'ID de conversation depuis les cookies."""
    return request.cookies.get("conversation_id", str(uuid.uuid4()))

def get_conversation_file(conv_id: str) -> str:
    """Récupère le fichier de la conversation."""
    return os.path.join(CONVERSATIONS_FOLDER, f"{conv_id}.json")

def load_conversation(conv_id: str) -> Dict[str, Any]:
    """Charge une conversation."""
    conv_file = get_conversation_file(conv_id)
    try:
        with open(conv_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"messages": [], "started_at": datetime.now().isoformat()}

def save_conversation(conv_id: str, conversation: Dict[str, Any]):
    """Sauvegarde une conversation."""
    conv_file = get_conversation_file(conv_id)
    with open(conv_file, 'w', encoding='utf-8') as f:
        json.dump(conversation, f, indent=2, ensure_ascii=False)

def add_message_to_conversation(conv_id: str, role: str, content: str):
    """Ajoute un message à une conversation."""
    conversation = load_conversation(conv_id)
    conversation["messages"].append({
        "timestamp": datetime.now().isoformat(),
        "role": role,
        "content": content
    })
    save_conversation(conv_id, conversation)

def get_all_conversations() -> List[Dict[str, Any]]:
    """Récupère la liste de toutes les conversations."""
    conversations = []
    for filename in os.listdir(CONVERSATIONS_FOLDER):
        if filename.endswith('.json'):
            try:
                with open(os.path.join(CONVERSATIONS_FOLDER, filename), 'r', encoding='utf-8') as f:
                    conv = json.load(f)
                conversations.append({
                    "id": filename.replace('.json', ''),
                    "started_at": conv.get("started_at", ""),
                    "last_message": conv["messages"][-1]["content"][:50] + "..." if conv["messages"] else ""
                })
            except (json.JSONDecodeError, IndexError):
                continue
    return sorted(conversations, key=lambda x: x["started_at"], reverse=True)

def is_command_allowed(command: str) -> bool:
    """Vérifie si une commande est autorisée."""
    cmd_parts = command.split()[0] if command.split() else ''
    if cmd_parts not in ALLOWED_COMMANDS:
        return False
    
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False
    
    if cmd_parts in ['cat', 'ls', 'head', 'tail', 'grep', 'rm', 'mv', 'cp']:
        for arg in command.split()[1:]:
            if arg.startswith('/'):
                allowed = False
                for allowed_dir in ALLOWED_DIRS:
                    if arg.startswith(allowed_dir):
                        allowed = True
                        break
                if not allowed:
                    return False
    
    return True

def execute_command(command: str) -> str:
    """Exécute une commande autorisée et retourne le résultat."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd='/home/ubuntu'
        )
        if result.returncode != 0:
            return f"Erreur (code {result.returncode}) :\n{result.stderr}"
        return result.stdout if result.stdout else "Commande exécutée avec succès."
    except subprocess.TimeoutExpired:
        return "Erreur : Timeout (30 secondes dépassées)."
    except Exception as e:
        return f"Erreur : {str(e)}"

def process_message(conv_id: str, user_message: str) -> str:
    """Traite un message utilisateur et retourne une réponse."""
    user_message_lower = user_message.lower()
    
    # Salutations
    if user_message_lower in ['bonjour', 'salut', 'hello', 'hi', 'hey', 'coucou']:
        response = "Bonjour ! Je suis ton assistant sur le VPS rennesdev.fr. Comment puis-je t'aider aujourd'hui ? 😊"
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Au revoir
    if user_message_lower in ['au revoir', 'bye', 'à plus', 'à bientôt', 'merci', 'ok merci', 'merci beaucoup']:
        response = "De rien ! À bientôt ! 👋"
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Qui suis-je / Qui es-tu
    if user_message_lower in ['qui suis-je ?', 'qui es-tu ?', 'qui es tu ?', 'tu es qui ?']:
        response = "Je suis ton assistant sur le VPS rennesdev.fr. Je peux exécuter des commandes autorisées, lire des fichiers, analyser des logs, ou t'aider à gérer ton infrastructure. Je suis là pour remplacer PuTTY et simplifier ta vie ! 🚀"
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Date / Heure
    if user_message_lower in ['quelle heure est-il ?', 'date', 'heure', 'quelle est la date ?', 'quelle date ?']:
        response = execute_command('date')
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Uptime
    if user_message_lower in ['uptime', 'depuis quand le serveur est-il allumé ?', 'temps de fonctionnement']:
        response = execute_command('uptime')
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Lire un fichier
    if re.match(r'^(lis|read|affiche|montre|ouvre|cat|afficher|voir)\s+', user_message_lower):
        file_path = re.sub(r'^(lis|read|affiche|montre|ouvre|cat|afficher|voir)\s+', '', user_message, flags=re.IGNORECASE).strip()
        if not file_path.startswith('/'):
            file_path = f'/home/ubuntu/{file_path}'
        
        allowed = False
        for allowed_dir in ALLOWED_DIRS:
            if file_path.startswith(allowed_dir):
                allowed = True
                break
        
        if not allowed:
            response = f"Erreur : Accès refusé au fichier {file_path} (dossier non autorisé)."
        elif os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                response = f"Contenu de {file_path} :\n\n```\n{content}\n```"
            except Exception as e:
                response = f"Erreur lors de la lecture de {file_path} : {str(e)}"
        else:
            base_dir = os.path.dirname(file_path)
            if os.path.isdir(base_dir):
                files = os.listdir(base_dir)
                suggestions = [f for f in files if f.lower() == os.path.basename(file_path).lower()]
                if suggestions:
                    response = f"Fichier introuvable : {file_path}\n\nDid you mean: {', '.join(suggestions)}?"
                else:
                    response = f"Fichier introuvable : {file_path}"
            else:
                response = f"Fichier introuvable : {file_path}"
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Exécuter une commande
    if user_message_lower.startswith('exécute ') or user_message_lower.startswith('execute ') or user_message_lower.startswith('lance '):
        command = user_message[len('exécute '):].strip()
        if is_command_allowed(command):
            response = execute_command(command)
        else:
            response = f"Commande non autorisée : {command.split()[0] if command.split() else command}."
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Commandes directes
    if is_command_allowed(user_message):
        response = execute_command(user_message)
        add_message_to_conversation(conv_id, "user", user_message)
        add_message_to_conversation(conv_id, "assistant", response)
        return response
    
    # Mode conversation naturel
    response = f"J'ai bien reçu ton message :\n\n**{user_message}**\n\n"
    
    if "problème" in user_message_lower or "erreur" in user_message_lower:
        response += "Je vais analyser ce problème. Peux-tu me donner plus de détails ?"
    elif "aide" in user_message_lower or "help" in user_message_lower:
        response += "Voici ce que je peux faire pour toi :\n"
        response += "- Lire des fichiers (ex: 'Lis ORDRES.md')\n"
        response += "- Exécuter des commandes autorisées (ex: 'date', 'tailscale status')\n"
        response += "- Uploader des fichiers\n"
        response += "- Répondre à tes questions\n"
    elif "fichier" in user_message_lower:
        response += "Tu veux que je lise ou modifie un fichier ? Donne-moi le chemin exact."
    elif "commande" in user_message_lower:
        response += "Tu veux exécuter une commande ? Dis-moi laquelle (ex: 'date', 'ls /home/ubuntu/')."
    else:
        response += "Je vais traiter ta demande. Si tu veux que j'exécute une action spécifique, précise-la (ex: 'Lis ORDRES.md', 'date', etc.)."
    
    add_message_to_conversation(conv_id, "user", user_message)
    add_message_to_conversation(conv_id, "assistant", response)
    return response

# Routes
@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        with open(os.path.join(TEMPLATES_FOLDER, "index.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Erreur : Fichier index.html introuvable</h1>", status_code=404)

@app.post("/send_message")
async def send_message(request: Request, message_request: MessageRequest):
    conv_id = get_conversation_id(request)
    response = process_message(conv_id, message_request.message)
    return JSONResponse(content={"response": response})

@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    conv_id = get_conversation_id(request)
    try:
        filepath = os.path.join(UPLOAD_FOLDER, file.filename)
        with open(filepath, "wb") as buffer:
            buffer.write(await file.read())
        response_msg = f"Fichier {file.filename} uploadé avec succès !"
        add_message_to_conversation(conv_id, "user", f"[Upload] {file.filename}")
        add_message_to_conversation(conv_id, "assistant", response_msg)
        return JSONResponse(content={"message": response_msg})
    except Exception as e:
        return JSONResponse(content={"error": f"Erreur lors de l'upload : {str(e)}"}, status_code=500)

@app.post("/new_conversation")
async def new_conversation(request: Request):
    response = JSONResponse(content={"status": "ok", "message": "Nouvelle conversation démarrée."})
    response.delete_cookie("conversation_id")
    return response

@app.get("/list_conversations")
async def list_conversations():
    return JSONResponse(content={"conversations": get_all_conversations()})

@app.post("/load_conversation/{conv_id}")
async def load_conversation_route(conv_id: str, request: Request):
    conv_file = get_conversation_file(conv_id)
    try:
        with open(conv_file, 'r', encoding='utf-8') as f:
            conv = json.load(f)
        response = JSONResponse(content={"status": "ok", "messages": conv.get("messages", [])})
        response.set_cookie(key="conversation_id", value=conv_id, httponly=True, max_age=3600*24*30)
        return response
    except (FileNotFoundError, json.JSONDecodeError):
        return JSONResponse(content={"status": "error", "message": "Conversation introuvable."}, status_code=404)

@app.get("/uploads/{filename}")
async def uploaded_file(filename: str):
    return FileResponse(os.path.join(UPLOAD_FOLDER, filename))

# Pour servir les fichiers statiques (CSS, JS) depuis /static
@app.get("/static/{path:path}")
async def serve_static(path: str):
    return FileResponse(os.path.join(STATIC_FOLDER, path))
