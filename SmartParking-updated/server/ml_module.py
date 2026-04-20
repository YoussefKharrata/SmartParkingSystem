#!/usr/bin/env python3

import sqlite3, json, time, logging, os, sys, random, signal
from datetime import datetime, timedelta

import numpy  as np
import pandas as pd
from sklearn.ensemble        import RandomForestClassifier, IsolationForest
from sklearn.cluster         import KMeans
from sklearn.preprocessing   import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics         import accuracy_score
import joblib
import paho.mqtt.client as mqtt
from config import NB_PLACES, MQTT_BROKER, MQTT_PORT

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(BASE_DIR, "data", "parking.db")
MODEL_DIR     = os.path.join(BASE_DIR, "models")
DATASET_PATH  = os.path.join(BASE_DIR, "dataset.csv")
LOG_DIR       = os.path.join(BASE_DIR, "logs")
RETRAIN_EVERY = 3600
MIN_SAMPLES   = 100

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "ml.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)


def load_dataset_csv() -> pd.DataFrame | None:
    if not os.path.exists(DATASET_PATH):
        return None
    df = pd.read_csv(DATASET_PATH)
    df = df[df["Occupancy"] >= 0].copy()
    top_id = df["SystemCodeNumber"].value_counts().index[0]
    df = df[df["SystemCodeNumber"] == top_id].copy()
    df["LastUpdated"] = pd.to_datetime(df["LastUpdated"])
    df["heure"]        = df["LastUpdated"].dt.hour
    df["minute"]       = df["LastUpdated"].dt.minute
    df["jour_semaine"] = df["LastUpdated"].dt.weekday
    df["occupancy_pct"]= (df["Occupancy"] / df["Capacity"]).clip(0, 1)
    df["occupe"]       = (df["occupancy_pct"] >= 0.5).astype(int)
    df["distance"]     = df["occupe"].apply(
        lambda o: random.uniform(3, 15) if o else random.uniform(25, 120)
    )
    df["place_id"] = 1
    log.info("dataset.csv chargé : parking %s, %d lignes", top_id, len(df))
    return df


def generate_sensor_data(nb_jours=30):
    log.info("Génération données simulées (%d jours, %d places)...", nb_jours, NB_PLACES)
    records = []
    t = datetime.now() - timedelta(days=nb_jours)
    while t < datetime.now():
        h  = t.hour
        wd = t.weekday()
        wk = wd >= 5
        if   0  <= h < 6:  p_base = 0.02
        elif 8  <= h < 10: p_base = 0.85 if not wk else 0.30
        elif 12 <= h < 14: p_base = 0.80 if not wk else 0.40
        elif 17 <= h < 19: p_base = 0.75 if not wk else 0.25
        else:               p_base = 0.30
        for place_id in range(1, NB_PLACES + 1):
            p      = min(1.0, p_base * random.uniform(0.7, 1.3))
            occupe = 1 if random.random() < p else 0
            records.append({
                "timestamp": t.isoformat(), "place_id": place_id,
                "heure": h, "minute": t.minute, "jour_semaine": wd,
                "distance": random.uniform(3, 15) if occupe else random.uniform(25, 120),
                "occupe": occupe, "porte_ouverte": occupe
            })
        t += timedelta(minutes=1)
    return pd.DataFrame(records)


def generate_rfid_data(nb_jours=30, nb_badges=10):
    records = []
    badges  = [f"UID_{i:03d}" for i in range(nb_badges)]
    profils_badges = {}
    for b in badges:
        profils_badges[b] = {
            "heures_habituelles": random.sample(range(7, 20), k=random.randint(2, 5)),
            "jours_habituels":    random.sample(range(0, 7),  k=random.randint(3, 6)),
            "suspect":            random.random() < 0.1,
        }
    t = datetime.now() - timedelta(days=nb_jours)
    while t < datetime.now():
        for badge, profil in profils_badges.items():
            if (t.hour in profil["heures_habituelles"] and
                t.weekday() in profil["jours_habituels"] and
                random.random() < 0.3):
                records.append({
                    "timestamp":     t.isoformat(),
                    "uid":           badge,
                    "card_type":     "MIFARE 1KB",
                    "action":        "refuse_parking_plein" if profil["suspect"] and random.random() < 0.3 else "entree",
                    "heure":         t.hour,
                    "jour_semaine":  t.weekday(),
                    "porte_ouverte": 0 if (profil["suspect"] and random.random() < 0.3) else 1,
                })
        t += timedelta(hours=1)
    return pd.DataFrame(records)


def init_db_ml(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS sensor_data (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT,
        place_id      INTEGER DEFAULT 1,
        heure         INTEGER,
        minute        INTEGER,
        jour_semaine  INTEGER,
        distance      REAL,
        occupe        INTEGER,
        porte_ouverte INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS rfid_events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT,
        uid           TEXT,
        card_type     TEXT,
        heure         INTEGER,
        jour_semaine  INTEGER,
        porte_ouverte INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS profils (
        uid               TEXT PRIMARY KEY,
        premiere_visite   TEXT,
        derniere_visite   TEXT,
        nb_visites        INTEGER DEFAULT 0,
        heures_frequentes TEXT,
        jours_frequents   TEXT,
        label             TEXT DEFAULT 'inconnu',
        card_type         TEXT
    )""")
    conn.commit()


def injecter_donnees(df_sensor, df_rfid):
    conn = sqlite3.connect(DB_PATH)
    init_db_ml(conn)
    df_sensor.to_sql("sensor_data", conn, if_exists="replace", index=False)
    df_rfid[["timestamp", "uid", "card_type", "heure", "jour_semaine", "porte_ouverte"]].to_sql(
        "rfid_events", conn, if_exists="replace", index=False
    )
    now = datetime.now().isoformat()
    for uid, grp in df_rfid.groupby("uid"):
        nb     = len(grp)
        heures = json.dumps(grp["heure"].value_counts().to_dict())
        jours  = json.dumps(grp["jour_semaine"].value_counts().to_dict())
        label  = "regulier" if nb >= 10 else "occasionnel" if nb >= 3 else "nouveau"
        conn.execute("""
            INSERT OR REPLACE INTO profils
            (uid, premiere_visite, derniere_visite, nb_visites,
             heures_frequentes, jours_frequents, label, card_type)
            VALUES (?,?,?,?,?,?,?,?)
        """, (uid, now, now, nb, heures, jours, label, "MIFARE 1KB"))
    conn.commit()
    conn.close()
    log.info("Données injectées.")


FEATURES = ["heure_sin", "heure_cos", "jour_sin", "jour_cos", "est_weekend", "heure_pointe", "minute"]


def preparer_features(df):
    df = df.copy()
    df["heure_sin"]    = np.sin(2 * np.pi * df["heure"] / 24)
    df["heure_cos"]    = np.cos(2 * np.pi * df["heure"] / 24)
    df["jour_sin"]     = np.sin(2 * np.pi * df["jour_semaine"] / 7)
    df["jour_cos"]     = np.cos(2 * np.pi * df["jour_semaine"] / 7)
    df["est_weekend"]  = (df["jour_semaine"] >= 5).astype(int)
    df["heure_pointe"] = df["heure"].apply(lambda h: 1 if h in [8, 9, 12, 13, 17, 18] else 0)
    return df


def train_models():
    df_csv = load_dataset_csv()

    conn = sqlite3.connect(DB_PATH)
    init_db_ml(conn)

    if df_csv is not None and len(df_csv) >= MIN_SAMPLES:
        existing = 0
        try:
            existing = conn.execute("SELECT COUNT(*) FROM sensor_data").fetchone()[0]
        except Exception:
            pass
        if existing == 0:
            df_sensor = df_csv[["place_id", "heure", "minute", "jour_semaine", "distance", "occupe"]].copy()
            df_sensor["porte_ouverte"] = df_sensor["occupe"]
            df_sensor["timestamp"]     = datetime.now().isoformat()
            df_sensor.to_sql("sensor_data", conn, if_exists="replace", index=False)
            conn.commit()
            log.info("Entraînement depuis dataset.csv (%d lignes)", len(df_sensor))
        else:
            log.info("Entraînement depuis SQLite (%d lignes réelles)", existing)
        df_sensor = pd.read_sql("SELECT * FROM sensor_data", conn)
    else:
        try:
            df_sensor = pd.read_sql("SELECT * FROM sensor_data", conn)
        except Exception:
            df_sensor = pd.DataFrame()

        if len(df_sensor) < MIN_SAMPLES:
            log.warning("Données insuffisantes — génération simulée...")
            conn.close()
            df_s = generate_sensor_data()
            df_r = generate_rfid_data()
            injecter_donnees(df_s, df_r)
            conn = sqlite3.connect(DB_PATH)
            df_sensor = pd.read_sql("SELECT * FROM sensor_data", conn)

    if "place_id" not in df_sensor.columns:
        df_sensor["place_id"] = 1

    try:
        df_rfid = pd.read_sql("SELECT * FROM rfid_events", conn)
    except Exception:
        df_rfid = pd.DataFrame(columns=["uid", "heure", "jour_semaine", "porte_ouverte"])
    conn.close()

    df = preparer_features(df_sensor)
    X, y = df[FEATURES], df["occupe"]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
    m1 = RandomForestClassifier(n_estimators=100, max_depth=10,
                                 random_state=42, class_weight="balanced")
    m1.fit(Xtr, ytr)
    acc = accuracy_score(yte, m1.predict(Xte))
    log.info("Précision prédiction : %.1f%%", acc * 100)
    joblib.dump(m1, f"{MODEL_DIR}/model_prediction.pkl")

    if len(df_rfid) >= 20 and "uid" in df_rfid.columns:
        if "action" not in df_rfid.columns:
            df_rfid["action"] = df_rfid["porte_ouverte"].apply(
                lambda v: "entree" if v else "refuse_parking_plein"
            )
        stats = df_rfid.groupby("uid").agg(
            nb_visites    = ("uid",    "count"),
            heure_moy     = ("heure",  "mean"),
            heure_std     = ("heure",  "std"),
            nb_refus      = ("action", lambda x: (x == "refuse_parking_plein").sum()),
            nb_jours_uniq = ("jour_semaine", "nunique"),
        ).fillna(0).reset_index()

        scaler   = StandardScaler()
        features = ["nb_visites", "heure_moy", "heure_std", "nb_refus", "nb_jours_uniq"]
        X_badges = scaler.fit_transform(stats[features])
        km = KMeans(n_clusters=min(3, len(stats)), random_state=42, n_init=10)
        stats["cluster"] = km.fit_predict(X_badges)

        conn = sqlite3.connect(DB_PATH)
        for _, row in stats.iterrows():
            conn.execute(
                "UPDATE profils SET label=? WHERE uid=?",
                (f"cluster_{int(row['cluster'])}", row["uid"])
            )
        conn.commit()
        conn.close()
        joblib.dump({"kmeans": km, "scaler": scaler, "features": features},
                    f"{MODEL_DIR}/model_clustering.pkl")
        log.info("Clustering badges : %d clusters pour %d badges", km.n_clusters, len(stats))
    else:
        log.info("KMeans ignoré : %d événements RFID (minimum 20)", len(df_rfid))

    m3 = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
    X_norm = df[df["occupe"] == 0][["distance", "heure", "jour_semaine"]]
    if len(X_norm) > 10:
        m3.fit(X_norm)
        joblib.dump(m3, f"{MODEL_DIR}/model_anomalie.pkl")

    stats_out = {
        "derniere_entrainement": datetime.now().isoformat(),
        "nb_sensor": int(len(df_sensor)),
        "nb_rfid":   int(len(df_rfid)),
        "precision": round(float(acc), 4),
        "nb_places": NB_PLACES,
        "source":    "dataset.csv" if (df_csv is not None and len(df_csv) >= MIN_SAMPLES) else "sqlite/simulated",
    }
    with open(f"{MODEL_DIR}/stats.json", "w") as f:
        json.dump(stats_out, f, indent=2)

    return m1, acc


def charger_modeles():
    path = f"{MODEL_DIR}/model_prediction.pkl"
    if not os.path.exists(path):
        log.info("Modèles absents — entraînement initial...")
        return train_models()
    m1 = joblib.load(path)
    log.info("Modèles chargés.")
    return m1, None


def predict_occupation(model, heure, minute, jour_semaine):
    preds = []
    for dh in range(12):
        h = (heure + dh) % 24
        j = (jour_semaine + (heure + dh) // 24) % 7
        row = pd.DataFrame([{
            "heure_sin":    np.sin(2 * np.pi * h / 24),
            "heure_cos":    np.cos(2 * np.pi * h / 24),
            "jour_sin":     np.sin(2 * np.pi * j / 7),
            "jour_cos":     np.cos(2 * np.pi * j / 7),
            "est_weekend":  1 if j >= 5 else 0,
            "heure_pointe": 1 if h in [8, 9, 12, 13, 17, 18] else 0,
            "minute":       minute,
        }])
        proba = model.predict_proba(row)[0][1]
        preds.append({"heure": h, "prob_occupe": round(float(proba), 3)})
    return preds


def run_ml_server():
    log.info("=== Démarrage Module ML — %d places ===", NB_PLACES)
    model, _ = charger_modeles()
    dernier  = time.time()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, u, f, rc, props):
        log.info("ML connecté MQTT")
        c.subscribe([("parking/sensor", 0), ("parking/rfid", 0)])

    def on_message(c, u, msg):
        nonlocal model, dernier
        try:
            data = json.loads(msg.payload.decode())
            now  = datetime.now()

            if msg.topic == "parking/sensor":
                place_id = data.get("place_id", 1)
                preds = predict_occupation(model, now.hour, now.minute, now.weekday())
                c.publish("parking/ml/result", json.dumps({
                    "timestamp":   now.isoformat(),
                    "place_id":    place_id,
                    "predictions": preds,
                }))

            elif msg.topic == "parking/rfid":
                profil = data.get("profil", {})
                uid    = data.get("uid", "")
                if profil.get("suspect"):
                    c.publish("parking/ml/profil_alerte", json.dumps({
                        "uid":        uid,
                        "nb_visites": profil.get("nb_visites"),
                        "nb_refus":   profil.get("nb_refus"),
                        "message":    f"Badge {uid} présente un comportement anormal",
                        "timestamp":  now.isoformat(),
                    }))

            if time.time() - dernier > RETRAIN_EVERY:
                log.info("Re-entraînement...")
                model, acc = train_models()
                dernier = time.time()
                c.publish("parking/ml/retrain", json.dumps({
                    "timestamp": now.isoformat(), "precision": acc
                }))
        except Exception as e:
            log.error("Erreur ML : %s", e)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    def stop(s, f):
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT,  stop)
    signal.signal(signal.SIGTERM, stop)

    log.info("ML en écoute...")
    client.loop_forever()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--generate-data", action="store_true")
    p.add_argument("--train-only",    action="store_true")
    p.add_argument("--jours", type=int, default=30)
    args = p.parse_args()

    if args.generate_data:
        df_s = generate_sensor_data(args.jours)
        df_r = generate_rfid_data(args.jours)
        injecter_donnees(df_s, df_r)
        print(f"Généré : {len(df_s)} mesures capteur + {len(df_r)} événements RFID")
    elif args.train_only:
        _, acc = train_models()
        print(f"Modèles entraînés — précision : {acc:.1%}")
    else:
        run_ml_server()