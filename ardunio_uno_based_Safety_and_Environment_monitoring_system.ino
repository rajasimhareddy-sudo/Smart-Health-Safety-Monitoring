/*
  Sensor Station - Arduino Uno
  DHT11 + MQ-2 + NEO-6M GPS -> SSD1306 OLED + HC-05 (Bluetooth) -> Python dashboard

  Libraries (Library Manager):
    - Adafruit SSD1306
    - Adafruit GFX Library
    - DHT sensor library (Adafruit)  + Adafruit Unified Sensor
    - TinyGPSPlus (Mikal Hart)

  Serial output format (one line every 2 s, goes to HC-05 on pin D1 and USB):
    $D,temp,hum,gas,lat,lon,sats,fix
*/

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
#include <SoftwareSerial.h>
#include <TinyGPSPlus.h>

// ---------- Pins ----------
#define DHTPIN      7
#define DHTTYPE     DHT11
#define MQ2_PIN     A0
#define GPS_RX_PIN  8      // Arduino RX  <- GPS TX
#define GPS_TX_PIN  9      // Arduino TX  -> GPS RX (not required)

// ---------- OLED ----------
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_ADDR     0x3C   // use 0x3D if your module needs it

// ---------- Gas thresholds (raw 0-1023, calibrate for your sensor) ----------
#define GAS_SAFE  300
#define GAS_WARN  500
#define GAS_HIGH  600

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
DHT dht(DHTPIN, DHTTYPE);
SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);
TinyGPSPlus gps;

const unsigned long SEND_INTERVAL = 2000;   // ms
unsigned long lastSend = 0;

void setup() {
  Serial.begin(9600);        // hardware UART -> HC-05 (and USB)
  gpsSerial.begin(9600);     // NEO-6M default baud
  dht.begin();

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    for (;;);                // OLED not found - check wiring/address
  }
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(F("Sensor Station"));
  display.println(F("Warming up..."));
  display.display();
  delay(2000);
}

void loop() {
  // Keep feeding GPS data as often as possible
  while (gpsSerial.available() > 0) {
    gps.encode(gpsSerial.read());
  }

  if (millis() - lastSend >= SEND_INTERVAL) {
    lastSend = millis();

    float temp = dht.readTemperature();
    float hum  = dht.readHumidity();
    int   gas  = analogRead(MQ2_PIN);

    bool   fix  = gps.location.isValid();
    double lat  = fix ? gps.location.lat() : 0.0;
    double lon  = fix ? gps.location.lng() : 0.0;
    int    sats = gps.satellites.isValid() ? (int)gps.satellites.value() : 0;

    showOnOled(temp, hum, gas, fix, lat, lon, sats);
    sendToPC(temp, hum, gas, fix, lat, lon, sats);
  }
}

const __FlashStringHelper* gasLabel(int gas) {
  if (gas>=GAS_SAFE)   return F("SAFE");
  if (gas >= GAS_HIGH) return F("HIGH");
  if (gas >= GAS_WARN) return F("WARN");
  return F("OK");
}

void showOnOled(float t, float h, int gas, bool fix, double lat, double lon, int sats) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.print(F("Temp: "));
  if (isnan(t)) display.print(F("--")); else display.print(t, 1);
  display.print(F(" C"));

  display.setCursor(0, 10);
  display.print(F("Hum : "));
  if (isnan(h)) display.print(F("--")); else display.print(h, 0);
  display.print(F(" %"));

  display.setCursor(0, 20);
  display.print(F("Gas : "));
  display.print(gas);
  display.print(F(" "));
  display.print(gasLabel(gas));

  if (fix) {
    display.setCursor(0, 32);
    display.print(F("Lat: "));
    display.print(lat, 6);
    display.setCursor(0, 42);
    display.print(F("Lon: "));
    display.print(lon, 6);
    display.setCursor(0, 54);
    display.print(F("Sats: "));
    display.print(sats);
  } else {
    display.setCursor(0, 36);
    display.print(F("GPS: searching..."));
    display.setCursor(0, 48);
    display.print(F("Sats: "));
    display.print(sats);
  }
  display.display();
}

void sendToPC(float t, float h, int gas, bool fix, double lat, double lon, int sats) {
  Serial.print(F("$D,"));
  Serial.print(t, 1);       Serial.print(',');
  Serial.print(h, 1);       Serial.print(',');
  Serial.print(gas);        Serial.print(',');
  Serial.print(lat, 6);     Serial.print(',');
  Serial.print(lon, 6);     Serial.print(',');
  Serial.print(sats);       Serial.print(',');
  Serial.println(fix ? 1 : 0);
}
