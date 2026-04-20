# SmartParking — Extension Réservation & Tarification

## Ce qui a été ajouté

### Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `server/reservations.py` | Module Flask Blueprint — toutes les routes API de réservation et tarification |
| `server/templates/admin_reservations.html` | Interface web admin pour gérer les réservations |
| `mobile_app/lib/main.dart` | Application Flutter (Dart) pour réserver depuis un mobile |
| `mobile_app/pubspec.yaml` | Dépendances Flutter |

### Fichiers modifiés

| Fichier | Modification |
|---|---|
| `server/dashboard.py` | Intégration du Blueprint, état `reservee` des places, compteur réservées |
| `server/mqtt_bridge.py` | Init des tables réservation/tarifs en base |
| `server/templates/dashboard.html` | Affichage 🟡 RÉSERVÉE, compteur "Réservées", lien Admin |

---

## Tarification

- **Tarif sans réservation** : 10 MAD/h (modifiable en admin)
- **Tarif avec réservation** : 15 MAD/h (+50%) (modifiable en admin)
- Les tarifs sont stockés en base SQLite et modifiables depuis `/admin/reservations`

---

## Nouvelles tables SQLite

```sql
-- Réservations
reservations (id, place_id, uid_badge, nom_client, telephone, debut, fin,
              duree_heures, tarif_heure, montant_total, statut, created_at)

-- Tarifs configurables
tarifs (id, nom, valeur, description, updated_at)
```

---

## Routes API ajoutées

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/tarifs` | Lire les tarifs |
| PUT | `/api/tarifs` | Modifier un tarif |
| GET | `/api/places/disponibilite?debut=&fin=` | Disponibilité des places pour une plage |
| GET | `/api/reservations` | Liste des réservations |
| POST | `/api/reservations` | Créer une réservation |
| GET | `/api/reservations/actives` | Réservations actives maintenant |
| POST | `/api/reservations/<id>/annuler` | Annuler une réservation |
| GET | `/api/reservations/stats` | Statistiques |

---

## Dashboard — Nouveautés

- Les places réservées apparaissent en **🟡 RÉSERVÉE** (orange)
- Un compteur "Réservées" s'ajoute aux compteurs existants
- Lien vers l'admin en haut à droite de la grille des places
- Le workflow Arduino/MQTT existant n'est **pas modifié**

---

## Interface Admin Web

Accessible sur : `http://<ip-serveur>:5000/admin/reservations`

- Vue des stats (actives, à venir, revenus)
- Modification des tarifs en temps réel
- Création manuelle de réservations
- Annulation de réservations
- Filtres : Toutes / Actives / Annulées
- Rafraîchissement automatique toutes les 30 secondes

---

## Application Mobile (Flutter/Dart)

### Configuration

Modifier la constante `kServerUrl` dans `mobile_app/lib/main.dart` :
```dart
const String kServerUrl = 'http://192.168.1.100:5000'; // IP de votre serveur
```

### Installation

```bash
cd mobile_app
flutter pub get
flutter run            # debug sur émulateur/device
flutter build apk      # APK Android
flutter build ios      # iOS (nécessite macOS + Xcode)
```

### Fonctionnalités

1. **Onglet Réserver**
   - Sélection de la date/heure d'arrivée et de départ
   - Affichage du montant estimé en temps réel
   - Liste des places avec statut (Disponible / Réservée)
   - Formulaire de réservation (nom, téléphone, UID badge RFID optionnel)
   - Confirmation avec récapitulatif

2. **Onglet Mes réservations**
   - Recherche par nom client
   - Affichage des réservations actives et à venir
   - Annulation possible

### Dépendances Flutter

```yaml
http: ^1.2.0              # Appels API REST
intl: ^0.19.0             # Formatage dates (français)
shared_preferences: ^2.2.2 # Mémorisation du nom/téléphone
```

---

## Logique métier

- Une place **réservée** mais pas encore **occupée** physiquement → statut RÉSERVÉE (🟡)
- Une place **occupée** physiquement → statut OCCUPÉE (🔴), même si réservée
- Le workflow RFID/capteurs Arduino reste intact — la réservation est une couche additionnelle
- Conflit de réservation : le serveur renvoie une erreur 409 si une place est déjà réservée sur la plage demandée
