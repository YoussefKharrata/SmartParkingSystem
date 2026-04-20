# 🚀 Guide de déploiement — SmartParking

## Vue d'ensemble des options

| Option | Coût | Difficulté | Adapté pour |
|--------|------|------------|-------------|
| **VPS (Hetzner/OVH)** | ~5€/mois | Moyenne | Production stable |
| **Railway** | Gratuit → 5$/mois | Facile | Prototypes / démos |
| **Render** | Gratuit → 7$/mois | Facile | Prototypes |
| **Serveur local + Ngrok** | Gratuit | Très facile | Tests / démos |

---

## Option 1 — VPS (Recommandé pour production)

### 1.1 Préparer le serveur (Ubuntu 22.04)

```bash
# Connexion SSH
ssh root@VOTRE_IP

# Mise à jour système
apt update && apt upgrade -y

# Installer dépendances
apt install -y python3 python3-pip python3-venv nginx mosquitto git
```

### 1.2 Cloner et installer le projet

```bash
# Créer un utilisateur dédié
adduser parking
usermod -aG sudo parking
su - parking

# Cloner le projet
git clone https://github.com/VOTRE_COMPTE/SmartParking.git
cd SmartParking/server

# Environnement virtuel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 1.3 Configurer Gunicorn (serveur WSGI)

Créer `/etc/systemd/system/smartparking.service` :

```ini
[Unit]
Description=SmartParking Flask App
After=network.target

[Service]
User=parking
WorkingDirectory=/home/parking/SmartParking/server
Environment="PATH=/home/parking/SmartParking/server/venv/bin"
ExecStart=/home/parking/SmartParking/server/venv/bin/gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 127.0.0.1:5000 \
    dashboard:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable smartparking
systemctl start smartparking
systemctl status smartparking  # vérifier que c'est OK
```

### 1.4 Configurer Nginx (reverse proxy + HTTPS)

```bash
apt install -y certbot python3-certbot-nginx
```

Créer `/etc/nginx/sites-available/smartparking` :

```nginx
server {
    listen 80;
    server_name votre-domaine.com www.votre-domaine.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        
        # WebSocket (SocketIO)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_read_timeout 86400;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/smartparking /etc/nginx/sites-enabled/
nginx -t  # tester la config
systemctl restart nginx

# Certificat SSL gratuit (HTTPS)
certbot --nginx -d votre-domaine.com -d www.votre-domaine.com
```

### 1.5 DNS

Chez votre registrar (Namecheap, GoDaddy, OVH…) :
```
A    @    VOTRE_IP    TTL 3600
A    www  VOTRE_IP    TTL 3600
```

---

## Option 2 — Railway (Le plus simple)

### 2.1 Préparer le projet

Créer `server/Procfile` :
```
web: gunicorn --worker-class eventlet --workers 1 --bind 0.0.0.0:$PORT dashboard:app
```

Créer `server/runtime.txt` :
```
python-3.11.0
```

### 2.2 Déployer

```bash
# Installer Railway CLI
npm install -g @railway/cli

# Se connecter
railway login

# Initialiser et déployer
cd SmartParking/server
railway init
railway up
railway domain  # obtenir le domaine gratuit
```

### 2.3 Variables d'environnement sur Railway

Dans le dashboard Railway → Variables :
```
MQTT_BROKER=broker.hivemq.com
MQTT_PORT=1883
SECRET_KEY=votre_cle_secrete_longue
```

---

## Option 3 — Ngrok (Tests rapides / démos)

```bash
# Sur votre machine locale, lancer le serveur
cd SmartParking/server
python dashboard.py

# Dans un autre terminal, exposer avec Ngrok
ngrok http 5000
# → vous obtenez une URL publique type : https://abc123.ngrok.io
```

---

## Configuration MQTT pour production

Par défaut le projet utilise `localhost`. Pour un vrai déploiement :

### Option A — Mosquitto local (sur le VPS)

```bash
# Déjà installé à l'étape 1.1
systemctl enable mosquitto
systemctl start mosquitto
```

Dans `server/config.py` :
```python
MQTT_BROKER = "localhost"
MQTT_PORT   = 1883
```

### Option B — HiveMQ Cloud (gratuit, 10 connexions)

1. Créer un compte sur https://www.hivemq.com/mqtt-cloud-broker/
2. Récupérer Host, Port (8883), Username, Password

Dans `server/config.py` :
```python
MQTT_BROKER   = "XXXXX.s1.eu.hivemq.cloud"
MQTT_PORT     = 8883
MQTT_USER     = "votre_user"
MQTT_PASSWORD = "votre_mdp"
MQTT_TLS      = True
```

Et dans `dashboard.py`, activer TLS :
```python
import ssl
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
```

---

## Sécurisation minimale pour la production

### Ajouter une authentification simple

Dans `dashboard.py`, avant les routes admin :

```python
from functools import wraps
from flask import request, Response

ADMIN_USER = "admin"
ADMIN_PASS = "changez-moi-2025"

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
            return Response("Accès refusé", 401,
                {'WWW-Authenticate': 'Basic realm="SmartParking Admin"'})
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/reservations")
@require_auth
def admin_reservations():
    return render_template("admin_reservations.html")

@app.route("/admin/passages")
@require_auth
def admin_passages():
    return render_template("admin_passages.html")
```

### Variables d'environnement (ne pas hardcoder les secrets)

```python
import os

SECRET_KEY  = os.environ.get("SECRET_KEY", "parking-dev-key")
ADMIN_USER  = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS  = os.environ.get("ADMIN_PASS", "changez-moi")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
```

---

## Checklist avant mise en production

- [ ] Changer `SECRET_KEY` dans `dashboard.py`
- [ ] Activer HTTPS (Certbot ou Railway/Render le font automatiquement)
- [ ] Configurer un vrai broker MQTT (pas localhost)
- [ ] Sauvegarder régulièrement `data/parking.db`
- [ ] Ajouter authentification sur les routes `/admin/*`
- [ ] Configurer `NB_PLACES` correctement dans `config.py`
- [ ] Tester les WebSockets depuis l'extérieur

---

## Commandes utiles en production (VPS)

```bash
# Voir les logs en direct
journalctl -u smartparking -f

# Redémarrer après modification du code
systemctl restart smartparking

# Sauvegarder la base de données
cp /home/parking/SmartParking/server/data/parking.db \
   /home/parking/backups/parking_$(date +%Y%m%d).db

# Mettre à jour le code
cd /home/parking/SmartParking
git pull
source server/venv/bin/activate
pip install -r server/requirements.txt
systemctl restart smartparking
```
