# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2025-12-28
### Added
- **Extended Stats:** The `USAGE` command now reports Disk usage, RAM usage, CPU Frequency, and Core count.
- **Multithreading:** LED status indicators now run on a dedicated thread (Core 0) to prevent blocking the main network loop (Core 1) and ensure smooth blinking patterns.
- **Connection Stability:** Added logic to the Web UI to prevent double connection attempts and properly clear polling intervals.

### Changed
- **Refactor:** Complete codebase restructure into modular classes (`WOLApp`, `CryptoManager`, `WOLService`) for better maintainability and organization.
- **Time Sync:** Increased NTP time skew tolerance from 60s to 120s to reduce false positive security rejections.
- **Network Hardening:** Improved `ping` utility with stricter timeouts and proper socket resource cleanup (`finally` block).

## [1.1.0] - 2025-12-27
### Changed
- **Security Upgrade:** All MQTT traffic is now encrypted using AES-256-CBC.
- **Addressing:** MQTT Topics now include a configurable `DEVICE_SERIAL` to support multiple devices on the same broker.
- **Web UI:** Removed hardcoded credentials. Added a Settings UI to configure Target Serial and Secret Key (saved in LocalStorage).
- **Core:** Refactored `utils.py` to handle PKCS7 padding and AES encryption.

## [1.0.0] - 2025-12-27
### Added
- Initial version of the Secure ESP32 WOL system.
- Secure HMAC-SHA256 command verification.
- Dynamic MQTT topic rotation based on UTC time.
- Responsive Tailwind-based web controller.
- GitHub Actions workflow for automatic deployment and releases.
