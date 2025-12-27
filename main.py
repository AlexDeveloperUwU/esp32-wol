import gc
import time

import machine
from umqtt.robust import MQTTClient

import config
from utils import CryptoManager, SystemTools, WOLService


class LEDController:
    """
    <summary>Manages physical LED patterns for system feedback.</summary>
    """

    BOOT = 100
    CONNECTING = 300
    ERROR = 50
    IDLE_ON = 50
    IDLE_OFF = 4000

    def __init__(self):
        self.enabled = config.LED_SIGNALS
        self.pin = None
        if self.enabled:
            try:
                self.pin = machine.Pin(config.LED_PIN, machine.Pin.OUT)
                self.pin.value(0)
            except:
                self.enabled = False
        self.state = 0
        self.last_tick = 0
        self.mode = self.BOOT

    def set_mode(self, mode):
        self.mode = mode

    def update(self):
        if not self.enabled:
            return
        now = time.ticks_ms()
        interval = self.mode
        if self.mode == self.IDLE_ON or self.mode == self.IDLE_OFF:
            interval = self.IDLE_ON if self.state == 1 else self.IDLE_OFF
        if time.ticks_diff(now, self.last_tick) > interval:
            self.state = 1 - self.state
            self.pin.value(self.state)
            self.last_tick = now

    def flash(self, count):
        if not self.enabled:
            return
        for _ in range(count):
            self.pin.value(1)
            time.sleep(0.05)
            self.pin.value(0)
            time.sleep(0.05)


class WOLApp:
    """
    <summary>Main application class managing the MQTT client and system loop.</summary>
    """

    def __init__(self):
        self.led = LEDController()
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
            print("[SYS] WDT not supported on this hardware.")

    def _feed(self):
        if self.wdt:
            self.wdt.feed()

    def _on_message(self, topic, msg):
        self.led.flash(1)
        raw_payload = msg.decode()
        print(f"\n[RX] Message on {topic.decode()}")

        decrypted = self.crypto.decrypt(raw_payload)
        if not decrypted:
            return

        try:
            parts = decrypted.split("|")
            if len(parts) != 3:
                print("[ERR] Invalid packet structure")
                return

            cmd, ts, sig = parts[0], parts[1], parts[2]
            if not self.crypto.verify_signature(cmd, ts, sig):
                return

            current_ts = time.time() + 946684800
            if abs(current_ts - int(ts)) > 60:
                print(
                    f"[ERR] Replay/Time sync error. Diff: {abs(current_ts - int(ts))}s"
                )
                return

            print(f"[OK] Command: {cmd} (TS: {ts})")
            resp_topic = self.current_topic + "/response"

            if cmd == "WAKE":
                WOLService.send_magic_packet()
                self.led.flash(3)
            elif cmd == "STATUS":
                status = (
                    "ONLINE" if WOLService.ping_device(config.WOL_IP) else "OFFLINE"
                )
                self._publish(resp_topic, status)
                self.led.flash(2)
            elif cmd == "PING":
                self._publish(resp_topic, "PONG")
                self.led.flash(1)
            elif cmd == "USAGE":
                metrics = SystemTools.get_metrics(self.start_time)
                self._publish(resp_topic, metrics)
                print("[TX] Usage metrics sent.")
                self.led.flash(2)

        except Exception as e:
            print("[ERR] Callback exception:", e)

    def _publish(self, topic, payload):
        enc = self.crypto.encrypt(payload)
        if enc:
            self.client.publish(topic, enc)
            print(f"[TX] Response sent to {topic}")

    def _connect_mqtt(self):
        print(f"[MQTT] Connecting to {config.MQTT_BROKER}...")
        self.led.set_mode(LEDController.CONNECTING)
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
        print(f"[MQTT] Connected and subscribed to: {self.current_topic}")
        self.led.set_mode(LEDController.IDLE_ON)

    def run(self):
        print(f"--- ESP32 WOL v{config.VERSION} ---")
        self._setup_wdt()
        gc.enable()

        if not SystemTools.sync_time():
            print("[CRIT] Cannot proceed without time sync. Resetting...")
            time.sleep(2)
            machine.reset()

        self.start_time = time.time()

        try:
            self._connect_mqtt()
        except Exception as e:
            print("[CRIT] MQTT Connection failed:", e)
            time.sleep(5)
            machine.reset()

        print("[SYS] System entering main loop.")
        while True:
            self._feed()
            self.led.update()

            try:
                if time.time() - self.start_time > 43200:
                    print("[SYS] Scheduled 12h maintenance reboot...")
                    machine.reset()

                self.client.check_msg()

                new_topic = SystemTools.get_dynamic_topic()
                if new_topic != self.current_topic:
                    print(f"[MQTT] Rotating topic: {new_topic}")
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

                time.sleep(0.05)

            except Exception as e:
                print(f"[ERR] Runtime error: {e}")
                self.led.set_mode(LEDController.ERROR)
                time.sleep(5)
                machine.reset()


if __name__ == "__main__":
    app = WOLApp()
    app.run()
