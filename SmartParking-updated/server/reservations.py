#!/usr/bin/env python3
"""
Module de réservation et tarification — SmartParking
Tarif sans réservation : 10 MAD/h
Tarif avec réservation : 15 MAD/h (+50%)
"""

import sqlite3
import os
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "parking.db")

TARIF_HORAIRE_BASE    = 10.0
TARIF_HORAIRE_RESERVE = 15.0
DUREE_MAX_RESERVATION = 24
AVANCE_MAX_RESERVATION = 72

reservations_bp = Blueprint("reservations", __name__)


def init_reservation_tables():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, place_id INTEGER NOT NULL,
        uid_badge TEXT, nom_client TEXT NOT NULL, telephone TEXT,
        debut TEXT NOT NULL, fin TEXT NOT NULL, duree_heures REAL NOT NULL,
        tarif_heure REAL NOT NULL, montant_total REAL NOT NULL,
        statut TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS tarifs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT UNIQUE NOT NULL,
        valeur REAL NOT NULL, description TEXT, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS passages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, place_id INTEGER NOT NULL,
        uid_badge TEXT, nom_client TEXT, telephone TEXT,
        entree TEXT NOT NULL, sortie TEXT, duree_heures REAL,
        tarif_heure REAL NOT NULL DEFAULT 10.0, montant_total REAL,
        statut TEXT NOT NULL DEFAULT 'en_cours', mode_paiement TEXT,
        paiement_ref TEXT, paiement_ok INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS paiements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, type_source TEXT NOT NULL,
        source_id INTEGER NOT NULL, montant REAL NOT NULL,
        mode TEXT NOT NULL, reference TEXT NOT NULL,
        statut TEXT NOT NULL DEFAULT 'ok', created_at TEXT NOT NULL)""")
    c.execute("""INSERT OR IGNORE INTO tarifs (nom, valeur, description, updated_at)
                 VALUES ('tarif_base', ?, 'Tarif horaire sans réservation (MAD/h)', ?)""",
              (TARIF_HORAIRE_BASE, datetime.now().isoformat()))
    c.execute("""INSERT OR IGNORE INTO tarifs (nom, valeur, description, updated_at)
                 VALUES ('tarif_reserve', ?, 'Tarif horaire avec réservation (MAD/h)', ?)""",
              (TARIF_HORAIRE_RESERVE, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_tarif(nom):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT valeur FROM tarifs WHERE nom = ?", (nom,)).fetchone()
    conn.close()
    return row[0] if row else (TARIF_HORAIRE_BASE if nom == "tarif_base" else TARIF_HORAIRE_RESERVE)


def generer_reference():
    import random, string
    prefix = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"PAY-{prefix}-{suffix}"


def place_est_reservee(place_id, debut=None, fin=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now().isoformat() if debut is None else debut
    fin_check = fin or now
    row = conn.execute("""SELECT * FROM reservations WHERE place_id=? AND statut='active'
        AND debut<=? AND fin>=? ORDER BY debut ASC LIMIT 1""",
        (place_id, fin_check, now)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_places_reservees_maintenant():
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now().isoformat()
    rows = conn.execute("""SELECT DISTINCT place_id FROM reservations
        WHERE statut='active' AND debut<=? AND fin>=?""", (now, now)).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── Tarifs ────────────────────────────────────────────────────────────────────
@reservations_bp.route("/api/tarifs", methods=["GET"])
def api_tarifs():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM tarifs").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@reservations_bp.route("/api/tarifs", methods=["PUT"])
def api_update_tarif():
    data = request.get_json()
    nom, val = data.get("nom"), data.get("valeur")
    if not nom or val is None:
        return jsonify({"error": "nom et valeur requis"}), 400
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE tarifs SET valeur=?, updated_at=? WHERE nom=?",
                 (float(val), datetime.now().isoformat(), nom))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "nom": nom, "valeur": val})


# ── Réservations ──────────────────────────────────────────────────────────────
@reservations_bp.route("/api/reservations", methods=["GET"])
def api_liste_reservations():
    statut = request.args.get("statut", "all")
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    if statut == "all":
        rows = conn.execute("SELECT * FROM reservations ORDER BY created_at DESC LIMIT 100").fetchall()
    else:
        rows = conn.execute("SELECT * FROM reservations WHERE statut=? ORDER BY created_at DESC LIMIT 100", (statut,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@reservations_bp.route("/api/reservations/actives", methods=["GET"])
def api_reservations_actives():
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("""SELECT * FROM reservations WHERE statut='active' AND debut<=? AND fin>=? ORDER BY place_id""", (now, now)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@reservations_bp.route("/api/places/disponibilite", methods=["GET"])
def api_disponibilite():
    from config import NB_PLACES
    debut = request.args.get("debut", datetime.now().isoformat())
    fin   = request.args.get("fin", (datetime.now() + timedelta(hours=1)).isoformat())
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    places = []
    for pid in range(1, NB_PLACES + 1):
        res = conn.execute("""SELECT * FROM reservations WHERE place_id=? AND statut='active'
            AND debut<? AND fin>? ORDER BY debut ASC LIMIT 1""", (pid, fin, debut)).fetchone()
        places.append({"place_id": pid, "disponible": res is None, "reservation": dict(res) if res else None})
    conn.close()
    return jsonify({"places": places, "debut": debut, "fin": fin,
        "tarif_base": get_tarif("tarif_base"), "tarif_reserve": get_tarif("tarif_reserve")})

@reservations_bp.route("/api/reservations", methods=["POST"])
def api_creer_reservation():
    data = request.get_json()
    place_id = data.get("place_id"); nom_client = data.get("nom_client","").strip()
    telephone = data.get("telephone","").strip(); uid_badge = data.get("uid_badge","").strip()
    debut_str = data.get("debut"); fin_str = data.get("fin")
    if not place_id or not nom_client or not debut_str or not fin_str:
        return jsonify({"error": "place_id, nom_client, debut, fin requis"}), 400
    try:
        debut = datetime.fromisoformat(debut_str); fin = datetime.fromisoformat(fin_str)
    except ValueError:
        return jsonify({"error": "Format date invalide (ISO 8601)"}), 400
    now = datetime.now()
    if debut < now - timedelta(minutes=5): return jsonify({"error": "La date de début est dans le passé"}), 400
    if fin <= debut: return jsonify({"error": "La fin doit être après le début"}), 400
    duree_heures = (fin - debut).total_seconds() / 3600
    if duree_heures > DUREE_MAX_RESERVATION: return jsonify({"error": f"Durée max {DUREE_MAX_RESERVATION}h"}), 400
    if (debut - now).total_seconds() / 3600 > AVANCE_MAX_RESERVATION: return jsonify({"error": f"Réservation max {AVANCE_MAX_RESERVATION}h à l'avance"}), 400
    conflit = place_est_reservee(place_id, debut_str, fin_str)
    if conflit: return jsonify({"error": f"Place {place_id} déjà réservée de {conflit['debut']} à {conflit['fin']} par {conflit['nom_client']}"}), 409
    tarif_heure = get_tarif("tarif_reserve"); montant_total = round(duree_heures * tarif_heure, 2)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""INSERT INTO reservations (place_id, uid_badge, nom_client, telephone, debut, fin,
        duree_heures, tarif_heure, montant_total, statut, created_at) VALUES (?,?,?,?,?,?,?,?,?,'active',?)""",
        (place_id, uid_badge or None, nom_client, telephone or None,
         debut.isoformat(), fin.isoformat(), round(duree_heures,2), tarif_heure, montant_total, now.isoformat()))
    reservation_id = cur.lastrowid; conn.commit(); conn.close()
    return jsonify({"ok": True, "id": reservation_id, "place_id": place_id, "nom_client": nom_client,
        "debut": debut.isoformat(), "fin": fin.isoformat(), "duree_heures": round(duree_heures,2),
        "tarif_heure": tarif_heure, "montant_total": montant_total}), 201

@reservations_bp.route("/api/reservations/<int:res_id>/annuler", methods=["POST"])
def api_annuler_reservation(res_id):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM reservations WHERE id=?", (res_id,)).fetchone()
    if not row: conn.close(); return jsonify({"error": "Réservation introuvable"}), 404
    if row["statut"] != "active": conn.close(); return jsonify({"error": "Réservation déjà annulée ou terminée"}), 400
    conn.execute("UPDATE reservations SET statut='annulee' WHERE id=?", (res_id,))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "id": res_id})

@reservations_bp.route("/api/reservations/stats", methods=["GET"])
def api_stats_reservations():
    conn = sqlite3.connect(DB_PATH); now = datetime.now().isoformat()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0],
        "actives": conn.execute("SELECT COUNT(*) FROM reservations WHERE statut='active' AND debut<=? AND fin>=?", (now, now)).fetchone()[0],
        "a_venir": conn.execute("SELECT COUNT(*) FROM reservations WHERE statut='active' AND debut>?", (now,)).fetchone()[0],
        "annulees": conn.execute("SELECT COUNT(*) FROM reservations WHERE statut='annulee'").fetchone()[0],
        "revenus_total": conn.execute("SELECT COALESCE(SUM(montant_total),0) FROM reservations WHERE statut='active'").fetchone()[0],
        "tarif_base": get_tarif("tarif_base"), "tarif_reserve": get_tarif("tarif_reserve"),
    }
    conn.close(); return jsonify(stats)

@reservations_bp.route("/api/reservations/<int:res_id>/payer", methods=["POST"])
def api_payer_reservation(res_id):
    data = request.get_json(); mode = data.get("mode_paiement", "carte")
    carte_numero = data.get("carte_numero", "")
    if mode not in ("carte", "especes"): return jsonify({"error": "mode_paiement doit être 'carte' ou 'especes'"}), 400
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM reservations WHERE id=?", (res_id,)).fetchone()
    if not row: conn.close(); return jsonify({"error": "Réservation introuvable"}), 404
    if mode == "carte":
        numero_clean = carte_numero.replace(" ","").replace("-","")
        if len(numero_clean) < 13 or not numero_clean.isdigit():
            conn.close(); return jsonify({"error": "Numéro de carte invalide"}), 400
    reference = generer_reference()
    conn.execute("""INSERT INTO paiements (type_source, source_id, montant, mode, reference, statut, created_at)
        VALUES ('reservation', ?, ?, ?, ?, 'ok', ?)""",
        (res_id, row["montant_total"], mode, reference, datetime.now().isoformat()))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "reservation_id": res_id, "montant_total": row["montant_total"],
        "mode_paiement": mode, "reference": reference,
        "message": f"✓ Paiement {mode} accepté — {row['montant_total']} MAD — Réf: {reference}"})


# ── Passages sans réservation ─────────────────────────────────────────────────
@reservations_bp.route("/api/passages", methods=["GET"])
def api_liste_passages():
    statut = request.args.get("statut", "all")
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    if statut == "all":
        rows = conn.execute("SELECT * FROM passages ORDER BY created_at DESC LIMIT 100").fetchall()
    else:
        rows = conn.execute("SELECT * FROM passages WHERE statut=? ORDER BY created_at DESC LIMIT 100", (statut,)).fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@reservations_bp.route("/api/passages/en-cours", methods=["GET"])
def api_passages_en_cours():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM passages WHERE statut='en_cours' ORDER BY entree DESC").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@reservations_bp.route("/api/passages", methods=["POST"])
def api_enregistrer_entree():
    data = request.get_json(); place_id = data.get("place_id")
    uid_badge = data.get("uid_badge","").strip(); nom_client = data.get("nom_client","").strip()
    telephone = data.get("telephone","").strip()
    if not place_id: return jsonify({"error": "place_id requis"}), 400
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    existant = conn.execute("SELECT id FROM passages WHERE place_id=? AND statut='en_cours'", (place_id,)).fetchone()
    if existant: conn.close(); return jsonify({"error": f"Passage déjà en cours sur la place {place_id}"}), 409
    tarif_heure = get_tarif("tarif_base"); now = datetime.now()
    cur = conn.execute("""INSERT INTO passages (place_id, uid_badge, nom_client, telephone, entree, tarif_heure, statut, created_at)
        VALUES (?,?,?,?,?,?,'en_cours',?)""",
        (place_id, uid_badge or None, nom_client or None, telephone or None, now.isoformat(), tarif_heure, now.isoformat()))
    passage_id = cur.lastrowid; conn.commit(); conn.close()
    return jsonify({"ok": True, "id": passage_id, "place_id": place_id, "entree": now.isoformat(),
        "tarif_heure": tarif_heure, "message": f"Entrée enregistrée — tarif {tarif_heure} MAD/h"}), 201

@reservations_bp.route("/api/passages/<int:passage_id>/calculer", methods=["GET"])
def api_calculer_passage(passage_id):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM passages WHERE id=?", (passage_id,)).fetchone()
    conn.close()
    if not row: return jsonify({"error": "Passage introuvable"}), 404
    entree = datetime.fromisoformat(row["entree"]); now = datetime.now()
    duree = (now - entree).total_seconds() / 3600
    duree_fact = max(duree, 0.5); montant = round(duree_fact * row["tarif_heure"], 2)
    return jsonify({"id": passage_id, "place_id": row["place_id"], "nom_client": row["nom_client"],
        "entree": row["entree"], "duree_heures": round(duree, 2), "duree_facturee": round(duree_fact, 2),
        "tarif_heure": row["tarif_heure"], "montant_total": montant, "statut": row["statut"]})

@reservations_bp.route("/api/passages/<int:passage_id>/payer", methods=["POST"])
def api_payer_passage(passage_id):
    data = request.get_json(); mode = data.get("mode_paiement", "carte")
    carte_numero = data.get("carte_numero", "")
    if mode not in ("carte", "especes"): return jsonify({"error": "mode_paiement doit être 'carte' ou 'especes'"}), 400
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM passages WHERE id=?", (passage_id,)).fetchone()
    if not row: conn.close(); return jsonify({"error": "Passage introuvable"}), 404
    if row["statut"] != "en_cours": conn.close(); return jsonify({"error": "Ce passage n'est pas en cours"}), 400
    if mode == "carte":
        numero_clean = carte_numero.replace(" ","").replace("-","")
        if len(numero_clean) < 13 or not numero_clean.isdigit():
            conn.close(); return jsonify({"error": "Numéro de carte invalide"}), 400
    entree = datetime.fromisoformat(row["entree"]); now = datetime.now()
    duree = (now - entree).total_seconds() / 3600
    duree_fact = max(duree, 0.5); montant = round(duree_fact * row["tarif_heure"], 2)
    reference = generer_reference()
    conn.execute("""UPDATE passages SET sortie=?, duree_heures=?, montant_total=?,
        statut='payé', mode_paiement=?, paiement_ref=?, paiement_ok=1 WHERE id=?""",
        (now.isoformat(), round(duree_fact,2), montant, mode, reference, passage_id))
    conn.execute("""INSERT INTO paiements (type_source, source_id, montant, mode, reference, statut, created_at)
        VALUES ('passage', ?, ?, ?, ?, 'ok', ?)""",
        (passage_id, montant, mode, reference, now.isoformat()))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "passage_id": passage_id, "place_id": row["place_id"],
        "entree": row["entree"], "sortie": now.isoformat(), "duree_heures": round(duree_fact,2),
        "tarif_heure": row["tarif_heure"], "montant_total": montant,
        "mode_paiement": mode, "reference": reference,
        "message": f"✓ Paiement {mode} accepté — {montant} MAD — Réf: {reference}"})


# ── Stats paiements ───────────────────────────────────────────────────────────
@reservations_bp.route("/api/paiements", methods=["GET"])
def api_liste_paiements():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM paiements ORDER BY created_at DESC LIMIT 200").fetchall()
    conn.close(); return jsonify([dict(r) for r in rows])

@reservations_bp.route("/api/paiements/stats", methods=["GET"])
def api_stats_paiements():
    conn = sqlite3.connect(DB_PATH)
    stats = {
        "total_paiements": conn.execute("SELECT COUNT(*) FROM paiements").fetchone()[0],
        "revenus_reservations": conn.execute("SELECT COALESCE(SUM(montant),0) FROM paiements WHERE type_source='reservation'").fetchone()[0],
        "revenus_passages": conn.execute("SELECT COALESCE(SUM(montant),0) FROM paiements WHERE type_source='passage'").fetchone()[0],
        "revenus_total": conn.execute("SELECT COALESCE(SUM(montant),0) FROM paiements").fetchone()[0],
        "paiements_carte": conn.execute("SELECT COUNT(*) FROM paiements WHERE mode='carte'").fetchone()[0],
        "paiements_especes": conn.execute("SELECT COUNT(*) FROM paiements WHERE mode='especes'").fetchone()[0],
        "passages_en_cours": conn.execute("SELECT COUNT(*) FROM passages WHERE statut='en_cours'").fetchone()[0],
        "passages_total": conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
        "tarif_base": get_tarif("tarif_base"), "tarif_reserve": get_tarif("tarif_reserve"),
    }
    conn.close(); return jsonify(stats)
