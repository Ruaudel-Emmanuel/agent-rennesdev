#!/bin/bash

# ============================================================
# Agent RennesDev - Script d'installation automatique
# ============================================================

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Vérifier que le script est exécuté en root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Erreur : Ce script doit être exécuté en tant que root (sudo).${NC}"
    exit 1
fi

# Afficher le titre
echo -e "${BLUE}
============================================
   🤖 Agent RennesDev - Installation
============================================${NC}\n"

# Mettre à jour le système
echo -e "${YELLOW}⏳ Mise à jour du système...${NC}"
apt update -qq && apt upgrade -y -qq > /dev/null 2>&1
echo -e "${GREEN}✅ Système à jour.${NC}\n"

# Installer les dépendances
echo -e "${YELLOW}⏳ Installation des dépendances...${NC}"
apt install -y -qq python3 python3-pip python3-venv curl git > /dev/null 2>&1
echo -e "${GREEN}✅ Dépendances installées.${NC}\n"

# Créer l'utilisateur ubuntu si nécessaire
if ! id -u ubuntu >/dev/null 2>&1; then
    echo -e "${YELLOW}⏳ Création de l'utilisateur 'ubuntu'...${NC}"
    useradd -m -s /bin/bash ubuntu
    echo -e "${GREEN}✅ Utilisateur 'ubuntu' créé.${NC}\n"
fi

# Cloner le dépôt (si ce n'est pas déjà fait)
REPO_DIR="/home/ubuntu/agent-rennesdev"
if [ ! -d "$REPO_DIR" ]; then
    echo -e "${YELLOW}⏳ Clonage du dépôt GitHub...${NC}"
    git clone https://github.com/Ruaudel-Emmanuel/agent-rennesdev.git "$REPO_DIR" > /dev/null 2>&1
    chown -R ubuntu:ubuntu "$REPO_DIR"
    echo -e "${GREEN}✅ Dépôt cloné.${NC}\n"
else
    echo -e "${YELLOW}ℹ️  Le dépôt existe déjà dans $REPO_DIR.${NC}\n"
fi

# Créer les dossiers nécessaires
echo -e "${YELLOW}⏳ Création des dossiers...${NC}"
mkdir -p /home/ubuntu/{uploads,communication-web/conversations}
chown -R ubuntu:ubuntu /home/ubuntu/{uploads,communication-web}
echo -e "${GREEN}✅ Dossiers créés.${NC}\n"

# Installer les dépendances Python
echo -e "${YELLOW}⏳ Installation des dépendances Python...${NC}"
su - ubuntu -c "
    cd $REPO_DIR/backend
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
"
echo -e "${GREEN}✅ Dépendances Python installées.${NC}\n"

# Configurer Caddy
echo -e "${YELLOW}⏳ Configuration de Caddy...${NC}"
if [ ! -f "/etc/caddy/Caddyfile" ]; then
    echo -e "${RED}Erreur : Caddy n'est pas installé.${NC}"
    echo "Installe Caddy d'abord : https://caddyserver.com/docs/install"
    exit 1
fi

cp "$REPO_DIR/configs/caddy/Caddyfile" /etc/caddy/Caddyfile
systemctl restart caddy > /dev/null 2>&1
echo -e "${GREEN}✅ Caddy configuré.${NC}\n"

# Configurer le service systemd
echo -e "${YELLOW}⏳ Configuration du service systemd...${NC}"
cp "$REPO_DIR/configs/systemd/communication-web.service" /etc/systemd/system/
systemctl daemon-reload > /dev/null 2>&1
systemctl enable communication-web > /dev/null 2>&1
systemctl start communication-web > /dev/null 2>&1
echo -e "${GREEN}✅ Service systemd configuré.${NC}\n"

# Vérifier que le service est démarré
if systemctl is-active --quiet communication-web; then
    echo -e "${GREEN}✅ Service Agent RennesDev démarré avec succès !${NC}\n"
else
    echo -e "${RED}Erreur : Le service n'a pas pu démarrer.${NC}"
    echo "Vérifie les logs avec : journalctl -u communication-web -f"
    exit 1
fi

# Afficher les informations de connexion
echo -e "${BLUE}============================================${NC}"
echo -e "${GREEN}✅ Installation terminée avec succès !${NC}"
echo -e "${BLUE}============================================${NC}\n"

echo "🌐 Accède à l'interface :"
echo "   https://agent.rennesdev.fr"
echo ""
echo "📖 Documentation API :"
echo "   https://agent.rennesdev.fr/docs"
echo ""
echo "💡 Commandes utiles :"
echo "   - Redémarrer le service : sudo systemctl restart communication-web"
echo "   - Voir les logs : sudo journalctl -u communication-web -f"
echo "   - Arrêter le service : sudo systemctl stop communication-web"
echo ""
echo -e "${BLUE}============================================${NC}\n"
