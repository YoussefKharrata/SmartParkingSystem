# SmartParking — Système de parking intelligent IoT

Projet d'IoT réalisé sur Raspberry Pi 4 et Arduino Uno. Le système détecte en temps réel l'occupation d'une place de parking via un capteur ultrasonique HC-SR04, contrôle l'accès par badge RFID (MFRC522), et ouvre une barrière motorisée (servo SG90) uniquement si la place est libre. Chaque badge est profilé automatiquement au fil du temps (fréquence de visite, horaires habituels, classification). Un module de Machine Learning prédit l'occupation sur les 12 prochaines heures et détecte les comportements de badges anormaux. Tout est supervisé via un dashboard web temps réel accessible depuis n'importe quel appareil sur le réseau local.

### Membres

- Youssef KHARRATA : [LinkedIn](https://www.linkedin.com/in/youssef-kharrata-696600331/)  
- Adam MRANI : [LinkedIn](https://www.linkedin.com/in/adam-mrani-b28a40321/)  
- Ayman BENAYAD : [LinkedIn](https://www.linkedin.com/in/aymanbenayad/)  
- Marouane CHTITA : [LinkedIn](https://www.linkedin.com/in/marouane-chtita/)

---

## Structure du projet

```
/home/pi/parking/
├── mqtt_bridge.py          Pont Arduino -> MQTT + profiling RFID + SQLite
├── ml_module.py            Module Machine Learning (entraînement + serveur)
├── dashboard.py            Serveur Flask + API REST + WebSocket
├── parking_main.ino        Firmware Arduino Uno
├── simulate_arduino.py     Simulateur Arduino pour tests sans matériel
├── dataset.csv             Données historiques d'occupation (entraînement ML)
├── requirements.txt        Dépendances Python
├── templates/
│   └── dashboard.html      Interface web (HTML/CSS/JS)
├── data/
│   └── parking.db          Base SQLite (créée automatiquement)
├── models/
│   ├── model_prediction.pkl    Modèle RandomForest (créé automatiquement)
│   ├── model_clustering.pkl    Modèle KMeans badges (créé automatiquement)
│   ├── model_anomalie.pkl      Modèle IsolationForest (créé automatiquement)
│   └── stats.json              Métriques du dernier entraînement
└── logs/
    ├── bridge.log
    └── ml.log
```

---

## Fonctionnement général

Le système repose sur trois processus Python indépendants qui communiquent via un bus de messages MQTT (Mosquitto).

`mqtt_bridge.py` est le seul composant connecté à l'Arduino. Il lit en continu le port série USB, parse les JSON envoyés par le firmware, et fait le lien avec le reste du système. C'est lui qui décide d'ouvrir la porte (envoi de `OPEN` à l'Arduino) après réception d'un badge, et qui construit le profil de chaque badge au fil du temps. Toutes les données sont persistées dans une base SQLite.

`ml_module.py` est un serveur ML autonome. Il s'abonne aux topics MQTT pour recevoir les événements en temps réel, calcule des prédictions d'occupation pour les 12 prochaines heures, et surveille les profils de badges pour détecter des comportements anormaux. Il se ré-entraîne automatiquement toutes les heures sur les données accumulées.

`dashboard.py` est le serveur web. Il s'abonne à tous les topics MQTT et pousse immédiatement chaque mise à jour vers les navigateurs connectés via WebSocket (SocketIO), sans que le client ait besoin de faire du polling. Il expose également une API REST pour le chargement initial des données historiques.

L'Arduino ne prend aucune décision d'autorisation. Il transmet l'UID brut du badge et attend une commande `OPEN` ou `CLOSE` en retour.

---

## Profiling RFID

Chaque badge qui se présente est enregistré dans la table `profils` de SQLite. À chaque passage, le système incrémente le compteur de visites et met à jour deux dictionnaires JSON : l'un compte les passages par heure (0–23), l'autre par jour de la semaine (0=lundi, 6=dimanche). Un label est calculé automatiquement selon la fréquence :

- `nouveau` : 1 à 2 visites
- `occasionnel` : 3 à 9 visites
- `regulier` : 10 visites et plus

Ces profils alimentent le module KMeans qui regroupe les badges en 3 clusters comportementaux. Un badge dont le cluster présente beaucoup de refus et une forte variance horaire est signalé comme suspect via le topic `parking/ml/profil_alerte`.

---

## Module ML — les trois modèles

**RandomForestClassifier (prédiction d'occupation)**

Les features temporelles brutes (heure, jour) sont encodées en coordonnées polaires via sinus/cosinus. Cela permet au modèle de comprendre que 23h et 0h sont proches, ou que dimanche et lundi sont adjacents, sans traiter ces valeurs comme des entiers linéaires. Features utilisées : `heure_sin`, `heure_cos`, `jour_sin`, `jour_cos`, `est_weekend`, `heure_pointe`, `minute`. Le modèle produit une probabilité d'occupation pour chacune des 12 prochaines heures.

**KMeans (clustering comportemental des badges)**

Pour chaque badge, cinq métriques sont calculées : nombre de visites, heure moyenne de passage, variance des horaires, nombre de refus enregistrés, nombre de jours distincts fréquentés. Ces vecteurs sont normalisés via StandardScaler puis regroupés en 3 clusters. Le cluster à forte variance horaire et beaucoup de refus correspond typiquement à un comportement anormal.

**IsolationForest (anomalies capteur)**

Entraîné uniquement sur les mesures de distance lorsque la place est libre, il établit une baseline de ce qu'est une lecture "normale" (grande distance, régulière). Toute lecture future qui s'écarte significativement de cette baseline est signalée comme une anomalie matérielle.

---

## Source de données pour l'entraînement

Le module ML cherche `dataset.csv` en premier. Ce fichier contient des données historiques réelles d'un parking public (colonnes : `SystemCodeNumber`, `Capacity`, `Occupancy`, `LastUpdated`). Le taux d'occupation est calculé comme `Occupancy / Capacity`, et un seuil à 50% détermine la valeur binaire `occupe`. La colonne distance est reconstituée synthétiquement (3–15 cm si occupé, 25–120 cm si libre) pour alimenter l'IsolationForest.

Si `dataset.csv` est absent ou contient moins de 100 lignes valides, le module bascule automatiquement sur SQLite (données réelles collectées par l'Arduino), puis en dernier recours génère 30 jours de données simulées avec des profils horaires réalistes (pics matin/midi/soir atténués le week-end).

Le fichier `models/stats.json` indique après chaque entraînement la source utilisée (`dataset.csv`, `sqlite/simulated`), le nombre d'exemples, et la précision obtenue.

---

## 1. Prérequis système

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip mosquitto mosquitto-clients
```

---

## 2. Installation des dépendances Python

```bash
cd /home/pi/parking
pip3 install -r requirements.txt --break-system-packages
```

---

## 3. Démarrer le broker MQTT (Mosquitto)

Mosquitto est le bus central du système. Tous les composants communiquent exclusivement via lui. Il doit être démarré avant tout autre service.

```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Pour surveiller tous les messages en temps réel :

```bash
mosquitto_sub -h localhost -t "parking/#" -v
```

---

## 4. Identifier le port série de l'Arduino

```bash
ls /dev/tty*
# Généralement /dev/ttyUSB0 ou /dev/ttyACM0
sudo usermod -a -G dialout pi
```

Modifier la variable `SERIAL_PORT` dans `mqtt_bridge.py` si nécessaire. Si le port change après un redémarrage, créer une règle udev pour fixer le nom du périphérique.

---

## 5. Entraînement du modèle ML

À effectuer une première fois avant de lancer le serveur ML. Si les modèles `.pkl` sont absents au démarrage de `ml_module.py`, l'entraînement se déclenche automatiquement.

```bash
python3 ml_module.py --train-only
```

La précision attendue avec `dataset.csv` est entre 85% et 92% selon la répartition des données.

Pour forcer la génération de données simulées et les injecter dans SQLite :

```bash
python3 ml_module.py --generate-data --jours 30
```

---

## 6. Lancement des services

Lancer chaque service dans un terminal séparé, dans cet ordre.

### Terminal 1 — Pont MQTT

```bash
python3 /home/pi/parking/mqtt_bridge.py
```

Attend le message `SYSTEM:READY` de l'Arduino puis commence à traiter les JSON entrants. Publie sur MQTT et écrit dans SQLite à chaque événement.

### Terminal 2 — Module ML

```bash
python3 /home/pi/parking/ml_module.py
```

Charge ou entraîne les modèles au démarrage, puis écoute `parking/sensor` et `parking/rfid` pour publier des prédictions en temps réel. Se ré-entraîne toutes les heures.

### Terminal 3 — Dashboard

```bash
python3 /home/pi/parking/dashboard.py
```

Accès dashboard : `http://<IP_RASPBERRY>:5000`

Pour obtenir l'adresse IP : `hostname -I`

---

## 7. Tests sans Arduino — simulateur

`simulate_arduino.py` remplace complètement l'Arduino pendant le développement. Il publie directement sur MQTT les mêmes JSON que le firmware enverrait par port série. `mqtt_bridge.py` n'est pas nécessaire dans ce cas : le simulateur bypasse la couche série et injecte les messages directement dans le bus.

Lancer `dashboard.py` et `ml_module.py` normalement, puis à la place de `mqtt_bridge.py` :

```bash
# Mode manuel (console interactive)
python3 simulate_arduino.py

# Mode automatique (envois périodiques aléatoires)
python3 simulate_arduino.py --auto
```

Commandes disponibles en mode manuel :

| Commande | Effet |
|---|---|
| `s` | Sensor avec l'état courant |
| `s0` | Place libre (grande distance) |
| `s1` | Place occupée (petite distance) |
| `r` | Badge RFID aléatoire parmi 5 cartes prédéfinies |
| `r DE:AD:BE:EF` | Badge avec UID précis |
| `o` | Porte ouverte |
| `f` | Porte fermée |
| `a occupation sans badge` | Alerte avec message personnalisé |
| `q` | Quitter |

En mode automatique, le simulateur envoie un sensor toutes les 5 secondes, déclenche un passage RFID avec ouverture/fermeture de porte avec 15% de probabilité, et génère une alerte avec 5% de probabilité.

---

## 8. Démarrage automatique via systemd

Créer `/etc/systemd/system/parking-bridge.service` :

```ini
[Unit]
Description=Parking MQTT Bridge
After=network.target mosquitto.service

[Service]
ExecStart=/usr/bin/python3 /home/pi/parking/mqtt_bridge.py
WorkingDirectory=/home/pi/parking
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Répéter pour `parking-ml.service` et `parking-dashboard.service` avec les scripts correspondants.

```bash
sudo systemctl enable parking-bridge parking-ml parking-dashboard
sudo systemctl start  parking-bridge parking-ml parking-dashboard
```

---

## 9. Architecture des flux de données

```
Arduino Uno (USB série)
    |   JSON toutes les 500 ms
    v
mqtt_bridge.py
    |-- Publie  --> parking/sensor       (état capteur temps réel)
    |-- Publie  --> parking/rfid         (événement badge brut)
    |-- Publie  --> parking/profil       (profil badge mis à jour)
    |-- Publie  --> parking/profils_all  (liste complète des profils)
    |-- Publie  --> parking/porte        (état ouvert/fermé)
    |-- Sauvegarde --> parking.db (SQLite)
                         |
                         v
                   ml_module.py
                    |-- Lit parking.db ou dataset.csv
                    |-- Entraîne RandomForest + KMeans + IsolationForest
                    |-- Publie --> parking/ml/result        (prédictions 12h)
                    |-- Publie --> parking/ml/profil_alerte (badge suspect)
                    |-- Re-entraîne toutes les heures
                         |
                         v
                   dashboard.py (Flask)
                    |-- Souscrit à parking/#
                    |-- Pousse mises à jour via WebSocket (SocketIO)
                    |-- Expose API REST
                    |-- Sert templates/dashboard.html
```

Sans Arduino, `simulate_arduino.py` publie directement sur MQTT et remplace `mqtt_bridge.py` dans ce schéma.

---

## 10. Topics MQTT

| Topic                      | Direction           | Contenu                                               |
|----------------------------|---------------------|-------------------------------------------------------|
| `parking/sensor`           | Bridge -> tous      | Distance (cm), état occupé, porte ouverte             |
| `parking/rfid`             | Bridge -> tous      | UID badge, type carte, horodatage                     |
| `parking/profil`           | Bridge -> tous      | Profil complet du badge scanné (label, stats)         |
| `parking/profils_all`      | Bridge -> tous      | Liste complète de tous les profils connus             |
| `parking/porte`            | Bridge -> tous      | Etat ouvert / fermé                                   |
| `parking/ml/result`        | ML -> dashboard     | Probabilités d'occupation pour les 12h à venir        |
| `parking/ml/profil_alerte` | ML -> dashboard     | Badge dont le cluster indique un comportement anormal |
| `parking/ml/retrain`       | ML -> tous          | Notification de ré-entraînement + précision           |
| `parking/commande`         | Dashboard -> Bridge | OPEN ou CLOSE (commande manuelle porte)               |
| `parking/status`           | Bridge -> tous      | online / offline / arduino_ready                      |

---

## 11. API REST

| Route                  | Méthode | Description                                              |
|------------------------|---------|----------------------------------------------------------|
| `/api/etat`            | GET     | Snapshot complet de l'état courant en mémoire            |
| `/api/profils`         | GET     | Tous les badges enregistrés, triés par nombre de visites |
| `/api/profil/<uid>`    | GET     | Détail d'un badge + ses 50 derniers passages             |
| `/api/rfid`            | GET     | 50 derniers événements RFID avec jointure profil         |
| `/api/stats`           | GET     | Taux d'occupation moyen et passages par heure (SQL)      |
| `/api/commande`        | POST    | Envoyer `OPEN` ou `CLOSE` à l'Arduino via MQTT           |

---

## 12. Câblage Arduino

| Composant        | Broche Arduino          |
|------------------|-------------------------|
| HC-SR04 TRIG     | D9                      |
| HC-SR04 ECHO     | D8                      |
| MFRC522 SDA      | D10                     |
| MFRC522 SCK      | D13                     |
| MFRC522 MOSI     | D11                     |
| MFRC522 MISO     | D12                     |
| MFRC522 RST      | D5                      |
| MFRC522 VCC      | 3.3V (jamais 5V)        |
| Servo signal     | D3 (PWM)                |
| LED verte        | D6 + résistance 220 Ohm |
| LED rouge        | D7 + résistance 220 Ohm |
