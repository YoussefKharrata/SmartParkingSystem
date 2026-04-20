#!/usr/bin/env python3
"""
Simulateur Arduino -- SmartParking
Usage:
    python simulate_arduino.py          # mode interactif
    python simulate_arduino.py --auto   # automatique aleatoire
    python simulate_arduino.py --rush   # heure de pointe
    python simulate_arduino.py --demo   # demo complete
"""

import json, time, random, sys, os, threading
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Installez paho-mqtt : pip install paho-mqtt")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from config import NB_PLACES, MQTT_BROKER, MQTT_PORT
except ImportError:
    NB_PLACES, MQTT_BROKER, MQTT_PORT = 6, "localhost", 1883

# ── Couleurs ────────────────────────────────────────────────────────────────────
C = {"reset":"\033[0m","bold":"\033[1m","green":"\033[92m","red":"\033[91m",
     "yellow":"\033[93m","blue":"\033[94m","cyan":"\033[96m","dim":"\033[2m","purple":"\033[95m"}
def c(color, text): return f"{C.get(color,'')}{text}{C['reset']}"

# ── Etat ────────────────────────────────────────────────────────────────────────
places_etat   = {i: {"occupe": False, "distance": 80.0} for i in range(1, NB_PLACES + 1)}
porte_ouverte = False
stats         = {"publies": 0, "erreurs": 0, "badges": 0, "alertes": 0}
mqtt_connected = False

BADGES = {
    "4A:3F:1C:88": {"nom": "Ahmed Benali",   "label": "regulier",    "nb_visites": 47, "card_type": "MIFARE 1KB"},
    "B2:9E:47:D1": {"nom": "Fatima Zahra",   "label": "regulier",    "nb_visites": 23, "card_type": "MIFARE 1KB"},
    "CC:11:5A:2F": {"nom": "Mehdi Chraibi",  "label": "occasionnel", "nb_visites": 6,  "card_type": "MIFARE Ultralight"},
    "99:FF:AA:00": {"nom": "Sara El Amrani", "label": "nouveau",     "nb_visites": 1,  "card_type": "MIFARE 1KB"},
    "DE:AD:BE:EF": {"nom": "Youssef Kadiri", "label": "regulier",    "nb_visites": 31, "card_type": "MIFARE 1KB"},
    "77:AB:CD:12": {"nom": "Nadia Tazi",     "label": "occasionnel", "nb_visites": 8,  "card_type": "MIFARE Ultralight"},
    "AA:BB:CC:DD": {"nom": "Karim Mansouri", "label": "nouveau",     "nb_visites": 2,  "card_type": "MIFARE 1KB"},
}

# ── MQTT ─────────────────────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, reason_code, properties=None):
    global mqtt_connected
    mqtt_connected = True
    client.subscribe("parking/commande")
    log(c("green", "Connecte MQTT") + f" -> {MQTT_BROKER}:{MQTT_PORT}")

def on_disconnect(client, userdata, disconnect_flags, reason_code=None, properties=None):
    global mqtt_connected
    mqtt_connected = False
    log(c("red", "MQTT deconnecte"))

def on_commande(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        cmd  = data.get("commande", "")
        if cmd == "OPEN":
            send_porte("ouverte")
            log(c("cyan", "<- Commande OPEN"))
        elif cmd == "CLOSE":
            send_porte("fermee")
            log(c("cyan", "<- Commande CLOSE"))
    except Exception:
        pass

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_message    = on_commande

def connecter_mqtt():
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        time.sleep(0.6)
    except Exception as e:
        log(c("red", f"Connexion MQTT impossible: {e}"))
        log(c("yellow", "  Lancez mosquitto ou verifiez config.py"))

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{c('dim', ts)}  {msg}")

def pub(topic, payload):
    try:
        client.publish(topic, json.dumps(payload, ensure_ascii=False))
        stats["publies"] += 1
    except Exception as e:
        stats["erreurs"] += 1
        log(c("red", f"Erreur publish {topic}: {e}"))

# ── Capteurs ─────────────────────────────────────────────────────────────────────
def send_sensor(place_id, occupe=None, distance=None):
    global places_etat
    if occupe is None:
        occupe = places_etat[place_id]["occupe"]
    if distance is None:
        if occupe:
            distance = round(random.uniform(4, 14) + random.uniform(-1, 1), 1)
        else:
            distance = round(random.uniform(65, 110) + random.uniform(-3, 3), 1)
    places_etat[place_id]["occupe"]   = occupe
    places_etat[place_id]["distance"] = distance
    pub("parking/sensor", {
        "type": "sensor", "place_id": place_id, "distance": distance,
        "occupe": occupe, "porte_ouverte": porte_ouverte,
        "timestamp": datetime.now().isoformat(),
    })
    etat = c("red", "OCCUPEE") if occupe else c("green", "LIBRE  ")
    log(f"  Capteur P{place_id} -> {etat}  dist={c('yellow', f'{distance:5.1f} cm')}")

def send_all_sensors():
    log(c("blue", "Envoi etat toutes les places"))
    for pid in range(1, NB_PLACES + 1):
        send_sensor(pid)
        time.sleep(0.05)

# ── Porte ─────────────────────────────────────────────────────────────────────────
def send_porte(etat):
    global porte_ouverte
    porte_ouverte = (etat == "ouverte")
    pub("parking/porte", {"type":"porte","etat":etat,"timestamp":datetime.now().isoformat()})
    icon = "Ouverte" if etat == "ouverte" else "Fermee"
    couleur = "green" if etat == "ouverte" else "red"
    log(f"  Porte -> {c(couleur, icon.upper())}")

# ── Badge RFID ────────────────────────────────────────────────────────────────────
def send_rfid(uid=None):
    global stats
    if uid is None:
        uid = random.choice(list(BADGES.keys()))
    badge = BADGES.get(uid, {"nom":"Inconnu","label":"nouveau","nb_visites":0,"card_type":"MIFARE 1KB"})
    badge["nb_visites"] += 1
    BADGES[uid] = badge
    now = datetime.now()
    nb  = badge["nb_visites"]
    place_libre = any(not v["occupe"] for v in places_etat.values())
    stats["badges"] += 1

    profil = {"uid":uid,"nom":badge["nom"],"nb_visites":nb,"label":badge["label"],
              "card_type":badge["card_type"],"premiere_visite":now.isoformat(),
              "derniere_visite":now.isoformat(),
              "heures_frequentes":{str(now.hour):nb},"jours_frequents":{str(now.weekday()):nb}}

    pub("parking/rfid", {"type":"rfid","uid":uid,"card_type":badge["card_type"],
        "place_libre":place_libre,"timestamp":now.isoformat()})
    pub("parking/profil", {"timestamp":now.isoformat(),"uid":uid,
        "card_type":badge["card_type"],"profil":profil})
    pub("parking/profils_all", [
        {"uid":u,"nom":b["nom"],"nb_visites":b["nb_visites"],"label":b["label"],
         "card_type":b["card_type"],"premiere_visite":now.isoformat(),"derniere_visite":now.isoformat(),
         "heures_frequentes":json.dumps({str(now.hour):b["nb_visites"]}),
         "jours_frequents":json.dumps({str(now.weekday()):b["nb_visites"]})}
        for u,b in BADGES.items()])

    lc = {"regulier":"green","occasionnel":"yellow","nouveau":"blue"}.get(badge["label"],"dim")
    log(f"  Badge {c('cyan',uid)} -- {badge['nom']} -- {c(lc,badge['label'])} ({nb} visites)")

    if not place_libre:
        send_alerte(f"Badge {uid} ({badge['nom']}) refuse -- parking complet", "warning")
    else:
        def sequence():
            time.sleep(0.4)
            send_porte("ouverte")
            time.sleep(random.uniform(2.5, 4.0))
            send_porte("fermee")
            time.sleep(random.uniform(1.0, 2.0))
            libres = [pid for pid,v in places_etat.items() if not v["occupe"]]
            if libres:
                send_sensor(random.choice(libres), occupe=True)
        threading.Thread(target=sequence, daemon=True).start()

# ── Alertes ───────────────────────────────────────────────────────────────────────
def send_alerte(msg, type_alerte="danger"):
    stats["alertes"] += 1
    pub("parking/alerte", {"type":type_alerte,"message":msg,"timestamp":datetime.now().isoformat()})
    icon = "ALERTE" if type_alerte == "danger" else "AVERT."
    log(f"  [{c('red',icon)}] {msg}")

# ── Scenarios ─────────────────────────────────────────────────────────────────────
def scenario_voiture_entre(place_id=None):
    libres = [pid for pid,v in places_etat.items() if not v["occupe"]]
    if not libres:
        log(c("yellow", "  Toutes les places sont occupees"))
        return
    if place_id is None:
        place_id = random.choice(libres)
    log(c("green", f"  Voiture entre -> Place P{place_id}"))
    send_porte("ouverte")
    time.sleep(1.5)
    send_porte("fermee")
    time.sleep(1.0)
    send_sensor(place_id, occupe=True)

def scenario_voiture_sort(place_id=None):
    occupees = [pid for pid,v in places_etat.items() if v["occupe"]]
    if not occupees:
        log(c("yellow", "  Aucune place occupee"))
        return
    if place_id is None:
        place_id = random.choice(occupees)
    log(c("blue", f"  Voiture sort -> Place P{place_id} se libere"))
    send_sensor(place_id, occupe=False)
    time.sleep(0.8)
    send_porte("ouverte")
    time.sleep(2.0)
    send_porte("fermee")

def scenario_remplissage(delai=1.2):
    log(c("bold", "  Scenario: remplissage progressif"))
    for pid in range(1, NB_PLACES+1):
        if not places_etat[pid]["occupe"]:
            send_sensor(pid, occupe=True)
            time.sleep(delai)

def scenario_vidage(delai=1.2):
    log(c("bold", "  Scenario: vidage progressif"))
    for pid in range(1, NB_PLACES+1):
        if places_etat[pid]["occupe"]:
            send_sensor(pid, occupe=False)
            time.sleep(delai)

def scenario_heure_pointe(duree_sec=45):
    log(c("yellow", c("bold", f"  Scenario HEURE DE POINTE ({duree_sec}s)")))
    fin = time.time() + duree_sec
    while time.time() < fin:
        libres   = [pid for pid,v in places_etat.items() if not v["occupe"]]
        occupees = [pid for pid,v in places_etat.items() if v["occupe"]]
        restant  = int(fin - time.time())

        if libres and random.random() < 0.68:
            send_sensor(random.choice(libres), occupe=True)
            if random.random() < 0.35:
                send_rfid()
        elif occupees and random.random() < 0.28:
            send_sensor(random.choice(occupees), occupe=False)

        if random.random() < 0.07:
            send_alerte("Manoeuvre dangereuse detectee -- zone P"+str(random.randint(1,NB_PLACES)), "warning")

        nb_occ = sum(1 for v in places_etat.values() if v["occupe"])
        log(f"  {c('dim',f'[{restant}s]')} {nb_occ}/{NB_PLACES} places occupees")
        time.sleep(random.uniform(0.9, 2.2))
    log(c("green", "  Fin heure de pointe"))

def scenario_demo():
    log(c("purple", c("bold", "\n=== DEMO COMPLETE SmartParking ===")))
    log(c("bold", "\n[1/6] Initialisation -- toutes les places libres"))
    scenario_vidage(0.3)
    time.sleep(1)
    log(c("bold", "\n[2/6] 3 vehicules avec badge RFID"))
    for _ in range(3):
        send_rfid()
        time.sleep(2.5)
    log(c("bold", "\n[3/6] 2 vehicules sans reservation"))
    scenario_voiture_entre()
    time.sleep(2)
    scenario_voiture_entre()
    time.sleep(2)
    log(c("bold", "\n[4/6] Tentative d'intrusion"))
    send_alerte("Badge RFID inconnu detecte -- acces refuse", "danger")
    time.sleep(1.5)
    log(c("bold", "\n[5/6] 2 departs"))
    scenario_voiture_sort()
    time.sleep(2)
    scenario_voiture_sort()
    time.sleep(2)
    log(c("bold", "\n[6/6] Etat final"))
    send_all_sensors()
    log(c("green", c("bold", "\nDemo terminee!\n")))

# ── Mode automatique ──────────────────────────────────────────────────────────────
def mode_automatique():
    log(c("yellow", c("bold", "Mode automatique -- Ctrl+C pour arreter")))
    send_all_sensors()
    time.sleep(1)
    iteration = 0
    while True:
        iteration += 1
        rand = random.random()
        libres   = [pid for pid,v in places_etat.items() if not v["occupe"]]
        occupees = [pid for pid,v in places_etat.items() if v["occupe"]]

        if rand < 0.30:
            if libres and random.random() < 0.6:
                send_sensor(random.choice(libres), occupe=True)
            elif occupees:
                send_sensor(random.choice(occupees), occupe=False)
        elif rand < 0.50:
            send_all_sensors()
        elif rand < 0.65:
            send_rfid()
        elif rand < 0.70:
            msgs = [
                "Vehicule mal gare en P"+str(random.randint(1,NB_PLACES)),
                "Occupation sans badge RFID detectee",
                "Capteur P"+str(random.randint(1,NB_PLACES))+" -- lecture instable",
                "Duree de stationnement depassee",
            ]
            send_alerte(random.choice(msgs), random.choice(["warning","danger"]))

        if iteration % 10 == 0:
            nb_occ = sum(1 for v in places_etat.values() if v["occupe"])
            log(c("dim", f"  Bilan: {nb_occ}/{NB_PLACES} occupees | {stats['publies']} pub | {stats['badges']} badges"))

        time.sleep(random.uniform(2, 5))

# ── Interface interactive ──────────────────────────────────────────────────────────
AIDE = """
Commandes disponibles :
  s              -> rafraichir tous les capteurs
  s<N>           -> rafraichir place N          (ex: s3)
  s<N>0          -> place N = LIBRE             (ex: s30)
  s<N>1          -> place N = OCCUPEE           (ex: s31)

  entree [N]     -> voiture entre (sur la place N ou aleatoire)
  sortie [N]     -> voiture sort  (de la place N ou aleatoire)
  remplir        -> remplissage progressif
  vider          -> vidage progressif
  rush           -> simulation heure de pointe (45s)
  demo           -> demo complete enchainees

  r              -> badge RFID aleatoire
  r <uid>        -> badge RFID avec UID precis  (ex: r 4A:3F:1C:88)
  badges         -> lister les badges disponibles
  o              -> porte ouverte
  f              -> porte fermee

  alerte <msg>   -> envoyer une alerte manuelle
  etat           -> afficher l etat de toutes les places
  stats          -> statistiques MQTT
  aide           -> cette aide
  q              -> quitter
"""

def afficher_etat():
    print()
    nb_occ = sum(1 for v in places_etat.values() if v["occupe"])
    print(f"  {c('bold', f'Parking -- {nb_occ}/{NB_PLACES} places occupees')}")
    print()
    for pid, v in places_etat.items():
        if v["occupe"]:
            print(f"  P{pid}  {c('red','  OCCUPEE')}   dist={c('yellow', f\"{v['distance']:5.1f} cm\")}")
        else:
            print(f"  P{pid}  {c('green','  LIBRE  ')}   dist={c('dim', f\"{v['distance']:5.1f} cm\")}")
    print()

def afficher_badges():
    print()
    print(f"  {c('bold','Badges disponibles:')}")
    for uid, b in BADGES.items():
        lc = {"regulier":"green","occasionnel":"yellow","nouveau":"blue"}.get(b["label"],"dim")
        print(f"  {c('cyan',uid)}  {b['nom']:<20}  {c(lc,b['label']):<12}  {b['nb_visites']} visites")
    print()

def mode_interactif():
    print(c("bold", c("blue", """
  SIMULATEUR ARDUINO -- SmartParking
  Tapez 'aide' pour voir les commandes.
""")))
    send_all_sensors()

    while True:
        try:
            line = input(f"\n{c('cyan','>')} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue

        parts = line.split(None, 1)
        cmd   = parts[0].lower()
        arg   = parts[1].strip() if len(parts) > 1 else None

        if cmd in ("q","quit","exit"):
            break
        elif cmd in ("aide","help","?"):
            print(AIDE)
        elif cmd == "etat":
            afficher_etat()
        elif cmd == "badges":
            afficher_badges()
        elif cmd == "stats":
            nb_occ = sum(1 for v in places_etat.values() if v["occupe"])
            print(f"\n  Publies: {stats['publies']}  Erreurs: {stats['erreurs']}  Badges: {stats['badges']}  Alertes: {stats['alertes']}")
            print(f"  Places occupees: {nb_occ}/{NB_PLACES}  MQTT: {'OK' if mqtt_connected else 'KO'}\n")
        elif cmd == "s":
            send_all_sensors()
        elif cmd.startswith("s") and len(cmd) >= 2:
            try:
                if cmd[-1] in ("0","1"):
                    pid = int(cmd[1:-1]); occup = cmd[-1] == "1"
                    if 1 <= pid <= NB_PLACES: send_sensor(pid, occupe=occup)
                    else: print(c("red", f"  Place invalide (1-{NB_PLACES})"))
                else:
                    pid = int(cmd[1:])
                    if 1 <= pid <= NB_PLACES: send_sensor(pid)
                    else: print(c("red", f"  Place invalide (1-{NB_PLACES})"))
            except ValueError:
                print(c("red", "  Commande inconnue -- tapez 'aide'"))
        elif cmd == "entree":
            if arg:
                try: threading.Thread(target=scenario_voiture_entre, args=(int(arg),), daemon=True).start()
                except ValueError: print(c("red","  Numero de place invalide"))
            else:
                threading.Thread(target=scenario_voiture_entre, daemon=True).start()
        elif cmd == "sortie":
            if arg:
                try: threading.Thread(target=scenario_voiture_sort, args=(int(arg),), daemon=True).start()
                except ValueError: print(c("red","  Numero de place invalide"))
            else:
                threading.Thread(target=scenario_voiture_sort, daemon=True).start()
        elif cmd == "remplir":
            threading.Thread(target=scenario_remplissage, daemon=True).start()
        elif cmd == "vider":
            threading.Thread(target=scenario_vidage, daemon=True).start()
        elif cmd == "rush":
            threading.Thread(target=scenario_heure_pointe, daemon=True).start()
        elif cmd == "demo":
            threading.Thread(target=scenario_demo, daemon=True).start()
        elif cmd == "r":
            if arg:
                uid = arg.upper()
                if uid not in BADGES:
                    BADGES[uid] = {"nom":"Badge manuel","label":"nouveau","nb_visites":0,"card_type":"MIFARE 1KB"}
                send_rfid(uid)
            else:
                send_rfid()
        elif cmd in ("o","open"):
            send_porte("ouverte")
        elif cmd in ("f","close"):
            send_porte("fermee")
        elif cmd == "alerte":
            send_alerte(arg or "Alerte test")
        else:
            print(c("red", f"  Commande inconnue: '{cmd}' -- tapez 'aide'"))

# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    mode = "interactif"
    if "--auto"  in sys.argv: mode = "auto"
    elif "--rush" in sys.argv: mode = "rush"
    elif "--demo" in sys.argv: mode = "demo"

    print(c("bold", c("blue", f"""
============================================
  SIMULATEUR ARDUINO -- SmartParking
  Places: {NB_PLACES}  |  MQTT: {MQTT_BROKER}:{MQTT_PORT}
  Mode: {mode}
============================================""")))

    connecter_mqtt()
    time.sleep(0.5)
    if not mqtt_connected:
        print(c("yellow", "Demarre sans MQTT (verifiez que mosquitto tourne)\n"))

    try:
        if mode == "auto":
            mode_automatique()
        elif mode == "rush":
            send_all_sensors()
            scenario_heure_pointe(60)
        elif mode == "demo":
            scenario_demo()
        else:
            mode_interactif()
    except KeyboardInterrupt:
        print(c("dim", "\nInterrompu."))

    client.loop_stop()
    try: client.disconnect()
    except: pass
    print(c("dim", f"\nTermine -- {stats['publies']} messages publies\n"))

if __name__ == "__main__":
    main()
