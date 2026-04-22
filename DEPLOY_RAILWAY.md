# 🚂 Déploiement Railway — SmartParking Dashboard

## Variables d'environnement à configurer sur Railway

| Variable | Exemple | Description |
|---|---|---|
| `SECRET_KEY` | `une-clé-secrète-longue` | Clé Flask (obligatoire) |
| `MQTT_BROKER` | `abc123.hivemq.cloud` | Adresse du broker MQTT |
| `MQTT_PORT` | `8883` | 8883 pour TLS (HiveMQ Cloud) ou 1883 |
| `MQTT_USER` | `monuser` | Utilisateur MQTT (si broker cloud) |
| `MQTT_PASS` | `monpassword` | Mot de passe MQTT |
| `NB_PLACES` | `6` | Nombre de places de parking |

## Étapes de déploiement

### 1. Broker MQTT gratuit (HiveMQ Cloud)
1. Créer un compte sur https://www.hivemq.com/mqtt-cloud-broker/
2. Créer un cluster gratuit
3. Copier le hostname (ex: `abc.hivemq.cloud`)
4. Créer un utilisateur dans "Access Management"
5. Port = **8883** (TLS activé automatiquement)

### 2. Déployer sur Railway
1. Push ce dossier sur GitHub
2. Aller sur https://railway.app → New Project → Deploy from GitHub
3. Sélectionner le repo
4. Aller dans **Variables** et ajouter toutes les variables ci-dessus
5. Railway détecte automatiquement le `Procfile`

### 3. Connecter ton nom de domaine
1. Dans Railway → Settings → Networking → Custom Domain
2. Ajouter ton domaine
3. Configurer le DNS chez ton registrar : CNAME vers l'URL Railway fournie

## Coût estimé Railway
- Gratuit jusqu'à ~$5/mois de ressources
- Ce projet (Flask léger) consomme ~$2-4/mois en général
- Le plan Hobby à $5/mois couvre largement ce projet

## Notes importantes
- La base SQLite (`data/parking.db`) est **persistante dans le volume Railway**
- Le ML model (`models/`) est régénéré automatiquement au premier démarrage
- Le dashboard fonctionne sans Arduino — MQTT optionnel
