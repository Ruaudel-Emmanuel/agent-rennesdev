# 🤖 Agent RennesDev - Interface Web pour VPS

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Agent RennesDev** est une interface web moderne pour interagir avec ton VPS **sans SSH**, directement depuis un navigateur. Elle remplace PuTTY et permet d'exécuter des commandes, lire des fichiers, uploader des documents, et gérer des conversations avec un assistant intelligent.

---

## 🌟 Fonctionnalités

✅ **Interface conversationnelle** - Parle naturellement avec ton VPS
✅ **Exécution de commandes** - Commandes autorisées (ls, cat, date, etc.)
✅ **Lecture de fichiers** - Affiche le contenu des fichiers directement
✅ **Upload de fichiers** - Envoie des fichiers .txt, .md, etc.
✅ **Historique des conversations** - Retrouve tes anciennes discussions
✅ **Nouvelle discussion** - Bouton pour réinitialiser la conversation
✅ **Documentation OpenAPI** - Swagger UI à `/docs`
✅ **Sécurité** - Liste blanche des commandes autorisées

---

## 📸 Aperçu

*(À ajouter : captures d'écran de l'interface)*

---

## 🚀 Installation

### Prérequis

- **VPS** avec Ubuntu 22.04/24.04 ou Debian
- **Python 3.8+**
- **Domain** pointant vers ton VPS (ex: `agent.rennesdev.fr`)
- **Cloudflare** (optionnel, pour le proxy)

### Installation rapide

#### 1️⃣ Cloner le dépôt
```bash
git clone https://github.com/Ruaudel-Emmanuel/agent-rennesdev.git
cd agent-rennesdev
```

#### 2️⃣ Installer les dépendances
```bash
# Installer Python et pip
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# Créer un environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r backend/requirements.txt
```

#### 3️⃣ Configurer FastAPI
```bash
# Tester localement
cd backend
uvicorn main:app --host 0.0.0.0 --port 5000 --workers 4
```

#### 4️⃣ Configurer Caddy (Reverse Proxy)
```bash
# Copier la configuration Caddy
sudo cp configs/caddy/Caddyfile /etc/caddy/Caddyfile

# Redémarrer Caddy
sudo systemctl restart caddy
```

#### 5️⃣ Configurer le service systemd
```bash
# Copier le service
sudo cp configs/systemd/communication-web.service /etc/systemd/system/

# Recharger et démarrer
sudo systemctl daemon-reload
sudo systemctl enable communication-web
sudo systemctl start communication-web
```

#### 6️⃣ Créer les dossiers nécessaires
```bash
sudo mkdir -p /home/ubuntu/{uploads,communication-web/conversations}
sudo chown -R ubuntu:ubuntu /home/ubuntu/{uploads,communication-web}
```

---

## 📂 Structure du projet

```
agent-rennesdev/
├── backend/
│   ├── main.py            # Backend FastAPI
│   └── requirements.txt   # Dépendances Python
├── frontend/
│   └── templates/
│       └── index.html     # Interface web
├── configs/
│   ├── caddy/
│   │   └── Caddyfile      # Configuration Caddy
│   └── systemd/
│       └── communication-web.service
├── scripts/
│   └── setup.sh           # Script d'installation
├── README.md              # Documentation
└── LICENSE                # Licence MIT
```

---

## 🛠 Configuration

### Variables d'environnement

| Variable | Description | Valeur par défaut |
|----------|-------------|-------------------|
| `UPLOAD_FOLDER` | Dossier pour les uploads | `/home/ubuntu/uploads` |
| `CONVERSATIONS_FOLDER` | Dossier pour l'historique | `/home/ubuntu/communication-web/conversations` |

### Commandes autorisées

Les commandes sont définies dans `backend/main.py` :
```python
ALLOWED_COMMANDS = [
    'date', 'whoami', 'pwd', 'ls', 'cat', 'head', 'tail', 'grep', 'echo',
    'kopia', 'tailscale', 'docker', 'systemctl', 'curl', 'ping', 'netstat',
    'df', 'free', 'uname', 'uptime', 'w', 'ps', 'ss', 'dig', 'nslookup',
    'journalctl', 'service', 'nginx', 'caddy', 'fail2ban', 'ufw'
]
```

### Commandes interdites

Les motifs interdits sont définis dans `FORBIDDEN_PATTERNS` :
```python
FORBIDDEN_PATTERNS = [
    r'rm\s+', r'mv\s+', r'chmod\s+', r'chown\s+', r'dd\s+',
    r'format\s+', r'mkfs\s+', r'fdisk\s+', r'parted\s+',
    r'apt\s+', r'yum\s+', r'dnf\s+', r'pip\s+', r'wget\s+'
]
```

---

## 🌐 Utilisation

### Démarrer l'interface
1. **Accède à** : `https://agent.rennesdev.fr`
2. **Tape un message** :
   - *"Bonjour !"*
   - *"Lis ORDRES.md"*
   - *"Quelle heure est-il ?"*
   - *"Exécute tailscale status"*
3. **Upload un fichier** : Utilise le bouton **📁 Uploader**

### Endpoints API

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/` | GET | Page d'accueil |
| `/send_message` | POST | Envoyer un message |
| `/upload` | POST | Uploader un fichier |
| `/new_conversation` | POST | Démarrer une nouvelle conversation |
| `/list_conversations` | GET | Lister les conversations |
| `/load_conversation/{id}` | POST | Charger une conversation |
| `/docs` | GET | Documentation Swagger UI |

---

## 🔒 Sécurité

- **Liste blanche des commandes** : Seules les commandes autorisées sont exécutées.
- **Dossiers restreints** : Accès limité à `/home/ubuntu/`, `/etc/caddy/`, etc.
- **Pas de commandes dangereuses** : `rm`, `mv`, `apt`, etc. sont bloquées.
- **HTTPS** : Chiffrement via Caddy + Let's Encrypt.

---

## 📜 Licence

Ce projet est sous licence **MIT** - voir le fichier [LICENSE](LICENSE) pour plus de détails.

---

## 🤝 Contribution

Les contributions sont les bienvenues ! Ouvre une **Pull Request** ou un **Issue** sur GitHub.

---

## 📧 Contact

- **Auteur** : Ruaudel Emmanuel
- **Site** : [rennesdev.fr](https://rennesdev.fr)
