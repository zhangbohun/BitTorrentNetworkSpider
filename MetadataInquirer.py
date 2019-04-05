# encoding: utf-8
# 实现bep_0009获取元数据扩展协议
import gc
import hashlib
import math
import random
import re
import socket
from struct import pack
from time import sleep, time

from libs.bencode import bencode

BT_PROTOCOL = 'BitTorrent protocol'

def send_handshake(the_socket, infohash):
    bt_header = chr(len(BT_PROTOCOL)) + BT_PROTOCOL
    ext_bytes = '\x00\x00\x00\x00\x00\x10\x00\x01'
    peer_id = '-LT0100-' + hashlib.sha1(''.join(chr(random.randint(0, 255)) for _ in xrange(20))).digest()[:12]
    packet = bt_header + ext_bytes + infohash + peer_id
    the_socket.send(packet)

def check_handshake(packet, self_infohash):
    try:
        bt_header_len, packet = ord(packet[:1]), packet[1:]
        if bt_header_len != len(BT_PROTOCOL):
            return False
    except TypeError:
        return False

    bt_header, packet = packet[:bt_header_len], packet[bt_header_len:]
    if bt_header != BT_PROTOCOL:
        return False

    packet = packet[8:]
    infohash = packet[:20]
    if infohash != self_infohash:
        return False

    return True



# 握手确定 bep_0009 获取元数据扩展协议
BT_MSG_ID = 20
EXT_HANDSHAKE_ID = 0

def send_message(the_socket, msg):
    msg_len = pack('>I', len(msg))
    the_socket.send(msg_len + msg)

def send_ext_handshake(the_socket):
    msg = chr(BT_MSG_ID) + chr(EXT_HANDSHAKE_ID) + bencode({'m': {'ut_metadata': 1}})
    send_message(the_socket, msg)

def request_metadata(the_socket, ut_metadata, piece):
    msg = chr(BT_MSG_ID) + chr(ut_metadata) + bencode({'msg_type': 0, 'piece': piece})
    send_message(the_socket, msg)

def get_ut_metadata(data):
    ut_metadata = 'ut_metadata'
    index = data.index(ut_metadata) + len(ut_metadata) + 1
    return int(data[index])

def get_metadata_size(data):
    metadata_size = 'metadata_size'
    start = data.index(metadata_size) + len(metadata_size) + 1
    data = data[start:]
    return int(data[:data.index('e')])

def recv_all(the_socket, timeout=15):
    the_socket.setblocking(0)
    total_data = []
    begin = time()

    while True:
        sleep(0.05)
        if total_data and time() - begin > timeout:
            break
        elif time() - begin > timeout * 2:
            break
        try:
            data = the_socket.recv(1024)
            if data:
                total_data.append(data)
                begin = time()
        except:
            pass
    return ''.join(total_data)



def inquire(infohash, address, metadata_queue, timeout=15):
    """
    数据字典格式：
    {
      "hash": "9B4E6D5134988706C004F9B245A5B214E3EF1941",
      "name": "种子名称",
      "size": "18679173"
    }
    """
    info = {}
    the_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        the_socket.settimeout(timeout)
        the_socket.connect(address)

        # handshake
        send_handshake(the_socket, infohash)
        packet = the_socket.recv(4096)
        if not check_handshake(packet, infohash):
            return

        # ext handshake
        send_ext_handshake(the_socket)
        packet = the_socket.recv(4096)
        ut_metadata, metadata_size = get_ut_metadata(packet), get_metadata_size(packet)
        # request each piece of metadata
        metadata = []
        for piece in xrange(int(math.ceil(metadata_size / (16.0 * 1024)))):  # piece是个控制块，根据控制块下载数据
            request_metadata(the_socket, ut_metadata, piece)
            packet = recv_all(the_socket, timeout)
            metadata.append(packet[packet.index('ee') + 2:])
        metadata = ''.join(metadata)

        # 拼装数据
        info['hash'] = infohash.encode('hex')

        # 用bdecode解码可能获取不到数据，直接用正则获取
        info['name'] = ''
        match_obj = re.search(r':name\.utf-8(\d*?):', metadata, re.M | re.I)
        if match_obj:
            s0 = match_obj.group(0)
            s1 = match_obj.group(1)
            info['name'] = metadata[metadata.index(s0) + len(s0):metadata.index(s0) + len(s0) + int(s1)]
        else:
            match_obj = re.search(r':name(\d*?):', metadata, re.M | re.I)
            if match_obj:
                s0 = match_obj.group(0)
                s1 = match_obj.group(1)
                info['name'] = metadata[metadata.index(s0) + len(s0):metadata.index(s0) + len(s0) + int(s1)]

        info['size'] = 0
        for s in re.findall(r':lengthi(\d*?)e', metadata, re.M | re.I):
            info['size'] += int(s)
        info['size'] = str(info['size'])

        # 只记录有效元数据
        if info['size'] != '0' and info['name'] != '':
            metadata_queue.put(info)
        del metadata
        gc.collect()
    except:
        # import traceback
        # traceback.print_exc()
        pass
    finally:
        the_socket.close()  # 确保关闭socket


if __name__ == '__main__':
    # 本地uTorrent测试
    inquire(str(bytearray.fromhex('01EA65BA68C5F115B3BDF49A4CF60FC59B59BACA')), ('127.0.0.1', 6881), None, 1)