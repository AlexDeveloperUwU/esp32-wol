import socket
import struct
import time
import select
import ntptime
import ubinascii
import hashlib
import hmac
from config import WOL_MAC, WOL_IP, WOL_PORT, SECRET_KEY, TOPIC_BASE

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
    return TOPIC_BASE + time_str

def verify_payload(payload_str):
    try:
        parts = payload_str.split("|")
        if len(parts) != 3:
            return None, None
        
        cmd, timestamp, signature = parts[0], parts[1], parts[2]
        
        msg_ts = int(timestamp)
        
        # FIX: ESP32 Epoch (2000) vs Unix Epoch (1970) correction
        current_ts = time.time() + 946684800
        
        if abs(current_ts - msg_ts) > 60:
            print(f"Time diff error: ESP={current_ts} MSG={msg_ts}")
            return None, None

        check_str = cmd + timestamp
        calc_sig = hmac.new(SECRET_KEY.encode(), check_str.encode(), hashlib.sha256).hexdigest()
        
        if calc_sig != signature:
            print(f"Sig error: Calc={calc_sig} Recv={signature}")
            return None, None
            
        return cmd, timestamp
    except Exception as e:
        print(f"Verification error: {e}")
        return None, None

def send_magic_packet():
    mac_bytes = ubinascii.unhexlify(WOL_MAC.replace(":", "").replace("-", ""))
    payload = b'\xff' * 6 + mac_bytes * 16
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
        checksum = checksum & 0xffffffff
        i = i + 2
    if i < len(source):
        checksum = checksum + source[len(source) - 1]
        checksum = checksum & 0xffffffff
    checksum = (checksum >> 16) + (checksum & 0xffff)
    checksum = checksum + (checksum >> 16)
    answer = ~checksum
    answer = answer & 0xffff
    answer = answer >> 8 | (answer << 8 & 0xff00)
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