import hashlib
import hmac
import os
import select
import socket
import struct
import time

import ntptime
import ubinascii
import ucryptolib

from config import DEVICE_SERIAL, SECRET_KEY, TOPIC_BASE, WOL_IP, WOL_MAC, WOL_PORT


class CryptoManager:
    """
    <summary>Handles AES encryption/decryption and HMAC signature verification.</summary>
    """

    def __init__(self):
        self.key = hashlib.sha256(SECRET_KEY.encode()).digest()

    def _pad(self, data):
        block_size = 16
        padding = block_size - len(data) % block_size
        return data + (chr(padding) * padding).encode()

    def _unpad(self, data):
        return data[: -data[-1]]

    def encrypt(self, plaintext):
        try:
            iv = os.urandom(16)
            cipher = ucryptolib.aes(self.key, 2, iv)
            encrypted = cipher.encrypt(self._pad(plaintext.encode()))
            return (
                ubinascii.hexlify(iv) + b":" + ubinascii.hexlify(encrypted)
            ).decode()
        except Exception as e:
            print("[SEC] Encryption error:", e)
            return ""

    def decrypt(self, encrypted_str):
        try:
            parts = encrypted_str.split(":")
            if len(parts) != 2:
                return None
            iv = ubinascii.unhexlify(parts[0])
            ciphertext = ubinascii.unhexlify(parts[1])
            cipher = ucryptolib.aes(self.key, 2, iv)
            return self._unpad(cipher.decrypt(ciphertext)).decode()
        except:
            print("[SEC] Decryption failed: Invalid format or key mismatch")
            return None

    def verify_signature(self, cmd, timestamp, signature):
        try:
            check_str = cmd + timestamp
            calc_sig = hmac.new(
                SECRET_KEY.encode(), check_str.encode(), hashlib.sha256
            ).hexdigest()
            match = calc_sig == signature
            if not match:
                print("[SEC] Signature mismatch for cmd:", cmd)
            return match
        except:
            return False


class SystemTools:
    """
    <summary>Utility class for system time, topic generation, and metrics.</summary>
    """

    @staticmethod
    def sync_time():
        print("[NTP] Syncing with pool.ntp.org...")
        try:
            ntptime.host = "pool.ntp.org"
            ntptime.settime()
            print("[NTP] Success. UTC Time:", time.gmtime())
            return True
        except Exception as e:
            print("[NTP] Failed:", e)
            return False

    @staticmethod
    def get_dynamic_topic():
        t = time.gmtime()
        time_str = "{:04d}{:02d}{:02d}{:02d}".format(t[0], t[1], t[2], t[3])
        return "{}{}/{}".format(TOPIC_BASE, DEVICE_SERIAL, time_str)

    @staticmethod
    def get_metrics(start_time):
        import gc

        import network

        gc.collect()
        try:
            fs = os.statvfs("/")
            disk_free = fs[0] * fs[3]
        except:
            disk_free = 0
        try:
            rssi = network.WLAN(network.STA_IF).status("rssi")
        except:
            rssi = 0
        return '{"uptime":%d,"mem_free":%d,"mem_alloc":%d,"rssi":%d,"disk_free":%d}' % (
            int(time.time() - start_time),
            gc.mem_free(),
            gc.mem_alloc(),
            rssi,
            disk_free,
        )


class WOLService:
    """
    <summary>Provides network services for Wake-on-LAN and ICMP Ping.</summary>
    """

    @staticmethod
    def send_magic_packet():
        print(f"[WOL] Sending Magic Packet to {WOL_MAC} via {WOL_IP}...")
        try:
            mac_bytes = ubinascii.unhexlify(WOL_MAC.replace(":", "").replace("-", ""))
            payload = b"\xff" * 6 + mac_bytes * 16
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, (WOL_IP, WOL_PORT))
            sock.close()
            print("[WOL] Packet transmitted.")
        except Exception as e:
            print("[WOL] Error:", e)

    @staticmethod
    def _get_checksum(source):
        checksum = 0
        count = (len(source) // 2) * 2
        i = 0
        while i < count:
            checksum += source[i + 1] * 256 + source[i]
            checksum &= 0xFFFFFFFF
            i += 2
        if i < len(source):
            checksum += source[len(source) - 1]
            checksum &= 0xFFFFFFFF
        checksum = (checksum >> 16) + (checksum & 0xFFFF)
        checksum += checksum >> 16
        answer = ~checksum & 0xFFFF
        return answer >> 8 | (answer << 8 & 0xFF00)

    @staticmethod
    def ping_device(host):
        print(f"[PING] Testing connectivity to {host}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, 1)
            sock.setblocking(0)
            header = struct.pack("!BBHHH", 8, 0, 0, 0x1234, 1)
            data = struct.pack("d", time.time())
            chk = WOLService._get_checksum(header + data)
            header = struct.pack("!BBHHH", 8, 0, chk, 0x1234, 1)
            addr = socket.getaddrinfo(host, 1)[0][-1]
            sock.sendto(header + data, addr)
            ready = select.select([sock], [], [], 2)
            sock.close()
            result = True if ready[0] else False
            print(f"[PING] Result: {'ONLINE' if result else 'OFFLINE'}")
            return result
        except Exception as e:
            print("[PING] Error:", e)
            return False
