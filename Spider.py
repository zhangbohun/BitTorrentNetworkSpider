# encoding: utf-8
import hashlib
import os.path
import random
import socket
from Queue import Queue
from struct import unpack, pack
from threading import Thread
from time import sleep

import MetadataInquirer
from libs import pymmh3, decodeh
from libs.SQLiteUtil import SQLiteUtil
from libs.bencode import bencode, bdecode


def random_id():
    return hashlib.sha1(''.join(chr(random.randint(0, 255)) for _ in xrange(20))).digest()

def get_neighbor_id(target, end=10):
    return target[:end] + random_id()[end:]


# node节点结构
class KNode(object):
    def __init__(self, nid, ip=None, port=None):
        self.nid = nid
        self.ip = ip
        self.port = port

    def __eq__(self, other):
        return other.nid == self.nid

    def __hash__(self):
        return hash(self.nid)

    @staticmethod
    def decode_nodes(nodes):
        """
        解析node串，每个node长度为26，其中20位为nid，4位为ip，2位为port
        数据格式: [ (node ID, ip, port),(node ID, ip, port),(node ID, ip, port).... ]
        """
        n = []
        length = len(nodes)
        if (length % 26) != 0:
            return n

        for i in xrange(0, length, 26):
            nid = nodes[i:i + 20]
            ip = socket.inet_ntoa(nodes[i + 20:i + 24])
            port = unpack('!H', nodes[i + 24:i + 26])[0]
            n.append((nid, ip, port))

        return n

    @staticmethod
    def encode_nodes(nodes):
        """ Encode a list of (id, connect_info) pairs into a node_info """
        n = []
        for node in nodes:
            n.extend([node.nid, long(''.join(['%02X' % long(i) for i in node.ip.split('.')]), 16), node.port])
        return pack('!' + '20sIH' * len(nodes), *n)


class Spider(Thread):
    def __init__(self, bind_ip, bind_port, max_node_size):
        Thread.__init__(self)
        self.setDaemon(True)

        self.isSpiderWorking = True

        self.nid = random_id()
        self.max_node_size = max_node_size
        self.node_list = []
        self.inquiry_info_queue = Queue()
        self.metadata_queue = Queue()

        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.ufd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.ufd.bind((self.bind_ip, self.bind_port))

    def start(self):
        Thread(target=self.join_dht).start()
        Thread(target=self.receiver).start()
        Thread(target=self.sniffer).start()
        for _ in xrange(100):  # 防止inquiry_info_queue消费过慢
            Thread(target=self.inquirer).start()
        Thread(target=self.recorder).start()
        Thread.start(self)

    def stop(self):
        self.isSpiderWorking = False

    # 加入DHT网络
    def join_dht(self):
        # 起始node
        BOOTSTRAP_NODES = [
            ('router.utorrent.com', 6881),
            ('router.bittorrent.com', 6881),
            ('dht.transmissionbt.com', 6881)
        ]
        for _ in xrange(20):
            if len(self.node_list) == 0:
                self.send_find_node(random.choice(BOOTSTRAP_NODES), self.nid)
            sleep(10)

    # 获取Node信息
    def sniffer(self):
        while self.isSpiderWorking:
            for _ in xrange(200):
                if len(self.node_list) == 0:
                    sleep(1)
                else:
                    # 伪装成目标相邻点在查找
                    # print('send packet')
                    node = self.node_list.pop(0)  # 线程安全 global interpreter lock
                    self.send_find_node((node.ip, node.port), get_neighbor_id(node.nid))
            sleep(10)

    # 接收ping, find_node, get_peers, announce_peer请求和find_node回复
    def receiver(self):
        while self.isSpiderWorking:
            try:
                (data, address) = self.ufd.recvfrom(65536)
                # print('receive udp packet')
                msg = bdecode(data)
                # print msg
                if msg['y'] == 'r':
                    if 'nodes' in msg['r']:
                        self.process_find_node_response(msg)
                elif msg['y'] == 'q':
                    if msg['q'] == 'ping':
                        self.send_pong(msg, address)
                    elif msg['q'] == 'find_node':
                        self.process_find_node_request(msg, address)
                    elif msg['q'] == 'get_peers':
                        self.process_get_peers_request(msg, address)
                    elif msg['q'] == 'announce_peer':
                        self.process_announce_peer_request(msg, address)
            except:
                pass

    # 发送本节点状态正常信息
    def send_pong(self, msg, address):
        msg = {
            't': msg['t'],
            'y': 'r',
            'r': {'id': self.nid}
        }
        self.ufd.sendto(bencode(msg), address)

    # 发送查询节点请求信息
    def send_find_node(self, address, nid, target_id=random_id()):
        msg = {
            't': ''.join(chr(random.randint(0, 255)) for _ in xrange(2)),
            'y': 'q',
            'q': 'find_node',
            'a': {'id': nid, 'target': target_id}
        }
        self.ufd.sendto(bencode(msg), address)

    # 处理查询节点请求的回复信息，用于获取新的有效节点
    def process_find_node_response(self, res):
        if len(self.node_list) > self.max_node_size:  # 限定队列大小
            return
        nodes = KNode.decode_nodes(res['r']['nodes'])
        for node in nodes:
            (nid, ip, port) = node
            if len(nid) != 20: continue
            if nid == self.nid: continue  # 排除自己
            if ip == self.bind_ip: continue
            if port < 1 or port > 65535: continue
            self.node_list.append(KNode(nid, ip, port))

    # 回应find_node请求信息
    def process_find_node_request(self, req, address):
        msg = {
            't': req['t'],
            'y': 'r',
            'r': {'id': get_neighbor_id(self.nid), 'nodes': KNode.encode_nodes(self.node_list[:8])}
        }
        self.ufd.sendto(bencode(msg), address)

    # 回应get_peer请求信息
    def process_get_peers_request(self, req, address):
        infohash = req['a']['info_hash']
        msg = {
            't': req['t'],
            'y': 'r',
            'r': {
                'id': get_neighbor_id(infohash, 3),
                'nodes': KNode.encode_nodes(self.node_list[:8]),
                'token': infohash[:4]  # 自定义token，例如取infohash最后四位
            }
        }
        self.ufd.sendto(bencode(msg), address)

    # 处理声明下载peer请求信息，用于获取有效的种子信息
    def process_announce_peer_request(self, req, address):
        infohash = req['a']['info_hash']
        token = req['a']['token']
        if infohash[:4] == token:  # 自定义的token规则校验
            if 'implied_port' in req['a'] and req['a']['implied_port'] != 0:
                port = address[1]
            else:
                port = req['a']['port']
                if port < 1 or port > 65535: return

        # print('announce_peer:' + infohash.encode('hex') + ' ip:' + address[0])
        self.inquiry_info_queue.put((infohash, (address[0], port)))  # 加入元数据获取信息队列

        self.send_pong(req, address)

    # 查询种子信息
    def inquirer(self):
        while self.isSpiderWorking:
            # 只用于保证局部无重复，实际数据唯一性通过数据库唯一键保证
            inquiry_info_bloom_filter = BloomFilter(5000, 5)
            for _ in xrange(1000):
                try:
                    announce = self.inquiry_info_queue.get(False)  # not block
                    if inquiry_info_bloom_filter.add(announce[0] + announce[1][0]):
                        # threads for download metadata
                        t = Thread(target=MetadataInquirer.inquire,
                                   args=(announce[0], announce[1], self.metadata_queue, 7))  # 超时时间不要太长防止短时间内线程过多
                        t.start()
                except:
                    pass

    # 记录种子信息
    def recorder(self):
        db_name = 'matadata.db'
        need_create_table = False
        if not os.path.exists(db_name):
            need_create_table = True
        sqlite_util = SQLiteUtil(db_name)

        if need_create_table:
            sqlite_util.executescript(
                'create table "matadata" ("hash" text primary key not null,"name"  text,"size"  text);')
        while self.isSpiderWorking:
            try:
                metadata = self.metadata_queue.get(False)  # not block
                name = metadata['name']
                try:
                    name = name.decode('utf8')
                except:
                    try:
                        name = name.decode('gb18030')
                    except:
                        try:
                            name = decodeh.decode(name)
                        except:
                            continue
                try:
                    sqlite_util.execute(
                        'insert into matadata (hash,name,size)values (?,?,?);',
                        (metadata['hash'], name, metadata['size']))
                    # import json
                    # print json.dumps(metadata, ensure_ascii=False).decode('utf-8')
                except:
                    # import traceback
                    # traceback.print_exc()
                    # 通过hash属性唯一键去重
                    # print metadata['hash']
                    pass
            except:
                sleep(0.5)


# 简化版布隆过滤器
class BloomFilter(object):
    def __init__(self, size, hash_count):
        self.bit_number = 0  # 初始化
        self.size = size
        self.hash_count = hash_count

    def add(self, item):
        for i in xrange(self.hash_count):
            index = pymmh3.hash(item, i) % self.size
            if not (self.bit_number >> index) & 1:  # 如果是0则是新的，返回True
                for j in xrange(self.hash_count):
                    index1 = pymmh3.hash(item, j) % self.size
                    self.bit_number |= 1 << index1
                return True
        return False


if __name__ == '__main__':
    threads = []
    for i in xrange(3):
        spider = Spider('0.0.0.0', 8087 + i, max_node_size=500)  # 需保证有公网ip且相应端口入方向通畅
        spider.start()

    sleep(60 * 60 * 60)  # 持续运行一段时间

    k = 0
    for i in threads:
        i.stop()
        i.join()
        k = k + 1
