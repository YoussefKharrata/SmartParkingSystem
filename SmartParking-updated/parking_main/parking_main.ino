#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>

#define NB_PLACES       6
#define SEUIL_CM        10
#define INTERVALLE_MS   500
#define PORTE_OUVERTE   90
#define PORTE_FERMEE    0
#define DELAI_FERMETURE 5000

#define RST_PIN    5
#define SS_PIN     10
#define SERVO_PIN  3
#define LED_LIBRE  6
#define LED_OCCUPE 7

const uint8_t TRIG_PINS[NB_PLACES] = {A0, A1, A2, A3, A4, 9};
const uint8_t ECHO_PINS[NB_PLACES] = {2,  4,  7,  8,  A5, 6};

MFRC522 rfid(SS_PIN, RST_PIN);
Servo   servoPorte;

bool          places[NB_PLACES] = {false};
bool          porteOuverte       = false;
unsigned long derniereLecture    = 0;
unsigned long tempsOuverture     = 0;

void setup() {
  Serial.begin(9600);
  while (!Serial);

  for (int i = 0; i < NB_PLACES; i++) {
    pinMode(TRIG_PINS[i], OUTPUT);
    pinMode(ECHO_PINS[i], INPUT);
  }
  pinMode(LED_LIBRE,  OUTPUT);
  pinMode(LED_OCCUPE, OUTPUT);

  servoPorte.attach(SERVO_PIN);
  servoPorte.write(PORTE_FERMEE);

  SPI.begin();
  rfid.PCD_Init();

  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_LIBRE,  HIGH);
    digitalWrite(LED_OCCUPE, HIGH);
    delay(200);
    digitalWrite(LED_LIBRE,  LOW);
    digitalWrite(LED_OCCUPE, LOW);
    delay(200);
  }
  digitalWrite(LED_LIBRE, HIGH);
  Serial.println(F("SYSTEM:READY"));
}

void loop() {
  unsigned long now = millis();

  if (now - derniereLecture >= INTERVALLE_MS) {
    derniereLecture = now;
    int nbLibres = 0;
    for (int i = 0; i < NB_PLACES; i++) {
      float dist   = lireDistance(i);
      bool  occupe = (dist > 0 && dist < SEUIL_CM);
      places[i] = occupe;
      if (!occupe) nbLibres++;
      envoyerSensor(i, dist, occupe);
    }
    mettreAJourLEDs(nbLibres);
  }

  if (porteOuverte && (millis() - tempsOuverture >= DELAI_FERMETURE)) {
    fermerPorte();
  }

  bool auMoinsUneLibre = false;
  for (int i = 0; i < NB_PLACES; i++) {
    if (!places[i]) { auMoinsUneLibre = true; break; }
  }

  if (auMoinsUneLibre) {
    if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
      lireEtEnvoyerRFID(auMoinsUneLibre);
      rfid.PICC_HaltA();
      rfid.PCD_StopCrypto1();
    }
  }

  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if      (cmd == "OPEN")  ouvrirPorte();
    else if (cmd == "CLOSE") fermerPorte();
  }
}

float lireDistance(int idx) {
  digitalWrite(TRIG_PINS[idx], LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PINS[idx], HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PINS[idx], LOW);
  long duree = pulseIn(ECHO_PINS[idx], HIGH, 30000);
  if (duree == 0) return 0;
  float d = duree * 0.034 / 2.0;
  return (d < 2 || d > 400) ? 0 : d;
}

void envoyerSensor(int idx, float distance, bool occupe) {
  Serial.print(F("{\"type\":\"sensor\""));
  Serial.print(F(",\"place_id\":")); Serial.print(idx + 1);
  Serial.print(F(",\"distance\":")); Serial.print(distance, 1);
  Serial.print(F(",\"occupe\":")); Serial.print(occupe ? F("true") : F("false"));
  Serial.print(F(",\"porte_ouverte\":")); Serial.print(porteOuverte ? F("true") : F("false"));
  Serial.println(F("}"));
}

void lireEtEnvoyerRFID(bool placesLibres) {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) uid += "0";
    uid += String(rfid.uid.uidByte[i], HEX);
    if (i < rfid.uid.size - 1) uid += ":";
  }
  uid.toUpperCase();
  MFRC522::PICC_Type type = rfid.PICC_GetType(rfid.uid.sak);
  String typeStr = rfid.PICC_GetTypeName(type);
  Serial.print(F("{\"type\":\"rfid\""));
  Serial.print(F(",\"uid\":\"")); Serial.print(uid); Serial.print(F("\""));
  Serial.print(F(",\"card_type\":\"")); Serial.print(typeStr); Serial.print(F("\""));
  Serial.print(F(",\"place_libre\":")); Serial.print(placesLibres ? F("true") : F("false"));
  Serial.println(F("}"));
  clignoteLED(LED_LIBRE, 1, 200);
}

void ouvrirPorte() {
  if (porteOuverte) return;
  servoPorte.write(PORTE_OUVERTE);
  porteOuverte   = true;
  tempsOuverture = millis();
  clignoteLED(LED_LIBRE, 2, 150);
  Serial.println(F("{\"type\":\"porte\",\"etat\":\"ouverte\"}"));
}

void fermerPorte() {
  if (!porteOuverte) return;
  servoPorte.write(PORTE_FERMEE);
  porteOuverte = false;
  Serial.println(F("{\"type\":\"porte\",\"etat\":\"fermee\"}"));
}

void mettreAJourLEDs(int nbLibres) {
  digitalWrite(LED_LIBRE,  nbLibres > 0 ? HIGH : LOW);
  digitalWrite(LED_OCCUPE, nbLibres == 0 ? HIGH : LOW);
}

void clignoteLED(int pin, int fois, int delaiMs) {
  bool etat = digitalRead(pin);
  for (int i = 0; i < fois; i++) {
    digitalWrite(pin, HIGH); delay(delaiMs);
    digitalWrite(pin, LOW);  delay(delaiMs);
  }
  digitalWrite(pin, etat ? HIGH : LOW);
}
