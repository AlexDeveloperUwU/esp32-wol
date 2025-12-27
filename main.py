import gc
import os
import time

import machine
import network
from umqtt.robust import MQTTClient

from config import LED_PIN, MQTT_BROKER, MQTT_CLIENT_ID, MQTT_PORT, WOL_IP, WOL_MAC
from utils import (
    encrypt_payload,
    get_dynamic_topic,
    ping_device,
    send_magic_packet,
    sync_time,
    verify_and_parse_msg,
)

STATUS_BOOT = 0
STATUS_CONNECTING = 1
STATUS_IDLE = 2
STATUS_ERROR = 3

current_status = STATUS_BOOT
last_led_tick = 0
led_state = 0
wdt = None

try:
    led = machine.Pin(LED_PIN, machine.Pin.OUT)
    led.value(0)
except:
    led = None

current_topic = ""
client = None
last_ping = 0
start_time = 0


def feed_wdt():
    if wdt:
        wdt.feed()


def set_status(status):
    global current_status
    current_status = status


def update_led():
    global last_led_tick, led_state
    if not led:
        return

    now = time.ticks_ms()
    interval = 0

    if current_status == STATUS_BOOT:
        interval = 100
    elif current_status == STATUS_CONNECTING:
        interval = 300
    elif current_status == STATUS_ERROR:
        interval = 50
    elif current_status == STATUS_IDLE:
        if led_state == 1:
            interval = 50
        else:
            interval = 4000

    if time.ticks_diff(now, last_led_tick) > interval:
        led_state = 1 - led_state
        led.value(led_state)
        last_led_tick = now


def flash_signal(count):
    if not led:
        return
    for _ in range(count):
        led.value(1)
        time.sleep(0.05)
        led.value(0)
        time.sleep(0.05)
    feed_wdt()


def get_system_stats():
    gc.collect()
    uptime_s = int(time.time() - start_time)
    mem_free = gc.mem_free()
    mem_alloc = gc.mem_alloc()

    try:
        fs = os.statvfs("/")
        disk_free = fs[0] * fs[3]
    except:
        disk_free = 0

    try:
        wlan = network.WLAN(network.STA_IF)
        rssi = wlan.status("rssi")
    except:
        rssi = 0

    return '{"uptime":%d,"mem_free":%d,"mem_alloc":%d,"rssi":%d,"disk_free":%d}' % (
        uptime_s,
        mem_free,
        mem_alloc,
        rssi,
        disk_free,
    )


def publish_encrypted(topic, payload):
    encrypted = encrypt_payload(payload)
    if encrypted:
        client.publish(topic, encrypted)


def sub_callback(topic, msg):
    flash_signal(1)

    try:
        topic_str = topic.decode()
        payload_str = msg.decode("utf-8")

        print(f"\n[RX] Message on: {topic_str}")

        cmd, ts = verify_and_parse_msg(payload_str)

        if cmd == "WAKE":
            print(f"[OK] WAKE (TS: {ts})")
            send_magic_packet()
            flash_signal(3)
            print("[TX] Magic Packet Sent")

        elif cmd == "STATUS":
            print(f"[OK] STATUS (TS: {ts})")
            is_online = ping_device(WOL_IP)
            resp = "ONLINE" if is_online else "OFFLINE"
            resp_topic = current_topic + "/response"
            publish_encrypted(resp_topic, resp)
            flash_signal(2)

        elif cmd == "PING":
            print(f"[OK] HEARTBEAT PING RECEIVED")
            resp_topic = current_topic + "/response"
            publish_encrypted(resp_topic, "PONG")
            flash_signal(1)

        elif cmd == "USAGE":
            print(f"[OK] USAGE STATS REQUEST")
            stats = get_system_stats()
            resp_topic = current_topic + "/response"
            print(f"[TX] {stats}")
            publish_encrypted(resp_topic, stats)
            flash_signal(2)

        elif cmd is None:
            print("[!!] Decryption Failed or Invalid Signature")
            set_status(STATUS_ERROR)
            time.sleep(1)
            set_status(STATUS_IDLE)

    except Exception as e:
        print(f"[!!] Callback Exception: {e}")

    feed_wdt()


def get_mqtt_client():
    set_status(STATUS_CONNECTING)
    print(f"[..] Connecting to MQTT Broker: {MQTT_BROKER}...")

    c = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT, keepalive=60)
    c.set_callback(sub_callback)
    c.DEBUG = True
    c.connect()
    print("[OK] MQTT Connected.")
    return c


def main_loop():
    global client, current_topic, last_ping, start_time, wdt

    set_status(STATUS_BOOT)

    try:
        wdt = machine.WDT(timeout=15000)
    except:
        print("[WARN] WDT not available")

    feed_wdt()
    gc.enable()
    gc.collect()

    print("[..] Syncing NTP time...")
    if sync_time():
        print("[OK] Time Synced.")
    else:
        print("[!!] NTP Sync Failed. Rebooting...")
        set_status(STATUS_ERROR)
        time.sleep(2)
        machine.reset()

    start_time = time.time()
    feed_wdt()

    try:
        client = get_mqtt_client()
        current_topic = get_dynamic_topic()
        client.subscribe(current_topic)
        print(f"[OK] Subscribed: {current_topic}")
        set_status(STATUS_IDLE)
        last_ping = time.time()

    except Exception as e:
        print(f"[!!] Connection Failed: {e}")
        set_status(STATUS_ERROR)
        time.sleep(3)
        machine.reset()

    while True:
        feed_wdt()

        try:
            update_led()
            gc.collect()

            if time.time() - start_time > 43200:
                print("[..] Scheduled 12h Reboot...")
                try:
                    client.disconnect()
                except:
                    pass
                time.sleep(1)
                machine.reset()

            client.check_msg()

            new_topic = get_dynamic_topic()
            if new_topic != current_topic:
                print(f"[..] Rotating Topic: {current_topic} -> {new_topic}")
                try:
                    client.unsubscribe(current_topic)
                except:
                    pass
                current_topic = new_topic
                client.subscribe(current_topic)
                sync_time()
                print("[OK] Topic Rotated")

            if time.time() - last_ping > 30:
                client.ping()
                last_ping = time.time()

            time.sleep(0.05)

        except OSError as e:
            print(f"[!!] MQTT Error: {e}")
            set_status(STATUS_CONNECTING)
            try:
                client.disconnect()
            except:
                pass
            try:
                feed_wdt()
                time.sleep(2)
                feed_wdt()
                client.connect()
                client.subscribe(current_topic)
                set_status(STATUS_IDLE)
            except:
                set_status(STATUS_ERROR)
                time.sleep(2)
                machine.reset()

        except Exception as e:
            print(f"[!!] Critical Error: {e}")
            set_status(STATUS_ERROR)
            time.sleep(2)
            machine.reset()


if __name__ == "__main__":
    main_loop()
