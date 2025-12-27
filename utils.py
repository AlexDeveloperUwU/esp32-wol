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


def sync_time():
    try:
        ntptime.host = "pool.ntp.org"
        ntptime.settime()
        return True
    except:
        return False


def get_dynamic_topic():
    t = time.gmtime()
    time_str = "{:04d}{:02d}{:02d}{:02d}".format(t[0], t[1], t[2], t[3])
    return "{}{}/{}".format(TOPIC_BASE, DEVICE_SERIAL, time_str)


def get_cipher_key():
    return hashlib.sha256(SECRET_KEY.encode()).digest()


def pad(data):
    block_size = 16
    padding = block_size - len(data) % block_size
    return data + (chr(padding) * padding).encode()


def unpad(data):
    padding = data[-1]
    return data[:-padding]


def encrypt_payload(plaintext):
    try:
        key = get_cipher_key()
        iv = os.urandom(16)
        cipher = ucryptolib.aes(key, 2, iv)
        padded_txt = pad(plaintext.encode())
        encrypted = cipher.encrypt(padded_txt)
        return (ubinascii.hexlify(iv) + b":" + ubinascii.hexlify(encrypted)).decode()
    except Exception as e:
        print(f"Encrypt error: {e}")
        return ""


def decrypt_payload(encrypted_str):
    try:
        parts = encrypted_str.split(":")
        if len(parts) != 2:
            return None

        iv = ubinascii.unhexlify(parts[0])
        ciphertext = ubinascii.unhexlify(parts[1])
        key = get_cipher_key()

        cipher = ucryptolib.aes(key, 2, iv)
        decrypted_padded = cipher.decrypt(ciphertext)
        return unpad(decrypted_padded).decode()
    except Exception as e:
        print(f"Decrypt error: {e}")
        return None


def verify_and_parse_msg(encrypted_msg):
    decrypted_str = decrypt_payload(encrypted_msg)
    if not decrypted_str:
        return None, None

    try:
        parts = decrypted_str.split("|")
        if len(parts) != 3:
            return None, None

        cmd, timestamp, signature = parts[0], parts[1], parts[2]
        msg_ts = int(timestamp)

        current_ts = time.time() + 946684800

        if abs(current_ts - msg_ts) > 60:
            print(f"Time diff error: ESP={current_ts} MSG={msg_ts}")
            return None, None

        check_str = cmd + timestamp
        calc_sig = hmac.new(
            SECRET_KEY.encode(), check_str.encode(), hashlib.sha256
        ).hexdigest()

        if calc_sig != signature:
            print("Invalid Signature")
            return None, None

        return cmd, timestamp
    except Exception as e:
        print(f"Parse error: {e}")
        return None, None


def send_magic_packet():
    mac_bytes = ubinascii.unhexlify(WOL_MAC.replace(":", "").replace("-", ""))
    payload = b"\xff" * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(payload, (WOL_IP, WOL_PORT))
    sock.close()


def get_checksum(source):
    checksum = 0
    count = (len(source) // 2) * 2
    i = 0
    while i < count:
        temp = source[i + 1] * 256 + source[i]
        checksum = checksum + temp
        checksum = checksum & 0xFFFFFFFF
        i = i + 2
    if i < len(source):
        checksum = checksum + source[len(source) - 1]
        checksum = checksum & 0xFFFFFFFF
    checksum = (checksum >> 16) + (checksum & 0xFFFF)
    checksum = checksum + (checksum >> 16)
    answer = ~checksum
    answer = answer & 0xFFFF
    answer = answer >> 8 | (answer << 8 & 0xFF00)
    return answer


def ping_device(host):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, 1)
        sock.setblocking(0)

        pkt_id = 0x1234
        pkt_seq = 1
        pkt_type = 8
        pkt_code = 0
        pkt_chk = 0

        header = struct.pack("!BBHHH", pkt_type, pkt_code, pkt_chk, pkt_id, pkt_seq)
        data = struct.pack("d", time.time())
        pkt_chk = get_checksum(header + data)
        header = struct.pack("!BBHHH", pkt_type, pkt_code, pkt_chk, pkt_id, pkt_seq)
        packet = header + data

        addr = socket.getaddrinfo(host, 1)[0][-1]
        sock.sendto(packet, addr)

        ready = select.select([sock], [], [], 2)
        if ready[0]:
            sock.close()
            return True

        sock.close()
        return False
    except:
        return False
