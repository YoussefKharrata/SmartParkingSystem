import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

// ─── Configuration ────────────────────────────────────────────────────────────
// Remplacer par l'adresse IP du serveur Raspberry Pi / PC sur le réseau local
const String kServerUrl = 'http://10.1.153.155:5000';

void main() {
  runApp(const SmartParkingApp());
}

// ─── Thème ────────────────────────────────────────────────────────────────────
final ThemeData kDarkTheme = ThemeData(
  brightness: Brightness.dark,
  scaffoldBackgroundColor: const Color(0xFF0D0F14),
  colorScheme: const ColorScheme.dark(
    primary:   Color(0xFF00B0FF),
    secondary: Color(0xFF00E676),
    error:     Color(0xFFFF1744),
    surface:   Color(0xFF161920),
  ),
  cardColor: const Color(0xFF161920),
  dividerColor: const Color(0xFF222733),
  fontFamily: 'Roboto',
  useMaterial3: true,
);

// ─── Couleurs constantes ──────────────────────────────────────────────────────
const kGreen  = Color(0xFF00E676);
const kRed    = Color(0xFFFF1744);
const kBlue   = Color(0xFF00B0FF);
const kAmber  = Color(0xFFFFAB00);
const kCard   = Color(0xFF161920);
const kBorder = Color(0xFF222733);
const kDim    = Color(0xFF6B7280);

// ─── Modèles ──────────────────────────────────────────────────────────────────
class PlaceInfo {
  final int id;
  final bool disponible;
  final Reservation? reservation;

  PlaceInfo({required this.id, required this.disponible, this.reservation});

  factory PlaceInfo.fromJson(Map<String, dynamic> j) => PlaceInfo(
    id:           j['place_id'] as int,
    disponible:   j['disponible'] as bool,
    reservation:  j['reservation'] != null
                  ? Reservation.fromJson(j['reservation']) : null,
  );
}

class Reservation {
  final int id;
  final int placeId;
  final String nomClient;
  final String? telephone;
  final String? uidBadge;
  final DateTime debut;
  final DateTime fin;
  final double dureeHeures;
  final double tarifHeure;
  final double montantTotal;
  final String statut;

  Reservation({
    required this.id, required this.placeId, required this.nomClient,
    this.telephone, this.uidBadge,
    required this.debut, required this.fin,
    required this.dureeHeures, required this.tarifHeure, required this.montantTotal,
    required this.statut,
  });

  factory Reservation.fromJson(Map<String, dynamic> j) => Reservation(
    id:           j['id'] as int,
    placeId:      j['place_id'] as int,
    nomClient:    j['nom_client'] as String,
    telephone:    j['telephone'] as String?,
    uidBadge:     j['uid_badge'] as String?,
    debut:        DateTime.parse(j['debut'] as String),
    fin:          DateTime.parse(j['fin'] as String),
    dureeHeures:  (j['duree_heures'] as num).toDouble(),
    tarifHeure:   (j['tarif_heure'] as num).toDouble(),
    montantTotal: (j['montant_total'] as num).toDouble(),
    statut:       j['statut'] as String,
  );
}

// ─── Service API ──────────────────────────────────────────────────────────────
class ParkingApi {
  static Future<Map<String, dynamic>> getDisponibilite({
    required DateTime debut,
    required DateTime fin,
  }) async {
    final uri = Uri.parse('$kServerUrl/api/places/disponibilite'
        '?debut=${debut.toIso8601String()}&fin=${fin.toIso8601String()}');
    final r = await http.get(uri).timeout(const Duration(seconds: 8));
    if (r.statusCode != 200) throw Exception('Erreur serveur');
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  static Future<Map<String, dynamic>> creerReservation({
    required int placeId,
    required String nomClient,
    required String telephone,
    required String uidBadge,
    required DateTime debut,
    required DateTime fin,
  }) async {
    final uri = Uri.parse('$kServerUrl/api/reservations');
    final r = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'place_id':   placeId,
        'nom_client': nomClient,
        'telephone':  telephone.isEmpty ? null : telephone,
        'uid_badge':  uidBadge.isEmpty  ? null : uidBadge,
        'debut':      debut.toIso8601String(),
        'fin':        fin.toIso8601String(),
      }),
    ).timeout(const Duration(seconds: 8));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (r.statusCode != 201) throw Exception(data['error'] ?? 'Erreur');
    return data;
  }

  static Future<List<Reservation>> getMesReservations(String nomClient) async {
    final uri = Uri.parse('$kServerUrl/api/reservations');
    final r = await http.get(uri).timeout(const Duration(seconds: 8));
    final list = (jsonDecode(r.body) as List).map((j) => Reservation.fromJson(j as Map<String, dynamic>)).toList();
    return list.where((res) =>
      res.nomClient.toLowerCase() == nomClient.toLowerCase() &&
      res.statut == 'active'
    ).toList();
  }

  static Future<void> annulerReservation(int id) async {
    final uri = Uri.parse('$kServerUrl/api/reservations/$id/annuler');
    final r   = await http.post(uri).timeout(const Duration(seconds: 8));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (!(data['ok'] as bool)) throw Exception(data['error'] ?? 'Erreur annulation');
  }

  static Future<Map<String, dynamic>> getTarifs() async {
    final uri  = Uri.parse('$kServerUrl/api/tarifs');
    final r    = await http.get(uri).timeout(const Duration(seconds: 8));
    final list = jsonDecode(r.body) as List;
    final map  = <String, double>{};
    for (final t in list) {
      map[(t['nom'] as String)] = (t['valeur'] as num).toDouble();
    }
    return map;
  }
}

// ─── App Root ─────────────────────────────────────────────────────────────────
class SmartParkingApp extends StatelessWidget {
  const SmartParkingApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'SmartParking',
    theme: kDarkTheme,
    debugShowCheckedModeBanner: false,
    home: const HomePage(),
  );
}

// ─── Page d'accueil ───────────────────────────────────────────────────────────
class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) => Scaffold(
    body: IndexedStack(
      index: _tab,
      children: const [
        ReservationPage(),
        MesReservationsPage(),
      ],
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: _tab,
      backgroundColor: kCard,
      onDestinationSelected: (i) => setState(() => _tab = i),
      destinations: const [
        NavigationDestination(icon: Icon(Icons.local_parking), label: 'Réserver'),
        NavigationDestination(icon: Icon(Icons.bookmark_outlined), label: 'Mes réservations'),
      ],
    ),
  );
}

// ─── Page Réservation ─────────────────────────────────────────────────────────
class ReservationPage extends StatefulWidget {
  const ReservationPage({super.key});
  @override State<ReservationPage> createState() => _ReservationPageState();
}

class _ReservationPageState extends State<ReservationPage> {
  DateTime _debut = DateTime.now().add(const Duration(minutes: 15));
  DateTime _fin   = DateTime.now().add(const Duration(hours: 1, minutes: 15));

  List<PlaceInfo> _places   = [];
  double          _tarifBase   = 10;
  double          _tarifReserve = 15;
  bool            _loading  = false;
  bool            _searched = false;
  String?         _error;

  @override
  void initState() {
    super.initState();
    _chargerTarifs();
  }

  Future<void> _chargerTarifs() async {
    try {
      final t = await ParkingApi.getTarifs();
      setState(() {
        _tarifBase    = t['tarif_base']    ?? 10;
        _tarifReserve = t['tarif_reserve'] ?? 15;
      });
    } catch (_) {}
  }

  Future<void> _chercher() async {
    if (_fin.isBefore(_debut) || _fin.isAtSameMomentAs(_debut)) {
      setState(() => _error = 'La fin doit être après le début');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      final data = await ParkingApi.getDisponibilite(debut: _debut, fin: _fin);
      setState(() {
        _places   = (data['places'] as List).map((j) => PlaceInfo.fromJson(j as Map<String, dynamic>)).toList();
        _searched = true;
      });
    } catch (e) {
      setState(() => _error = 'Impossible de joindre le serveur.\nVérifiez votre connexion.');
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _pickDateTime(bool isDebut) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: isDebut ? _debut : _fin,
      firstDate: now,
      lastDate: now.add(const Duration(days: 3)),
    );
    if (!mounted || picked == null) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(isDebut ? _debut : _fin),
    );
    if (!mounted || time == null) return;
    final dt = DateTime(picked.year, picked.month, picked.day, time.hour, time.minute);
    setState(() {
      if (isDebut) {
        _debut = dt;
        if (_fin.isBefore(_debut.add(const Duration(hours: 1)))) {
          _fin = _debut.add(const Duration(hours: 1));
        }
      } else {
        _fin = dt;
      }
      _places = []; _searched = false;
    });
  }

  double get _duree => _fin.difference(_debut).inMinutes / 60;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: CustomScrollView(
        slivers: [
          SliverAppBar(
            floating: true,
            backgroundColor: kCard,
            title: Row(children: [
              const Icon(Icons.local_parking, color: kBlue, size: 22),
              const SizedBox(width: 8),
              const Text('SmartParking', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            ]),
          ),
          SliverPadding(
            padding: const EdgeInsets.all(16),
            sliver: SliverList(children: [

              // ── Tarifs info ──
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: kCard,
                  border: Border.all(color: kBorder),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _tarifBadge('Sans réservation', _tarifBase,   kDim),
                    Container(width: 1, height: 30, color: kBorder),
                    _tarifBadge('Avec réservation', _tarifReserve, kAmber),
                  ],
                ),
              ),
              const SizedBox(height: 16),

              // ── Sélection dates ──
              Container(
                decoration: BoxDecoration(
                  color: kCard,
                  border: Border.all(color: kBorder),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(children: [
                  _dateRow('Arrivée', _debut, () => _pickDateTime(true)),
                  Divider(color: kBorder, height: 1),
                  _dateRow('Départ',  _fin,   () => _pickDateTime(false)),
                ]),
              ),
              const SizedBox(height: 8),

              // Durée + montant estimé
              if (_duree > 0)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                  child: Row(children: [
                    Icon(Icons.timer_outlined, size: 14, color: kDim),
                    const SizedBox(width: 4),
                    Text('${_duree.toStringAsFixed(1)}h', style: TextStyle(color: kDim, fontSize: 12)),
                    const Spacer(),
                    Text('Montant estimé : ', style: TextStyle(color: kDim, fontSize: 12)),
                    Text('${(_duree * _tarifReserve).toStringAsFixed(2)} MAD',
                      style: const TextStyle(color: kAmber, fontSize: 13, fontWeight: FontWeight.w600)),
                  ]),
                ),

              const SizedBox(height: 12),

              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _loading ? null : _chercher,
                  icon: _loading
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Icon(Icons.search),
                  label: Text(_loading ? 'Recherche…' : 'Voir les places disponibles'),
                  style: FilledButton.styleFrom(
                    backgroundColor: kBlue,
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ),

              if (_error != null) ...[
                const SizedBox(height: 12),
                _errorBox(_error!),
              ],

              if (_searched) ...[
                const SizedBox(height: 20),
                Text('${_places.where((p) => p.disponible).length} place(s) disponible(s)',
                  style: const TextStyle(color: kDim, fontSize: 13)),
                const SizedBox(height: 10),
                ..._places.map((p) => _PlaceCard(
                  place:        p,
                  debut:        _debut,
                  fin:          _fin,
                  tarifReserve: _tarifReserve,
                  onReserved:   _chercher,
                )),
              ],

            ].map((w) => Padding(padding: EdgeInsets.only(bottom: w is SizedBox ? 0 : 0), child: w)).toList()),
          ),
        ],
      ),
    );
  }

  Widget _tarifBadge(String label, double val, Color color) => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      Text('${val.toStringAsFixed(0)} MAD/h', style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 15)),
      Text(label, style: const TextStyle(color: kDim, fontSize: 11)),
    ],
  );

  Widget _dateRow(String label, DateTime dt, VoidCallback onTap) {
    final fmt = DateFormat('EEE dd MMM  HH:mm', 'fr_FR');
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(children: [
          Text(label, style: const TextStyle(color: kDim, fontSize: 13, width: 60)),
          const SizedBox(width: 12),
          Expanded(child: Text(fmt.format(dt), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500))),
          const Icon(Icons.chevron_right, color: kDim, size: 18),
        ]),
      ),
    );
  }
}

// ─── Carte d'une place ────────────────────────────────────────────────────────
class _PlaceCard extends StatelessWidget {
  final PlaceInfo place;
  final DateTime  debut, fin;
  final double    tarifReserve;
  final VoidCallback onReserved;
  const _PlaceCard({required this.place, required this.debut, required this.fin,
                    required this.tarifReserve, required this.onReserved});

  @override
  Widget build(BuildContext context) {
    final dispo = place.disponible;
    final color = dispo ? kGreen : kAmber;
    final duree  = fin.difference(debut).inMinutes / 60;
    final montant = duree * tarifReserve;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: kCard,
        border: Border.all(color: color.withOpacity(.35)),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(children: [
          // Numéro place
          Container(
            width: 48, height: 48,
            decoration: BoxDecoration(
              color: color.withOpacity(.1),
              borderRadius: BorderRadius.circular(10),
            ),
            alignment: Alignment.center,
            child: Text('P${place.id}', style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 16)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                dispo ? 'Disponible' : 'Réservée',
                style: TextStyle(color: color, fontSize: 13, fontWeight: FontWeight.w600),
              ),
              if (!dispo && place.reservation != null)
                Text(
                  'Par ${place.reservation!.nomClient}',
                  style: const TextStyle(color: kDim, fontSize: 11),
                ),
              if (dispo)
                Text(
                  '${montant.toStringAsFixed(2)} MAD · ${duree.toStringAsFixed(1)}h',
                  style: const TextStyle(color: kAmber, fontSize: 12),
                ),
            ]),
          ),
          if (dispo)
            FilledButton(
              onPressed: () => _ouvrirFormulaire(context),
              style: FilledButton.styleFrom(
                backgroundColor: kGreen,
                foregroundColor: Colors.black,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              child: const Text('Réserver', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
        ]),
      ),
    );
  }

  void _ouvrirFormulaire(BuildContext context) {
    final duree   = fin.difference(debut).inMinutes / 60;
    final montant = duree * tarifReserve;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: kCard,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _ReservationForm(
        place:        place,
        debut:        debut,
        fin:          fin,
        montant:      montant,
        tarifReserve: tarifReserve,
        onSuccess:    onReserved,
      ),
    );
  }
}

// ─── Formulaire de réservation ────────────────────────────────────────────────
class _ReservationForm extends StatefulWidget {
  final PlaceInfo place;
  final DateTime debut, fin;
  final double montant, tarifReserve;
  final VoidCallback onSuccess;
  const _ReservationForm({required this.place, required this.debut, required this.fin,
                          required this.montant, required this.tarifReserve, required this.onSuccess});

  @override State<_ReservationForm> createState() => _ReservationFormState();
}

class _ReservationFormState extends State<_ReservationForm> {
  final _nomCtrl = TextEditingController();
  final _telCtrl = TextEditingController();
  final _uidCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _chargerPrefs();
  }

  Future<void> _chargerPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    _nomCtrl.text = prefs.getString('nom_client') ?? '';
    _telCtrl.text = prefs.getString('telephone')  ?? '';
    _uidCtrl.text = prefs.getString('uid_badge')  ?? '';
  }

  Future<void> _reserver() async {
    if (_nomCtrl.text.trim().isEmpty) {
      setState(() => _error = 'Le nom est requis');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('nom_client', _nomCtrl.text.trim());
      await prefs.setString('telephone',  _telCtrl.text.trim());
      await prefs.setString('uid_badge',  _uidCtrl.text.trim());

      final data = await ParkingApi.creerReservation(
        placeId:    widget.place.id,
        nomClient:  _nomCtrl.text.trim(),
        telephone:  _telCtrl.text.trim(),
        uidBadge:   _uidCtrl.text.trim(),
        debut:      widget.debut,
        fin:        widget.fin,
      );
      if (!mounted) return;
      Navigator.pop(context);
      widget.onSuccess();
      _showSucces(context, data);
    } catch (e) {
      setState(() => _error = e.toString().replaceAll('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _showSucces(BuildContext ctx, Map<String, dynamic> data) {
    showDialog(
      context: ctx,
      builder: (_) => AlertDialog(
        backgroundColor: kCard,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Row(children: [
          Icon(Icons.check_circle, color: kGreen, size: 26),
          SizedBox(width: 10),
          Text('Réservation confirmée !'),
        ]),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          _infoRow('Réservation', '#${data['id']}'),
          _infoRow('Place', 'P${data['place_id']}'),
          _infoRow('Montant', '${data['montant_total']} MAD'),
          _infoRow('Durée', '${data['duree_heures']}h'),
        ]),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Fermer', style: TextStyle(color: kBlue)),
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String val) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(children: [
      Text('$label : ', style: const TextStyle(color: kDim, fontSize: 13)),
      Text(val, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
    ]),
  );

  @override
  Widget build(BuildContext context) {
    final kb = MediaQuery.of(context).viewInsets.bottom;
    final fmt = DateFormat('dd/MM HH:mm');
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 20, 20, 20 + kb),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        // Handle
        Center(child: Container(width: 40, height: 4, decoration: BoxDecoration(color: kBorder, borderRadius: BorderRadius.circular(2)))),
        const SizedBox(height: 16),

        Text('Réserver Place P${widget.place.id}',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(
          '${fmt.format(widget.debut)} → ${fmt.format(widget.fin)}  ·  ${widget.montant.toStringAsFixed(2)} MAD',
          style: const TextStyle(color: kAmber, fontSize: 13),
        ),
        const SizedBox(height: 20),

        _field('Votre nom *', _nomCtrl, Icons.person_outline, TextInputType.name),
        const SizedBox(height: 12),
        _field('Téléphone', _telCtrl, Icons.phone_outlined, TextInputType.phone),
        const SizedBox(height: 12),
        _field('UID Badge RFID (optionnel)', _uidCtrl, Icons.nfc, TextInputType.text),
        const SizedBox(height: 16),

        if (_error != null) ...[
          _errorBox(_error!),
          const SizedBox(height: 12),
        ],

        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: _loading ? null : _reserver,
            style: FilledButton.styleFrom(
              backgroundColor: kGreen,
              foregroundColor: Colors.black,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            ),
            child: _loading
                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : Text('Confirmer — ${widget.montant.toStringAsFixed(2)} MAD',
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          ),
        ),
      ]),
    );
  }

  Widget _field(String label, TextEditingController ctrl, IconData icon, TextInputType type) {
    return TextField(
      controller: ctrl,
      keyboardType: type,
      style: const TextStyle(fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: kDim, fontSize: 13),
        prefixIcon: Icon(icon, color: kDim, size: 18),
        filled: true,
        fillColor: const Color(0xFF0D0F14),
        border:         OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: kBorder)),
        enabledBorder:  OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: kBorder)),
        focusedBorder:  OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: kBlue, width: 1.5)),
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      ),
    );
  }
}

// ─── Page Mes Réservations ────────────────────────────────────────────────────
class MesReservationsPage extends StatefulWidget {
  const MesReservationsPage({super.key});
  @override State<MesReservationsPage> createState() => _MesReservationsPageState();
}

class _MesReservationsPageState extends State<MesReservationsPage> {
  List<Reservation> _reservations = [];
  bool   _loading = false;
  String _nom     = '';
  bool   _loaded  = false;

  @override
  void initState() {
    super.initState();
    _chargerNom();
  }

  Future<void> _chargerNom() async {
    final prefs = await SharedPreferences.getInstance();
    final nom   = prefs.getString('nom_client') ?? '';
    setState(() => _nom = nom);
    if (nom.isNotEmpty) _charger();
  }

  Future<void> _charger() async {
    if (_nom.isEmpty) return;
    setState(() { _loading = true; });
    try {
      final list = await ParkingApi.getMesReservations(_nom);
      setState(() { _reservations = list; _loaded = true; });
    } catch (e) {
      setState(() => _loaded = true);
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _annuler(Reservation res) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: kCard,
        title: const Text('Annuler la réservation ?'),
        content: Text('Place P${res.placeId} — ${res.montantTotal.toStringAsFixed(2)} MAD'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Non')),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Oui, annuler', style: TextStyle(color: kRed)),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    try {
      await ParkingApi.annulerReservation(res.id);
      _charger();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString()), backgroundColor: kRed),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat('dd/MM HH:mm');
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Mes réservations', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          const SizedBox(height: 16),

          // Champ nom
          Row(children: [
            Expanded(
              child: TextField(
                onChanged: (v) => setState(() => _nom = v),
                controller: TextEditingController(text: _nom)
                  ..selection = TextSelection.fromPosition(TextPosition(offset: _nom.length)),
                decoration: InputDecoration(
                  hintText: 'Votre nom',
                  hintStyle: const TextStyle(color: kDim),
                  filled: true, fillColor: kCard,
                  border:        OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: kBorder)),
                  enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: kBorder)),
                  focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: kBlue)),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                ),
              ),
            ),
            const SizedBox(width: 10),
            FilledButton(
              onPressed: _charger,
              style: FilledButton.styleFrom(backgroundColor: kBlue, foregroundColor: Colors.black, padding: const EdgeInsets.all(14)),
              child: const Icon(Icons.search),
            ),
          ]),
          const SizedBox(height: 20),

          if (_loading)
            const Center(child: CircularProgressIndicator(color: kBlue))
          else if (!_loaded)
            Center(child: Text('Entrez votre nom pour voir vos réservations', style: TextStyle(color: kDim)))
          else if (_reservations.isEmpty)
            Center(child: Text('Aucune réservation active trouvée', style: TextStyle(color: kDim)))
          else
            Expanded(
              child: RefreshIndicator(
                onRefresh: _charger,
                child: ListView.builder(
                  itemCount: _reservations.length,
                  itemBuilder: (_, i) {
                    final res = _reservations[i];
                    final now   = DateTime.now();
                    final actif = res.debut.isBefore(now) && res.fin.isAfter(now);
                    return Container(
                      margin: const EdgeInsets.only(bottom: 12),
                      decoration: BoxDecoration(
                        color: kCard,
                        border: Border.all(color: (actif ? kGreen : kBlue).withOpacity(.3)),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [
                            Text('Place P${res.placeId}', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                              decoration: BoxDecoration(
                                color: (actif ? kGreen : kBlue).withOpacity(.12),
                                borderRadius: BorderRadius.circular(20),
                                border: Border.all(color: (actif ? kGreen : kBlue).withOpacity(.3)),
                              ),
                              child: Text(actif ? 'En cours' : 'À venir',
                                style: TextStyle(color: actif ? kGreen : kBlue, fontSize: 11, fontWeight: FontWeight.w600)),
                            ),
                            const Spacer(),
                            Text('${res.montantTotal.toStringAsFixed(2)} MAD',
                              style: const TextStyle(color: kAmber, fontWeight: FontWeight.w700)),
                          ]),
                          const SizedBox(height: 8),
                          Text('${fmt.format(res.debut)} → ${fmt.format(res.fin)}',
                            style: const TextStyle(color: kDim, fontSize: 13)),
                          Text('${res.dureeHeures}h · ${res.tarifHeure} MAD/h',
                            style: const TextStyle(color: kDim, fontSize: 12)),
                          const SizedBox(height: 12),
                          Align(
                            alignment: Alignment.centerRight,
                            child: TextButton(
                              onPressed: () => _annuler(res),
                              style: TextButton.styleFrom(foregroundColor: kRed),
                              child: const Text('Annuler', style: TextStyle(fontSize: 13)),
                            ),
                          ),
                        ]),
                      ),
                    );
                  },
                ),
              ),
            ),
        ]),
      ),
    );
  }
}

// ─── Widget partagé : boîte d'erreur ─────────────────────────────────────────
Widget _errorBox(String msg) => Container(
  padding: const EdgeInsets.all(12),
  decoration: BoxDecoration(
    color: kRed.withOpacity(.08),
    border: Border.all(color: kRed.withOpacity(.3)),
    borderRadius: BorderRadius.circular(8),
  ),
  child: Row(children: [
    const Icon(Icons.error_outline, color: kRed, size: 16),
    const SizedBox(width: 8),
    Expanded(child: Text(msg, style: const TextStyle(color: kRed, fontSize: 13))),
  ]),
);
