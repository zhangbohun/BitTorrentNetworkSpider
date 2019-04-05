# BitTorrentNetworkSpider
BitTorrent network matadata spider

本项目主要参考了SimDHT的实现，作为爬虫并没有正确完整的实现 KRPC 等相关协议

代码简要介绍，主要分为几个部分：

0. lib 库，包括 bencode（用于处理 B 编码），decodeh（用于处理可能的编码问题），pymmh3（用于实现简化版的布隆过滤器）,SQLiteUtil（用于实现 sqlite3 单线程操作）

1. sinffer 用于获取网络内的 Node 节点信息，主要依靠 KRPC 协议中定义的 find_node 方法

2. receiver 用于接收其他节点发来的信息，包括 find_node 回复（可以获取新的 node 信息），以及 ping（需要回应 pong），find_node，get_peers，announce_peer（可以获取到有用的种子信息）请求

3. inquirer 用于获取元数据，通过 MetadataInquirer 根据 bep_0009 获取元数据扩展协议实现

4. recorder 用于记录种子元数据到数据库，这里用的是标准库自带的 sqlite3

5. BloomFilter 通过 pymmh3 以及位操作实现的简化版的布隆过滤器用于数据过滤减少重复操作

6. 以上整体构成 Spider主要部分，另包括多线程，获取随机 id，以及 join_dht 加入 DHT 网络等实现