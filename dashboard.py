#!/usr/bin/env python3

import json
import sqlite3
import threading
import logging
import os
import numpy as np
import pandas as pd
import joblib
from datetime import datetime

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt
from config import NB_PLACES, MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASS, SECRET_KEY
from reservations import (
    init_reservation_tables,
    get_places_reservees_maintenant,
    reservations_bp,
)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DB_PATH   = os.path.join(BASE_DIR, "data", "parking.db")
MODEL_DIR = os.path.join(BASE_DIR, "models")

# Créer les dossiers nécessaires au démarrage
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
os.makedirs(MODEL_DIR, exist_ok=True)

app      = Flask(__name__, template_folder="templates")
app.config["SECRET_KEY"] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

app.register_blueprint(reservations_bp)
init_reservation_tables()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

etat = {
    "places":        {str(i): {"occupe": False, "distance": 0, "porte_ouverte": False, "reservee": False} for i in range(1, NB_PLACES + 1)},
    "nb_places":     NB_PLACES,
    "nb_libres":     NB_PLACES,
    "nb_occupees":   0,
    "nb_reservees":  0,
    "derniere_maj":  "",
    "mqtt_ok":       False,
    "arduino_ok":    False,
    "dernier_badge": None,
    "alertes":       [],
    "predictions":   [],
}


def recalc_globaux():
    places_reservees = get_places_reservees_maintenant()
    for pid_str, place in etat["places"].items():
        place["reservee"] = int(pid_str) in places_reservees

    etat["nb_occupees"]  = sum(1 for p in etat["places"].values() if p["occupe"])
    etat["nb_reservees"] = sum(1 for p in etat["places"].values() if p["reservee"] and not p["occupe"])
    etat["nb_libres"]    = NB_PLACES - etat["nb_occupees"] - etat["nb_reservees"]
    if etat["nb_libres"] < 0:
        etat["nb_libres"] = 0


def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    etat["mqtt_ok"] = True
    client.subscribe("parking/#")


def on_mqtt_message(client, userdata, msg):
    try:
        data  = json.loads(msg.payload.decode())
        topic = msg.topic

        if topic == "parking/sensor":
            pid = str(data.get("place_id", 1))
            if pid in etat["places"]:
                etat["places"][pid].update({
                    "occupe":        data.get("occupe", False),
                    "distance":      data.get("distance", 0),
                    "porte_ouverte": data.get("porte_ouverte", False),
                })
            etat["derniere_maj"] = data.get("timestamp", "")
            etat["arduino_ok"]   = True
            recalc_globaux()
            socketio.emit("sensor_update", {
                "place_id": data.get("place_id", 1),
                "occupe":   data.get("occupe", False),
                "distance": data.get("distance", 0),
                "reservee": etat["places"][str(data.get("place_id", 1))].get("reservee", False),
                "nb_libres":    etat["nb_libres"],
                "nb_occupees":  etat["nb_occupees"],
                "nb_reservees": etat["nb_reservees"],
                "derniere_maj": etat["derniere_maj"],
            })

        elif topic == "parking/profil":
            etat["dernier_badge"] = data
            socketio.emit("nouveau_badge", data)

        elif topic == "parking/profils_all":
            socketio.emit("profils_update", data)

        elif topic == "parking/porte":
            ouv = data.get("etat") == "ouverte"
            for p in etat["places"].values():
                p["porte_ouverte"] = ouv
            socketio.emit("porte_update", {"porte_ouverte": ouv})

        elif topic == "parking/alerte":
            etat["alertes"].insert(0, data)
            etat["alertes"] = etat["alertes"][:50]
            socketio.emit("nouvelle_alerte", data)

        elif topic == "parking/ml/result":
            etat["predictions"] = data.get("predictions", [])
            socketio.emit("ml_update", data)

        elif topic == "parking/ml/profil_alerte":
            alerte = {
                "type":       "danger",
                "message":    data.get("message", f"Badge suspect : {data.get('uid','')}"),
                "uid":        data.get("uid", ""),
                "nb_visites": data.get("nb_visites"),
                "timestamp":  data.get("timestamp", datetime.now().isoformat()),
            }
            etat["alertes"].insert(0, alerte)
            etat["alertes"] = etat["alertes"][:50]
            socketio.emit("nouvelle_alerte", alerte)

    except Exception as e:
        log.error("MQTT message error: %s", e)


# Connexion MQTT avec support authentification (HiveMQ Cloud, EMQX, etc.)
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message
if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)
# TLS automatique si port 8883
if MQTT_PORT == 8883:
    mqtt_client.tls_set()
try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()
    log.info("MQTT connecté à %s:%d", MQTT_BROKER, MQTT_PORT)
except Exception as e:
    log.warning("MQTT non disponible au démarrage : %s — dashboard fonctionne quand même", e)


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/admin/reservations")
def admin_reservations():
    return render_template("admin_reservations.html")


@app.route("/api/etat")
def api_etat():
    return jsonify(etat)


@app.route("/api/config")
def api_config():
    return jsonify({"nb_places": NB_PLACES})


@app.route("/api/profils")
def api_profils():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM profils ORDER BY nb_visites DESC").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profil/<uid>")
def api_profil_detail(uid):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        profil = conn.execute("SELECT * FROM profils WHERE uid = ?", (uid,)).fetchone()
        historique = conn.execute("""
            SELECT timestamp, heure, jour_semaine
            FROM rfid_events WHERE uid = ?
            ORDER BY timestamp DESC LIMIT 50
        """, (uid,)).fetchall()
        conn.close()
        if not profil:
            return jsonify({"error": "UID non trouvé"}), 404
        return jsonify({"profil": dict(profil), "historique": [dict(r) for r in historique]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rfid")
def api_rfid():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT e.timestamp, e.uid, e.card_type, e.heure,
                   e.jour_semaine, p.label, p.nb_visites
            FROM rfid_events e
            LEFT JOIN profils p ON e.uid = p.uid
            ORDER BY e.timestamp DESC LIMIT 50
        """).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        stats = {
            "total_mesures":    conn.execute("SELECT COUNT(*) FROM sensor_data").fetchone()[0],
            "taux_occupation":  conn.execute("SELECT ROUND(AVG(occupe)*100,1) FROM sensor_data").fetchone()[0] or 0,
            "total_badges":     conn.execute("SELECT COUNT(*) FROM profils").fetchone()[0],
            "badges_reguliers": conn.execute("SELECT COUNT(*) FROM profils WHERE label='regulier'").fetchone()[0],
            "badges_nouveaux":  conn.execute("SELECT COUNT(*) FROM profils WHERE label='nouveau'").fetchone()[0],
            "total_passages":   conn.execute("SELECT COUNT(*) FROM rfid_events").fetchone()[0],
            "occupation_par_heure": [
                {"heure": r[0], "taux": round(r[1]*100, 1)}
                for r in conn.execute(
                    "SELECT heure, AVG(occupe) FROM sensor_data GROUP BY heure ORDER BY heure"
                ).fetchall()
            ],
            "passages_par_heure": [
                {"heure": r[0], "nb": r[1]}
                for r in conn.execute(
                    "SELECT heure, COUNT(*) FROM rfid_events GROUP BY heure ORDER BY heure"
                ).fetchall()
            ],
            "occupation_par_place": [
                {"place_id": r[0], "taux": round(r[1]*100, 1)}
                for r in conn.execute(
                    "SELECT place_id, AVG(occupe) FROM sensor_data GROUP BY place_id ORDER BY place_id"
                ).fetchall()
            ],
        }
        conn.close()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/predictions")
def api_predictions():
    try:
        model_path = os.path.join(MODEL_DIR, "model_prediction.pkl")
        if not os.path.exists(model_path):
            return jsonify({"predictions": []})
        model = joblib.load(model_path)
        now   = datetime.now()
        preds = []
        for dh in range(12):
            h = (now.hour + dh) % 24
            j = (now.weekday() + (now.hour + dh) // 24) % 7
            row = pd.DataFrame([{
                "heure_sin":    np.sin(2 * np.pi * h / 24),
                "heure_cos":    np.cos(2 * np.pi * h / 24),
                "jour_sin":     np.sin(2 * np.pi * j / 7),
                "jour_cos":     np.cos(2 * np.pi * j / 7),
                "est_weekend":  1 if j >= 5 else 0,
                "heure_pointe": 1 if h in [8, 9, 12, 13, 17, 18] else 0,
                "minute":       now.minute,
            }])
            proba = model.predict_proba(row)[0][1]
            preds.append({"heure": h, "prob_occupe": round(float(proba), 3)})
        return jsonify({"predictions": preds, "timestamp": now.isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/commande", methods=["POST"])
def api_commande():
    data = request.get_json()
    cmd  = data.get("commande", "")
    if cmd in ["OPEN", "CLOSE"]:
        try:
            mqtt_client.publish("parking/commande", json.dumps({"commande": cmd}))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info("Dashboard sur http://0.0.0.0:%d — %d places", port, NB_PLACES)
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
