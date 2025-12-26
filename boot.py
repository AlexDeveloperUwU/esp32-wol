import time

import mip
import network

from config import WIFI_PASS, WIFI_SSID


def connect_network():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    try:
        wlan.config(pm=0xA11140)
    except:
        pass

    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(0.5)
    print("WiFi Connected:", wlan.ifconfig())


def install_dependencies():
    libs = [("umqtt.robust", "umqtt.robust"), ("hmac", "hmac"), ("hashlib", "hashlib")]
    for import_name, install_name in libs:
        try:
            __import__(import_name)
        except ImportError:
            print(f"Installing {install_name}...")
            try:
                mip.install(install_name)
            except Exception as e:
                print(f"Error: {e}")


connect_network()
install_dependencies()
