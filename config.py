import os

NB_PLACES   = int(os.environ.get("NB_PLACES", 6))
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT   = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USER   = os.environ.get("MQTT_USER", "")
MQTT_PASS   = os.environ.get("MQTT_PASS", "")
SECRET_KEY  = os.environ.get("SECRET_KEY", "parking-iot-2025")
