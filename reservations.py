#!/usr/bin/env python3
"""
Module de réservation et tarification — SmartParking
Tarif de base : 10 MAD/h — Tarif avec réservation : 15 MAD/h (+50%)
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "parking.db")

# ─── Tarification ────────────────────────────────────────────────────────────
TARIF_HORAIRE_BASE       = 10.0   # MAD/heure sans réservation
TARIF_HORAIRE_RESERVE    = 15.0   # MAD/heure avec réservation (+50%)
DUREE_MAX_RESERVATION    = 24     # heures max de réservation
AVANCE_MAX_RESERVATION   = 72     # on peut réserver jusqu'à 72h à l'avance

reservations_bp = Blueprint("reservations", __name__)


# ─── Init DB ──────────────────────────────────────────────────────────────────
def init_reservation_tables():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS reservations (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        place_id      INTEGER NOT NULL,
        uid_badge     TEXT,
        nom_client    TEXT    NOT NULL,
        telephone     TEXT,
        debut         TEXT    NOT NULL,
        fin           TEXT    NOT NULL,
        duree_heures  REAL    NOT NULL,
        tarif_heure   REAL    NOT NULL,
        montant_total REAL    NOT NULL,
        statut        TEXT    NOT NULL DEFAULT 'active',
        created_at    TEXT    NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS tarifs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nom         TEXT UNIQUE NOT NULL,
        valeur      REAL NOT NULL,
        description TEXT,
        updated_at  TEXT NOT NULL
    )""")

    # Insérer les tarifs par défaut s'ils n'existent pas
    c.execute("""INSERT OR IGNORE INTO tarifs (nom, valeur, description, updated_at)
                 VALUES ('tarif_base', ?, 'Tarif horaire sans réservation (MAD/h)', ?)""",
              (TARIF_HORAIRE_BASE, datetime.now().isoformat()))
    c.execute("""INSERT OR IGNORE INTO tarifs (nom, valeur, description, updated_at)
                 VALUES ('tarif_reserve', ?, 'Tarif horaire avec réservation (MAD/h)', ?)""",
              (TARIF_HORAIRE_RESERVE, datetime.now().isoformat()))

    conn.commit()
    conn.close()


# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_tarif(nom):
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute("SELECT valeur FROM tarifs WHERE nom = ?", (nom,)).fetchone()
    conn.close()
    return row[0] if row else (TARIF_HORAIRE_BASE if nom == "tarif_base" else TARIF_HORAIRE_RESERVE)


def place_est_reservee(place_id: int, debut: str = None, fin: str = None) -> dict | None:
    """
    Retourne la réservation active pour une place à un instant donné.
    Par défaut vérifie l'instant présent.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    now = datetime.now().isoformat() if debut is None else debut
    fin_check = fin or now

    row = conn.execute("""
        SELECT * FROM reservations
        WHERE place_id = ?
          AND statut = 'active'
          AND debut <= ?
          AND fin   >= ?
        ORDER BY debut ASC LIMIT 1
    """, (place_id, fin_check, now)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_places_reservees_maintenant() -> set:
    """Retourne l'ensemble des place_id actuellement réservés."""
    conn = sqlite3.connect(DB_PATH)
    now  = datetime.now().isoformat()
    rows = conn.execute("""
        SELECT DISTINCT place_id FROM reservations
        WHERE statut = 'active' AND debut <= ? AND fin >= ?
    """, (now, now)).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ─── Routes API ───────────────────────────────────────────────────────────────

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
    nom  = data.get("nom")
    val  = data.get("valeur")
    if not nom or val is None:
        return jsonify({"error": "nom et valeur requis"}), 400
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE tarifs SET valeur=?, updated_at=? WHERE nom=?",
                 (float(val), datetime.now().isoformat(), nom))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "nom": nom, "valeur": val})


@reservations_bp.route("/api/reservations", methods=["GET"])
def api_liste_reservations():
    statut = request.args.get("statut", "all")
    conn   = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if statut == "all":
        rows = conn.execute(
            "SELECT * FROM reservations ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reservations WHERE statut=? ORDER BY created_at DESC LIMIT 100",
            (statut,)
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@reservations_bp.route("/api/reservations/actives", methods=["GET"])
def api_reservations_actives():
    """Places actuellement réservées — utilisé par le dashboard et l'app mobile."""
    now  = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM reservations
        WHERE statut = 'active' AND debut <= ? AND fin >= ?
        ORDER BY place_id
    """, (now, now)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@reservations_bp.route("/api/places/disponibilite", methods=["GET"])
def api_disponibilite():
    """
    Retourne la disponibilité de chaque place avec son statut de réservation.
    Paramètres optionnels : debut et fin (ISO) pour vérifier une plage.
    """
    from config import NB_PLACES
    debut = request.args.get("debut", datetime.now().isoformat())
    fin   = request.args.get("fin",   (datetime.now() + timedelta(hours=1)).isoformat())

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    places = []
    for pid in range(1, NB_PLACES + 1):
        res = conn.execute("""
            SELECT * FROM reservations
            WHERE place_id = ?
              AND statut = 'active'
              AND debut < ?
              AND fin   > ?
            ORDER BY debut ASC LIMIT 1
        """, (pid, fin, debut)).fetchone()

        places.append({
            "place_id":   pid,
            "disponible": res is None,
            "reservation": dict(res) if res else None
        })

    conn.close()
    return jsonify({
        "places": places,
        "debut":  debut,
        "fin":    fin,
        "tarif_base":    get_tarif("tarif_base"),
        "tarif_reserve": get_tarif("tarif_reserve"),
    })


@reservations_bp.route("/api/reservations", methods=["POST"])
def api_creer_reservation():
    data        = request.get_json()
    place_id    = data.get("place_id")
    nom_client  = data.get("nom_client", "").strip()
    telephone   = data.get("telephone", "").strip()
    uid_badge   = data.get("uid_badge", "").strip()
    debut_str   = data.get("debut")
    fin_str     = data.get("fin")

    # Validations basiques
    if not place_id or not nom_client or not debut_str or not fin_str:
        return jsonify({"error": "place_id, nom_client, debut, fin requis"}), 400

    try:
        debut = datetime.fromisoformat(debut_str)
        fin   = datetime.fromisoformat(fin_str)
    except ValueError:
        return jsonify({"error": "Format date invalide (ISO 8601)"}), 400

    now = datetime.now()
    if debut < now - timedelta(minutes=5):
        return jsonify({"error": "La date de début est dans le passé"}), 400
    if fin <= debut:
        return jsonify({"error": "La fin doit être après le début"}), 400

    duree_heures = (fin - debut).total_seconds() / 3600
    if duree_heures > DUREE_MAX_RESERVATION:
        return jsonify({"error": f"Durée max {DUREE_MAX_RESERVATION}h"}), 400
    if (debut - now).total_seconds() / 3600 > AVANCE_MAX_RESERVATION:
        return jsonify({"error": f"Réservation max {AVANCE_MAX_RESERVATION}h à l'avance"}), 400

    # Vérifier conflit
    conflit = place_est_reservee(place_id, debut_str, fin_str)
    if conflit:
        return jsonify({
            "error": f"Place {place_id} déjà réservée de {conflit['debut']} à {conflit['fin']} par {conflit['nom_client']}"
        }), 409

    tarif_heure   = get_tarif("tarif_reserve")
    montant_total = round(duree_heures * tarif_heure, 2)

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.execute("""
        INSERT INTO reservations
        (place_id, uid_badge, nom_client, telephone, debut, fin,
         duree_heures, tarif_heure, montant_total, statut, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,'active',?)
    """, (place_id, uid_badge or None, nom_client, telephone or None,
          debut.isoformat(), fin.isoformat(),
          round(duree_heures, 2), tarif_heure, montant_total,
          now.isoformat()))
    reservation_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "id":            reservation_id,
        "place_id":      place_id,
        "nom_client":    nom_client,
        "debut":         debut.isoformat(),
        "fin":           fin.isoformat(),
        "duree_heures":  round(duree_heures, 2),
        "tarif_heure":   tarif_heure,
        "montant_total": montant_total,
    }), 201


@reservations_bp.route("/api/reservations/<int:res_id>/annuler", methods=["POST"])
def api_annuler_reservation(res_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row  = conn.execute("SELECT * FROM reservations WHERE id=?", (res_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Réservation introuvable"}), 404
    if row["statut"] != "active":
        conn.close()
        return jsonify({"error": "Réservation déjà annulée ou terminée"}), 400

    conn.execute("UPDATE reservations SET statut='annulee' WHERE id=?", (res_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": res_id})


@reservations_bp.route("/api/reservations/stats", methods=["GET"])
def api_stats_reservations():
    conn = sqlite3.connect(DB_PATH)
    now  = datetime.now().isoformat()
    stats = {
        "total":          conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0],
        "actives":        conn.execute("SELECT COUNT(*) FROM reservations WHERE statut='active' AND debut<=? AND fin>=?", (now, now)).fetchone()[0],
        "a_venir":        conn.execute("SELECT COUNT(*) FROM reservations WHERE statut='active' AND debut>?", (now,)).fetchone()[0],
        "annulees":       conn.execute("SELECT COUNT(*) FROM reservations WHERE statut='annulee'").fetchone()[0],
        "revenus_total":  conn.execute("SELECT COALESCE(SUM(montant_total),0) FROM reservations WHERE statut='active'").fetchone()[0],
        "tarif_base":     get_tarif("tarif_base"),
        "tarif_reserve":  get_tarif("tarif_reserve"),
    }
    conn.close()
    return jsonify(stats)
