import _thread
import gc
import json
import time

import machine
from umqtt.robust import MQTTClient

import config
from utils import CryptoManager, ScheduleManager, SystemTools, WOLService


class BackgroundService:
    """
    <summary>Runs on Core 0. Handles LED blinking and Schedule checks.</summary>
    """

    BOOT = 100
    CONNECTING = 300
    ERROR = 50
    IDLE_ON = 50
    IDLE_OFF = 4000

    def __init__(self):
        self.enabled_led = config.LED_SIGNALS
        self.led_pin = None
        self.mode = self.BOOT
        self.state = 0
        self.last_wake_min = -1

        if self.enabled_led:
            try:
                self.led_pin = machine.Pin(config.LED_PIN, machine.Pin.OUT)
                self.led_pin.value(0)
            except:
                self.enabled_led = False

    def set_mode(self, mode):
        self.mode = mode

    def flash(self, count):
        if not self.enabled_led:
            return
        for _ in range(count):
            self.led_pin.value(1)
            time.sleep(0.05)
            self.led_pin.value(0)
            time.sleep(0.05)

    def _run_thread(self):
        last_led_tick = 0
        last_sched_tick = 0

        while True:
            now = time.ticks_ms()

            if self.enabled_led:
                interval = self.mode
                if self.mode in [self.IDLE_ON, self.IDLE_OFF]:
                    interval = self.IDLE_ON if self.state == 1 else self.IDLE_OFF

                if time.ticks_diff(now, last_led_tick) > interval:
                    self.state = 1 - self.state
                    self.led_pin.value(self.state)
                    last_led_tick = now

            if time.ticks_diff(now, last_sched_tick) > 10000:
                last_sched_tick = now
                try:
                    t = time.gmtime()
                    current_min = t[4]

                    if current_min != self.last_wake_min:
                        if ScheduleManager.should_wake():
                            print("[SCHED] Triggering Auto-Wake")
                            WOLService.send_magic_packet()
                            self.flash(3)
                            self.last_wake_min = current_min
                except Exception as e:
                    print("[SCHED] Thread Error:", e)

            time.sleep(0.05)

    def start(self):
        _thread.start_new_thread(self._run_thread, ())


class WOLApp:
    """
    <summary>Main Logic on Core 1. Manages MQTT and system integrity.</summary>
    """

    def __init__(self):
        self.service = BackgroundService()
        self.crypto = CryptoManager()
        self.client = None
        self.current_topic = ""
        self.start_time = 0
        self.last_mqtt_ping = 0
        self.wdt = None

    def _setup_wdt(self):
        print("[SYS] Initializing Watchdog (15s)...")
        try:
            self.wdt = machine.WDT(timeout=15000)
        except:
            print("[SYS] WDT not available.")

    def _feed(self):
        if self.wdt:
            self.wdt.feed()

    def _on_message(self, topic, msg):
        self.service.flash(1)
        try:
            decrypted = self.crypto.decrypt(msg.decode())
            if not decrypted:
                return

            parts = decrypted.split("|")
            if len(parts) < 3:
                return

            cmd_content = "|".join(parts[:-2])
            ts = parts[-2]
            sig = parts[-1]

            if not self.crypto.verify_signature(cmd_content, ts, sig):
                return

            current_ts = time.time() + 946684800
            if abs(current_ts - int(ts)) > 120:
                print(f"[ERR] Time skew: {abs(current_ts - int(ts))}s")
                return

            resp_topic = self.current_topic + "/response"

            is_json = cmd_content.startswith("{")
            command = cmd_content if not is_json else "JSON_CMD"

            if command == "WAKE":
                print("[OK] Manual Wake")
                WOLService.send_magic_packet()
                self.service.flash(3)
            elif command == "STATUS":
                status = (
                    "ONLINE" if WOLService.ping_device(config.WOL_IP) else "OFFLINE"
                )
                self._publish(resp_topic, status)
                self.service.flash(2)
            elif command == "PING":
                self._publish(resp_topic, "PONG")
            elif command == "USAGE":
                metrics = SystemTools.get_metrics(self.start_time)
                self._publish(resp_topic, metrics)
            elif command == "GET_SCHED":
                data = ScheduleManager.load_schedule()
                self._publish(resp_topic, json.dumps(data))
            elif is_json:
                try:
                    payload = json.loads(cmd_content)
                    if payload.get("cmd") == "SET_SCHED":
                        if ScheduleManager.save_schedule(payload.get("data")):
                            self._publish(resp_topic, "SCHED_SAVED")
                            print("[SCHED] Updated")
                except ValueError:
                    pass

        except Exception as e:
            print("[ERR] Callback error:", e)

    def _publish(self, topic, payload):
        enc = self.crypto.encrypt(payload)
        if enc:
            self.client.publish(topic, enc)

    def _connect_mqtt(self):
        print(f"[MQTT] Connecting to {config.MQTT_BROKER}...")
        self.service.set_mode(BackgroundService.CONNECTING)
        self.client = MQTTClient(
            config.MQTT_CLIENT_ID,
            config.MQTT_BROKER,
            port=config.MQTT_PORT,
            keepalive=60,
        )
        self.client.set_callback(self._on_message)
        self.client.connect()
        self.current_topic = SystemTools.get_dynamic_topic()
        self.client.subscribe(self.current_topic)
        print(f"[MQTT] Subscribed: {self.current_topic}")
        self.service.set_mode(BackgroundService.IDLE_ON)

    def run(self):
        print(f"--- ESP32 WOL v{config.VERSION} ---")
        self.service.start()
        self._setup_wdt()
        gc.enable()

        if not SystemTools.sync_time():
            print("[CRIT] No NTP. Rebooting...")
            time.sleep(5)
            machine.reset()

        self.start_time = time.time()
        self.last_mqtt_ping = time.time()

        try:
            self._connect_mqtt()
        except Exception as e:
            print("[CRIT] Init Error:", e)
            self.service.set_mode(BackgroundService.ERROR)
            time.sleep(10)
            machine.reset()

        print("[SYS] Entering Main Loop (Core 1).")
        while True:
            self._feed()
            try:
                if time.time() - self.start_time > 43200:
                    print("[SYS] Maintenance reboot.")
                    machine.reset()

                self.client.check_msg()

                new_topic = SystemTools.get_dynamic_topic()
                if new_topic != self.current_topic:
                    print(f"[MQTT] Rotating...")
                    try:
                        self.client.unsubscribe(self.current_topic)
                    except:
                        pass
                    self.current_topic = new_topic
                    self.client.subscribe(self.current_topic)
                    SystemTools.sync_time()

                if time.time() - self.last_mqtt_ping > 30:
                    self.client.ping()
                    self.last_mqtt_ping = time.time()

                time.sleep(0.2)

            except Exception as e:
                print(f"[ERR] Runtime Loop: {e}")
                self.service.set_mode(BackgroundService.ERROR)
                time.sleep(10)
                machine.reset()


if __name__ == "__main__":
    app = WOLApp()
    app.run()
