# Secure ESP32 Wake-on-LAN (MQTT)

This project implements a secure, production-grade Wake-on-LAN (WOL) solution using an ESP32 and a public MQTT broker. It bypasses CGNAT and requires no port forwarding.

## 🚦 LED Status Codes

The onboard LED provides real-time feedback on the system's state.

| Pattern | Speed | Description |
| :--- | :--- | :--- |
| **Rapid Strobe** | ⚡ Very Fast (100ms) | **Booting / Initializing** <br> System is starting up and syncing NTP time. |
| **Fast Blink** | 🟠 Fast (300ms) | **Connecting** <br> Attempting to connect to WiFi or the MQTT Broker. |
| **Heartbeat** | 🟢 1 Short Flash every 4s | **Idle (Online)** <br> Connected securely and waiting for commands. |
| **Panic Strobe** | 🔴 Extremely Fast (50ms) | **Error / Failure** <br> Network failure or critical crash. System will reboot automatically. |

### Signal Flashes (Command Feedback)
When a command is received while in **Idle** mode, the LED will interrupt the heartbeat to signal the specific action:

*   **1 Flash:** 📩 Message received (processing signature).
*   **2 Flashes:** 📊 `STATUS` command valid. Ping response sent.
*   **3 Flashes:** 🚀 `WAKE` command valid. Magic Packet sent to target.