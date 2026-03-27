import time
import subprocess
import pandas as pd
import psutil
from datetime import datetime, timedelta


try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    PIR_PIN = 17
    FAN_PIN = 27
    BULB_PIN = 22
    LED_PIN = 23
    GPIO.setup(PIR_PIN, GPIO.IN)
    GPIO.setup(FAN_PIN, GPIO.OUT)
    GPIO.setup(BULB_PIN, GPIO.OUT)
    GPIO.setup(LED_PIN, GPIO.OUT)
    GPIO_AVAILABLE = True
except:
    GPIO_AVAILABLE = False

try:
    import Adafruit_DHT
    DHT_SENSOR = Adafruit_DHT.DHT22
    DHT_PIN = 4
    DHT_AVAILABLE = True
except:
    DHT_AVAILABLE = False


try:
    import bluetooth
    BT_AVAILABLE = True
except:
    BT_AVAILABLE = False

try:
    from SX127x.LoRa import *
    from SX127x.board_config import BOARD
    BOARD.setup()
    class LoRaNode(LoRa):
        def __init__(self):
            super().__init__()
            self.set_mode(MODE.SLEEP)
    lora = LoRaNode()
    LORA_AVAILABLE = True
except:
    LORA_AVAILABLE = False


START_TIME = datetime(2026, 2, 27, 0, 0)
END_TIME   = datetime(2026, 3, 5, 23, 59)


def get_slot(ts):
    h, m = ts.hour, ts.minute
    if (h==0 and m>=45) or (1<=h<5) or (h==5 and m<45):
        return "midnight"
    if (h==5 and m>=45) or (6<=h<9):
        return "morning"
    if 9<=h<12:
        return "most_active_morning"
    if 12<=h<14:
        return "afternoon"
    if (14<=h<17) and (h==17 and m<25):
        return "most_active_afternoon"
    if (h==17 and m>=25) and (18<=h<19):
        return "evening"
    if 19<=h<22:
        return "most_active_night"
    return "night"


import psutil
import socket

def detect_network():
    interfaces = psutil.net_if_stats()
    active = [i for i, s in interfaces.items() if s.isup]

    def has_internet():
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            return True
        except:
            return False

    
    if "wlan0" in active:
        try:
            ssid = subprocess.check_output("iwgetid -r", shell=True).decode().strip().lower()
            if any(x in ssid for x in ["hotspot","android","redmi"]):
                return "4g"
            return "wifi"
        except:
            return "wifi"

    
    if "eth0" in active and has_internet():
        return "ethernet"

    
    if BT_AVAILABLE:
        try:
            bt = subprocess.check_output("hcitool con", shell=True).decode()
            if "ACL" in bt:
                return "bluetooth"
        except:
            pass

    
    if LORA_AVAILABLE:
        return "lora"

    
    return "unknown"


def measure_latency():
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "8.8.8.8"],
            capture_output=True, text=True, timeout=2
        )
        return float(result.stdout.split("time=")[1].split(" ")[0])
    except:
        return None


def read_dht():
    if not DHT_AVAILABLE:
        return None, None
    h, t = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
    return t, h

def read_motion():
    if GPIO_AVAILABLE:
        return GPIO.input(PIR_PIN)
    return 0


records = []
prev_temp = None
prev_latency = None
cycle = 0

current = START_TIME

while current <= END_TIME:

    slot = get_slot(current)

    
    temp, humidity = read_dht()
    if temp is None or humidity is None:
        current += timedelta(minutes=1)
        continue

    motion = read_motion()

    temp_change = 0 if prev_temp is None else round(temp - prev_temp, 2)
    prev_temp = temp
    temp_flag = 1 if abs(temp_change) >= 6 or temp < 21 or temp > 38 else 0

    
    network = detect_network()

    latency = measure_latency()
    if latency is None:
        current += timedelta(minutes=1)
        continue
    latency_change = 0 if prev_latency is None else round(latency - prev_latency, 2)
    prev_latency = latency
    latency_flag = 1 if (latency > 300 or abs(latency_change) > 150) else 0
    latency = round(latency, 2)

    
    fan = 1 if temp > 30 else 0
    bulb = 1 if (motion == 1 and slot in ["most_active_night","night","midnight"]) else 0
    cycle += 1
    led = 1 if cycle % 30 == 0 else 0

    if GPIO_AVAILABLE:
        GPIO.output(FAN_PIN, fan)
        GPIO.output(BULB_PIN, bulb)
        GPIO.output(LED_PIN, led)

    system_state = "active" if fan or bulb else "idle"

    
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().used / (1024*1024)
    #energy = (fan*50 + bulb*10 + led)/60  # arbitrary units

    
    row = {
        "timestamp": current,
        "slot": slot,
        "temperature": round(temp,2),
        "temp_change": temp_change,
        "temperature_anomaly": temp_flag,
        "humidity": round(humidity,2),
        "motion": motion,
        "fan_state": fan,
        "bulb_state": bulb,
        "led_state": led,
        "network_type": network,
        "latency": latency,
        "latency_anomaly": latency_flag,
        "system_state": system_state,
		"combined_anomaly": 1 if temp_flag or latency_flag else 0,
        "cpu_usage_percent": round(cpu,2),
        "ram_usage_mb": round(ram,2)
        #"energy_consumed": round(energy,3)
        
    }

    
    records.append(row)
    current += timedelta(minutes=1)


df = pd.DataFrame(records)
df.to_csv("FINAL_HARDWARE_LOG.csv", index=False)

if GPIO_AVAILABLE:
    GPIO.cleanup()

print("CSV Logging Complete — Records:", len(df))