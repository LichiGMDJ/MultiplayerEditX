from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# =============================================================================
# Binary protocol: reliable envelope/ACK + integrity/repair control messages.
# This patch runs after patch_turn_udp.py, so ProtocolHello already exists.
# =============================================================================
proto_hpp_path = Path("src/BinaryProtocol.hpp")
proto_hpp = proto_hpp_path.read_text(encoding="utf-8")

proto_hpp = replace_once(
    proto_hpp,
    '''        Reconnect         = 0x34,\n        ProtocolHello     = 0x35,\n\n        // Cursor (unreliable channel)''',
    '''        Reconnect         = 0x34,\n        ProtocolHello     = 0x35,\n        ReliableEnvelope = 0x36,\n        ReliableAck      = 0x37,\n        LevelDigest      = 0x38,\n        LevelManifest    = 0x39,\n        LevelRepairRequest = 0x3A,\n        FullResyncRequest  = 0x3B,\n\n        // Cursor (unreliable channel)''',
    "reliability protocol opcodes",
)

proto_hpp = replace_once(
    proto_hpp,
    '''    std::vector<uint8_t> serializePlayerLeft(int playerId);\n    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion);\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    '''    std::vector<uint8_t> serializePlayerLeft(int playerId);\n    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion);\n\n    std::vector<uint8_t> serializeReliableEnvelope(\n        uint32_t sequence, std::vector<uint8_t> const& payload);\n    std::vector<uint8_t> serializeReliableAck(uint32_t sequence);\n\n    std::vector<uint8_t> serializeLevelDigest(uint32_t objectCount, std::string const& hash);\n\n    struct LevelManifestEntry {\n        std::string uuid;\n        std::string hash;\n    };\n    std::vector<uint8_t> serializeLevelManifest(\n        uint32_t scanId, uint32_t chunkIndex, uint32_t totalChunks,\n        std::vector<LevelManifestEntry> const& entries);\n    std::vector<uint8_t> serializeLevelRepairRequest(\n        uint32_t scanId,\n        std::vector<std::string> const& missing,\n        std::vector<std::string> const& changed);\n    std::vector<uint8_t> serializeFullResyncRequest();\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    "reliability serializer declarations",
)

proto_hpp = replace_once(
    proto_hpp,
    '''    struct ProtocolHelloMsg {\n        uint32_t protocolVersion = 0;\n    };\n    ProtocolHelloMsg deserializeProtocolHello(Reader& r);\n\n    struct ErrorMsg {''',
    '''    struct ProtocolHelloMsg {\n        uint32_t protocolVersion = 0;\n    };\n    ProtocolHelloMsg deserializeProtocolHello(Reader& r);\n\n    struct ReliableEnvelopeMsg {\n        uint32_t sequence = 0;\n        std::vector<uint8_t> payload;\n    };\n    ReliableEnvelopeMsg deserializeReliableEnvelope(Reader& r);\n\n    struct ReliableAckMsg {\n        uint32_t sequence = 0;\n    };\n    ReliableAckMsg deserializeReliableAck(Reader& r);\n\n    struct LevelDigestMsg {\n        uint32_t objectCount = 0;\n        std::string hash;\n    };\n    LevelDigestMsg deserializeLevelDigest(Reader& r);\n\n    struct LevelManifestMsg {\n        uint32_t scanId = 0;\n        uint32_t chunkIndex = 0;\n        uint32_t totalChunks = 0;\n        std::vector<LevelManifestEntry> entries;\n    };\n    LevelManifestMsg deserializeLevelManifest(Reader& r);\n\n    struct LevelRepairRequestMsg {\n        uint32_t scanId = 0;\n        std::vector<std::string> missing;\n        std::vector<std::string> changed;\n    };\n    LevelRepairRequestMsg deserializeLevelRepairRequest(Reader& r);\n\n    struct FullResyncRequestMsg {};\n    FullResyncRequestMsg deserializeFullResyncRequest(Reader& r);\n\n    struct ErrorMsg {''',
    "reliability deserializer declarations",
)

proto_hpp_path.write_text(proto_hpp, encoding="utf-8")


proto_cpp_path = Path("src/BinaryProtocol.cpp")
proto_cpp = proto_cpp_path.read_text(encoding="utf-8")

proto_cpp = replace_once(
    proto_cpp,
    '''    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion) {\n        Writer w;\n        w.writeOpcode(Opcode::ProtocolHello);\n        w.writeVarInt(protocolVersion);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    '''    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion) {\n        Writer w;\n        w.writeOpcode(Opcode::ProtocolHello);\n        w.writeVarInt(protocolVersion);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeReliableEnvelope(\n        uint32_t sequence, std::vector<uint8_t> const& payload)\n    {\n        Writer w(payload.size() + 16);\n        w.writeOpcode(Opcode::ReliableEnvelope);\n        w.writeVarInt(sequence);\n        w.writeVarInt(static_cast<uint32_t>(payload.size()));\n        if (!payload.empty()) w.writeBytes(payload.data(), payload.size());\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeReliableAck(uint32_t sequence) {\n        Writer w;\n        w.writeOpcode(Opcode::ReliableAck);\n        w.writeVarInt(sequence);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeLevelDigest(uint32_t objectCount, std::string const& hash) {\n        Writer w;\n        w.writeOpcode(Opcode::LevelDigest);\n        w.writeVarInt(objectCount);\n        w.writeString(hash);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeLevelManifest(\n        uint32_t scanId, uint32_t chunkIndex, uint32_t totalChunks,\n        std::vector<LevelManifestEntry> const& entries)\n    {\n        Writer w;\n        w.writeOpcode(Opcode::LevelManifest);\n        w.writeVarInt(scanId);\n        w.writeVarInt(chunkIndex);\n        w.writeVarInt(totalChunks);\n        w.writeVarInt(static_cast<uint32_t>(entries.size()));\n        for (auto const& entry : entries) {\n            w.writeString(entry.uuid);\n            w.writeString(entry.hash);\n        }\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeLevelRepairRequest(\n        uint32_t scanId,\n        std::vector<std::string> const& missing,\n        std::vector<std::string> const& changed)\n    {\n        Writer w;\n        w.writeOpcode(Opcode::LevelRepairRequest);\n        w.writeVarInt(scanId);\n        w.writeVarInt(static_cast<uint32_t>(missing.size()));\n        for (auto const& uuid : missing) w.writeString(uuid);\n        w.writeVarInt(static_cast<uint32_t>(changed.size()));\n        for (auto const& uuid : changed) w.writeString(uuid);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeFullResyncRequest() {\n        Writer w;\n        w.writeOpcode(Opcode::FullResyncRequest);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    "reliability serializers",
)

proto_cpp = replace_once(
    proto_cpp,
    '''    ProtocolHelloMsg deserializeProtocolHello(Reader& r) {\n        ProtocolHelloMsg msg;\n        msg.protocolVersion = r.readVarInt();\n        return msg;\n    }\n\n    ErrorMsg deserializeError(Reader& r) {''',
    '''    ProtocolHelloMsg deserializeProtocolHello(Reader& r) {\n        ProtocolHelloMsg msg;\n        msg.protocolVersion = r.readVarInt();\n        return msg;\n    }\n\n    ReliableEnvelopeMsg deserializeReliableEnvelope(Reader& r) {\n        ReliableEnvelopeMsg msg;\n        msg.sequence = r.readVarInt();\n        uint32_t len = r.readVarInt();\n        if (r.hasError() || len > r.remaining()) return msg;\n        msg.payload.assign(r.currentPtr(), r.currentPtr() + len);\n        r.skip(len);\n        return msg;\n    }\n\n    ReliableAckMsg deserializeReliableAck(Reader& r) {\n        ReliableAckMsg msg;\n        msg.sequence = r.readVarInt();\n        return msg;\n    }\n\n    LevelDigestMsg deserializeLevelDigest(Reader& r) {\n        LevelDigestMsg msg;\n        msg.objectCount = r.readVarInt();\n        msg.hash = r.readString();\n        return msg;\n    }\n\n    LevelManifestMsg deserializeLevelManifest(Reader& r) {\n        LevelManifestMsg msg;\n        msg.scanId = r.readVarInt();\n        msg.chunkIndex = r.readVarInt();\n        msg.totalChunks = r.readVarInt();\n        uint32_t count = r.readVarInt();\n        msg.entries.reserve(count);\n        for (uint32_t i = 0; i < count; ++i) {\n            LevelManifestEntry entry;\n            entry.uuid = r.readString();\n            entry.hash = r.readString();\n            msg.entries.push_back(std::move(entry));\n        }\n        return msg;\n    }\n\n    LevelRepairRequestMsg deserializeLevelRepairRequest(Reader& r) {\n        LevelRepairRequestMsg msg;\n        msg.scanId = r.readVarInt();\n        uint32_t missingCount = r.readVarInt();\n        msg.missing.reserve(missingCount);\n        for (uint32_t i = 0; i < missingCount; ++i) msg.missing.push_back(r.readString());\n        uint32_t changedCount = r.readVarInt();\n        msg.changed.reserve(changedCount);\n        for (uint32_t i = 0; i < changedCount; ++i) msg.changed.push_back(r.readString());\n        return msg;\n    }\n\n    FullResyncRequestMsg deserializeFullResyncRequest(Reader&) {\n        return {};\n    }\n\n    ErrorMsg deserializeError(Reader& r) {''',
    "reliability deserializers",
)

proto_cpp_path.write_text(proto_cpp, encoding="utf-8")


# =============================================================================
# P2PManager: application-level sequence/ACK, retry, reconnect classification.
# =============================================================================
p2p_hpp_path = Path("src/P2PManager.hpp")
p2p_hpp = p2p_hpp_path.read_text(encoding="utf-8")

p2p_hpp = p2p_hpp.replace('#include <atomic>\n', '#include <atomic>\n#include <unordered_set>\n#include <deque>\n#include <cstdint>\n')

p2p_hpp = replace_once(
    p2p_hpp,
    '''        std::string getError() const;\n\n\n\n        void send(std::vector<uint8_t> const& data, ChannelType channel = ChannelType::Reliable);''',
    '''        std::string getError() const;\n        bool isPeerReconnect(int playerId);\n\n\n\n        void send(std::vector<uint8_t> const& data, ChannelType channel = ChannelType::Reliable);''',
    "reconnect query declaration",
)

p2p_hpp = replace_once(
    p2p_hpp,
    '''            std::vector<std::vector<uint8_t>> bulkReliableQueue;''',
    '''            std::vector<std::vector<uint8_t>> bulkReliableQueue;\n\n            struct PendingAck {\n                std::vector<uint8_t> envelope;\n                uint64_t lastSentMs = 0;\n                uint32_t attempts = 0;\n                bool queued = true;\n            };\n            uint32_t nextReliableSequence = 1;\n            std::unordered_map<uint32_t, PendingAck> pendingReliableAcks;\n            std::unordered_set<uint32_t> receivedReliableSequences;\n            std::deque<uint32_t> receivedReliableOrder;\n            bool reconnecting = false;''',
    "per-peer ACK state",
)

p2p_hpp = replace_once(
    p2p_hpp,
    '''        void relayMessage(int fromPlayerId, const uint8_t* data, size_t len, ChannelType channel);\n        void flushBulkReliableQueues();\n        void checkPeerReady(int playerId);''',
    '''        void relayMessage(int fromPlayerId, const uint8_t* data, size_t len, ChannelType channel);\n        void flushBulkReliableQueues();\n        void scheduleClientReconnect();\n        void checkPeerReady(int playerId);''',
    "reconnect helper declaration",
)

p2p_hpp = replace_once(
    p2p_hpp,
    '''        int m_nextPlayerId = 1; // host assigns IDs (host = 0)''',
    '''        int m_nextPlayerId = 1; // host assigns IDs (host = 0)\n        std::unordered_map<std::string, uint64_t> m_recentDisconnectedNames;\n        std::atomic<bool> m_reconnectScheduled{false};\n        int m_reconnectAttempts = 0;''',
    "reconnect manager state",
)

p2p_hpp_path.write_text(p2p_hpp, encoding="utf-8")


p2p_cpp_path = Path("src/P2PManager.cpp")
p2p_cpp = p2p_cpp_path.read_text(encoding="utf-8")

# Protocol v2 is intentionally incompatible with pre-ACK builds.
p2p_cpp = replace_once(
    p2p_cpp,
    'constexpr uint32_t kProtocolVersion = 1;',
    'constexpr uint32_t kProtocolVersion = 2;',
    "protocol version v2",
)

# Timestamp helper used by ACK retransmission and reconnect classification.
p2p_cpp = replace_once(
    p2p_cpp,
    '''    namespace {\n        constexpr uint32_t kProtocolVersion = 2;\n    }''',
    '''    namespace {\n        constexpr uint32_t kProtocolVersion = 2;\n\n        uint64_t reliabilityNowMs() {\n            return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(\n                std::chrono::steady_clock::now().time_since_epoch()\n            ).count());\n        }\n    }''',
    "reliability timestamp helper",
)

p2p_cpp = replace_once(
    p2p_cpp,
    '''    std::string P2PManager::getError() const {\n        std::lock_guard lock(m_stateMutex);\n        return m_error;\n    }''',
    '''    std::string P2PManager::getError() const {\n        std::lock_guard lock(m_stateMutex);\n        return m_error;\n    }\n\n    bool P2PManager::isPeerReconnect(int playerId) {\n        std::lock_guard lock(m_peersMutex);\n        auto it = m_peers.find(playerId);\n        return it != m_peers.end() && it->second.reconnecting;\n    }''',
    "reconnect query implementation",
)

# Add tracked envelope creation next to sendRaw in sendTo().
p2p_cpp = replace_once(
    p2p_cpp,
    '''            auto sendRaw = [&](std::vector<uint8_t> const& payload) -> bool {''',
    '''            auto queueTrackedReliable = [&](std::vector<uint8_t> const& payload) -> bool {\n                constexpr size_t kMaxTrackedReliable = 8192;\n                if (peer.pendingReliableAcks.size() >= kMaxTrackedReliable) {\n                    log::error(\n                        "P2PManager: tracked reliable window full for player {}; opcode {} rejected",\n                        playerId,\n                        payload.empty() ? -1 : static_cast<int>(payload[0])\n                    );\n                    return false;\n                }\n\n                uint32_t sequence = peer.nextReliableSequence++;\n                if (sequence == 0) sequence = peer.nextReliableSequence++;\n                auto envelope = proto::serializeReliableEnvelope(sequence, payload);\n                peer.pendingReliableAcks[sequence] = PeerInfo::PendingAck {\n                    envelope, 0, 0, true\n                };\n                peer.bulkReliableQueue.push_back(std::move(envelope));\n                log::debug(\n                    "P2PManager: TX queued #{} opcode={} player={}",\n                    sequence,\n                    payload.empty() ? -1 : static_cast<int>(payload[0]),\n                    playerId\n                );\n                return true;\n            };\n\n            auto sendRaw = [&](std::vector<uint8_t> const& payload) -> bool {''',
    "tracked reliable enqueue helper",
)

# Queue-first editor traffic now gets wrapped in a sequence envelope.
p2p_cpp = replace_once(
    p2p_cpp,
    '''                            peer.bulkReliableQueue.push_back(data);\n                            log::debug(\n                                "P2PManager: queued reliable editor opcode {} for ordered delivery to player {} (queue={})",\n                                static_cast<int>(data[0]),\n                                playerId,\n                                peer.bulkReliableQueue.size()\n                            );''',
    '''                            queueTrackedReliable(data);\n                            log::debug(\n                                "P2PManager: queued reliable editor opcode {} for ordered ACK delivery to player {} (queue={})",\n                                static_cast<int>(data[0]),\n                                playerId,\n                                peer.bulkReliableQueue.size()\n                            );''',
    "wrap normal reliable editor packets",
)

# Integrity messages mutate/repair editor state and must use the same ordered ACK path.
p2p_cpp = replace_once(
    p2p_cpp,
    '''                        opcode == proto::Opcode::SyncLevelStart ||\n                        opcode == proto::Opcode::SyncLevelChunk ||\n                        opcode == proto::Opcode::SyncLevelEnd;''',
    '''                        opcode == proto::Opcode::SyncLevelStart ||\n                        opcode == proto::Opcode::SyncLevelChunk ||\n                        opcode == proto::Opcode::SyncLevelEnd ||\n                        opcode == proto::Opcode::LevelDigest ||\n                        opcode == proto::Opcode::LevelManifest ||\n                        opcode == proto::Opcode::LevelRepairRequest ||\n                        opcode == proto::Opcode::FullResyncRequest;''',
    "integrity traffic in ACK FIFO",
)

# Split PlaceObjects batches must also be tracked/ACKed rather than raw FIFO entries.
p2p_cpp = replace_once(
    p2p_cpp,
    '''                    peer.bulkReliableQueue.push_back(std::move(payload));\n                    sentObjects += batch.size();''',
    '''                    queueTrackedReliable(payload);\n                    sentObjects += batch.size();''',
    "wrap split placement batches",
)

# Before the normal incoming queue path, consume ACK/envelope control messages.
p2p_cpp = replace_once(
    p2p_cpp,
    '''        if (!protocolVerified) return;\n\n        {\n            std::lock_guard lock(m_incomingMutex);''',
    '''        if (!protocolVerified) return;\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::ReliableAck)) {\n            proto::Reader ackReader(data + 1, len - 1);\n            auto ack = proto::deserializeReliableAck(ackReader);\n            if (ackReader.hasError()) return;\n\n            std::lock_guard lock(m_peersMutex);\n            auto it = m_peers.find(fromPlayerId);\n            if (it != m_peers.end()) {\n                it->second.pendingReliableAcks.erase(ack.sequence);\n                auto& queue = it->second.bulkReliableQueue;\n                for (auto qit = queue.begin(); qit != queue.end(); ) {\n                    if (!qit->empty() && (*qit)[0] == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {\n                        proto::Reader qr(qit->data() + 1, qit->size() - 1);\n                        auto qm = proto::deserializeReliableEnvelope(qr);\n                        if (!qr.hasError() && qm.sequence == ack.sequence) {\n                            qit = queue.erase(qit);\n                            continue;\n                        }\n                    }\n                    ++qit;\n                }\n                log::debug("P2PManager: ACK #{} from player {}", ack.sequence, fromPlayerId);\n            }\n            return;\n        }\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {\n            proto::Reader envelopeReader(data + 1, len - 1);\n            auto envelope = proto::deserializeReliableEnvelope(envelopeReader);\n            if (envelopeReader.hasError() || envelope.payload.empty()) {\n                log::warn("P2PManager: malformed reliable envelope from player {}", fromPlayerId);\n                return;\n            }\n\n            auto ack = proto::serializeReliableAck(envelope.sequence);\n            sendTo(fromPlayerId, ack, ChannelType::Reliable);\n\n            bool duplicate = false;\n            {\n                std::lock_guard lock(m_peersMutex);\n                auto it = m_peers.find(fromPlayerId);\n                if (it != m_peers.end()) {\n                    auto& seen = it->second.receivedReliableSequences;\n                    duplicate = seen.contains(envelope.sequence);\n                    if (!duplicate) {\n                        seen.insert(envelope.sequence);\n                        it->second.receivedReliableOrder.push_back(envelope.sequence);\n                        constexpr size_t kMaxRememberedSequences = 4096;\n                        while (it->second.receivedReliableOrder.size() > kMaxRememberedSequences) {\n                            auto old = it->second.receivedReliableOrder.front();\n                            it->second.receivedReliableOrder.pop_front();\n                            seen.erase(old);\n                        }\n                    }\n                }\n            }\n\n            if (duplicate) {\n                log::debug("P2PManager: duplicate #{} from player {} ACKed and ignored", envelope.sequence, fromPlayerId);\n                return;\n            }\n\n            log::debug(\n                "P2PManager: RX #{} opcode={} player={}",\n                envelope.sequence,\n                static_cast<int>(envelope.payload[0]),\n                fromPlayerId\n            );\n            onPeerMessage(fromPlayerId, envelope.payload.data(), envelope.payload.size());\n            return;\n        }\n\n        {\n            std::lock_guard lock(m_incomingMutex);''',
    "ACK and envelope receive path",
)

# Upgrade the queue drain with ACK timeout retransmission and sent timestamps.
p2p_cpp = replace_once(
    p2p_cpp,
    '''    void P2PManager::flushBulkReliableQueues() {\n        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;\n\n        std::lock_guard lock(m_peersMutex);\n        for (auto& [playerId, peer] : m_peers) {\n            if (!peer.ready || !peer.reliable || !peer.reliable->isOpen()) continue;\n\n            size_t sentThisTick = 0;''',
    '''    void P2PManager::flushBulkReliableQueues() {\n        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;\n        constexpr uint64_t kAckTimeoutMs = 900;\n        auto now = reliabilityNowMs();\n\n        std::lock_guard lock(m_peersMutex);\n        for (auto& [playerId, peer] : m_peers) {\n            if (!peer.ready || !peer.reliable || !peer.reliable->isOpen()) continue;\n\n            for (auto& [sequence, pending] : peer.pendingReliableAcks) {\n                if (!pending.queued && pending.lastSentMs > 0 && now - pending.lastSentMs >= kAckTimeoutMs) {\n                    peer.bulkReliableQueue.push_back(pending.envelope);\n                    pending.queued = true;\n                    log::warn(\n                        "P2PManager: RETRY #{} player={} attempt={}",\n                        sequence,\n                        playerId,\n                        pending.attempts + 1\n                    );\n                }\n            }\n\n            size_t sentThisTick = 0;''',
    "ACK timeout retransmission",
)

p2p_cpp = replace_once(
    p2p_cpp,
    '''                    peer.reliable->send(\n                        reinterpret_cast<const std::byte*>(payload.data()),\n                        payload.size()\n                    );\n                    peer.bulkReliableQueue.erase(peer.bulkReliableQueue.begin());\n                    ++sentThisTick;''',
    '''                    peer.reliable->send(\n                        reinterpret_cast<const std::byte*>(payload.data()),\n                        payload.size()\n                    );\n\n                    if (!payload.empty() && payload[0] == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {\n                        proto::Reader sentReader(payload.data() + 1, payload.size() - 1);\n                        auto sentEnvelope = proto::deserializeReliableEnvelope(sentReader);\n                        if (!sentReader.hasError()) {\n                            auto pendingIt = peer.pendingReliableAcks.find(sentEnvelope.sequence);\n                            if (pendingIt != peer.pendingReliableAcks.end()) {\n                                pendingIt->second.lastSentMs = reliabilityNowMs();\n                                pendingIt->second.attempts += 1;\n                                pendingIt->second.queued = false;\n                            }\n                        }\n                    }\n\n                    peer.bulkReliableQueue.erase(peer.bulkReliableQueue.begin());\n                    ++sentThisTick;''',
    "record tracked send timestamp",
)

# Remember unexpectedly disconnected host clients by name so a fast rejoin can
# use digest/repair instead of an unconditional initial full sync.
p2p_cpp = replace_once(
    p2p_cpp,
    '''    void P2PManager::onPeerDisconnected(int playerId, bool unexpected) {\n        {\n            std::lock_guard lock(m_peersMutex);\n            auto it = m_peers.find(playerId);\n            if (it != m_peers.end()) {\n                if (it->second.pc) it->second.pc->close();\n                m_peers.erase(it);\n            }\n        }''',
    '''    void P2PManager::onPeerDisconnected(int playerId, bool unexpected) {\n        {\n            std::lock_guard lock(m_peersMutex);\n            auto it = m_peers.find(playerId);\n            if (it != m_peers.end()) {\n                if (unexpected && m_role == Role::Host && !it->second.playerName.empty()) {\n                    m_recentDisconnectedNames[it->second.playerName] = reliabilityNowMs();\n                }\n                if (it->second.pc) it->second.pc->close();\n                m_peers.erase(it);\n            }\n        }''',
    "remember disconnected client",
)

p2p_cpp = replace_once(
    p2p_cpp,
    '''            if (m_role == Role::Client && playerId == 0) {\n                for (auto& cb : m_onError) {\n                    cb("Host disconnected");\n                }\n                return;\n            }''',
    '''            if (m_role == Role::Client && playerId == 0) {\n                if (unexpected) {\n                    m_state.store(State::Reconnecting);\n                    scheduleClientReconnect();\n                    return;\n                }\n                for (auto& cb : m_onError) {\n                    cb("Host disconnected");\n                }\n                return;\n            }''',
    "client reconnect instead of immediate session failure",
)

# Classify same-name fast rejoin as reconnect.
p2p_cpp = replace_once(
    p2p_cpp,
    '''        peer.playerId = clientPlayerId;\n        peer.playerName = clientName;\n        peer.colorIndex = clientPlayerId % 6;''',
    '''        peer.playerId = clientPlayerId;\n        peer.playerName = clientName;\n        peer.colorIndex = clientPlayerId % 6;\n\n        auto recentIt = m_recentDisconnectedNames.find(clientName);\n        if (recentIt != m_recentDisconnectedNames.end()) {\n            constexpr uint64_t kReconnectIdentityWindowMs = 20000;\n            if (reliabilityNowMs() - recentIt->second <= kReconnectIdentityWindowMs) {\n                peer.reconnecting = true;\n                log::info("P2PManager: player {} ({}) classified as reconnect", clientPlayerId, clientName);\n            }\n            m_recentDisconnectedNames.erase(recentIt);\n        }''',
    "reconnect classification",
)

# Reset reconnect attempt state once both channels are back.
p2p_cpp = replace_once(
    p2p_cpp,
    '''        if (m_role == Role::Client && pid == 0) {\n            m_state.store(State::Connected);\n            stopSignalPolling();\n        }''',
    '''        if (m_role == Role::Client && pid == 0) {\n            m_state.store(State::Connected);\n            m_reconnectAttempts = 0;\n            m_reconnectScheduled.store(false);\n            stopSignalPolling();\n        }''',
    "reset reconnect state",
)

# Reconnect scheduler: reuses the room join endpoint and preserves the editor.
p2p_cpp = replace_once(
    p2p_cpp,
    '''    void P2PManager::leaveSession() {''',
    '''    void P2PManager::scheduleClientReconnect() {\n        if (m_role != Role::Client) return;\n        if (m_reconnectScheduled.exchange(true)) return;\n\n        constexpr int kMaxReconnectAttempts = 6;\n        if (m_reconnectAttempts >= kMaxReconnectAttempts) {\n            m_reconnectScheduled.store(false);\n            m_state.store(State::Error);\n            for (auto& cb : m_onError) cb("Reconnect failed");\n            return;\n        }\n\n        int attempt = ++m_reconnectAttempts;\n        int delayMs = std::min(5000, 500 * (1 << std::min(attempt - 1, 3)));\n        auto room = getRoomCode();\n        auto name = m_localPlayerName;\n\n        log::warn(\n            "P2PManager: scheduling reconnect attempt {} in {} ms",\n            attempt,\n            delayMs\n        );\n\n        std::thread([this, delayMs, room, name]() {\n            std::this_thread::sleep_for(std::chrono::milliseconds(delayMs));\n            queueInMainThread([this, room, name]() {\n                m_reconnectScheduled.store(false);\n                if (m_role != Role::Client || m_state.load() != State::Reconnecting) return;\n                stopSignalPolling();\n                log::info("P2PManager: reconnecting to room {}", room);\n                signalingJoinRoom(room, name);\n            });\n        }).detach();\n    }\n\n\n    void P2PManager::leaveSession() {''',
    "reconnect scheduler implementation",
)

# During reconnect, HTTP join failures should retry instead of destroying the session.
p2p_cpp = p2p_cpp.replace(
    '''                } else if (res.code() == 404) {\n                    std::vector<ErrorCb> callbacks;''',
    '''                } else if (res.code() == 404) {\n                    if (m_state.load() == State::Reconnecting) {\n                        log::warn("P2PManager: reconnect join returned 404; retrying");\n                        scheduleClientReconnect();\n                        return;\n                    }\n                    std::vector<ErrorCb> callbacks;''',
    1,
)
p2p_cpp = p2p_cpp.replace(
    '''                } else {\n                    std::vector<ErrorCb> callbacks;\n                    std::string err;\n                    {\n                        std::lock_guard lock(m_stateMutex);\n                        m_error = "Failed to join room: " + std::to_string(res.code());''',
    '''                } else {\n                    if (m_state.load() == State::Reconnecting) {\n                        log::warn("P2PManager: reconnect join failed with {}; retrying", res.code());\n                        scheduleClientReconnect();\n                        return;\n                    }\n                    std::vector<ErrorCb> callbacks;\n                    std::string err;\n                    {\n                        std::lock_guard lock(m_stateMutex);\n                        m_error = "Failed to join room: " + std::to_string(res.code());''',
    1,
)

p2p_cpp_path.write_text(p2p_cpp, encoding="utf-8")


# =============================================================================
# RemoteActionHandler: stable level digest, manifest diff and targeted repair.
# =============================================================================
remote_hpp_path = Path("src/RemoteActionHandler.hpp")
remote_hpp = remote_hpp_path.read_text(encoding="utf-8")

remote_hpp = replace_once(
    remote_hpp,
    '''        std::unordered_map<GameObject*, std::string>& getTrackedSelections() { return m_preSelectSaveStrings; }''',
    '''        std::unordered_map<GameObject*, std::string>& getTrackedSelections() { return m_preSelectSaveStrings; }\n\n        struct IntegrityEntry {\n            std::string uuid;\n            std::string hash;\n        };\n        std::pair<uint32_t, std::string> computeLevelDigest() const;\n        std::vector<IntegrityEntry> buildLevelManifest() const;\n        std::vector<ActionSerializer::ObjectData> getObjectDataForUuids(\n            std::vector<std::string> const& uuids) const;\n        void sendLevelDigestTo(int playerId);\n        void sendLevelManifestTo(int playerId);''',
    "integrity public API",
)

remote_hpp = replace_once(
    remote_hpp,
    '''        std::vector<PendingPlacement> m_pendingPlacements;''',
    '''        std::vector<PendingPlacement> m_pendingPlacements;\n\n        struct RepairManifestState {\n            bool active = false;\n            int hostPlayerId = -1;\n            uint32_t scanId = 0;\n            uint32_t totalChunks = 0;\n            std::vector<bool> received;\n            std::vector<IntegrityEntry> entries;\n        };\n        RepairManifestState m_repairManifest;''',
    "repair manifest state",
)

remote_hpp_path.write_text(remote_hpp, encoding="utf-8")


remote_cpp_path = Path("src/RemoteActionHandler.cpp")
remote_cpp = remote_cpp_path.read_text(encoding="utf-8")
remote_cpp = remote_cpp.replace('#include <cmath>\n', '#include <cmath>\n#include <algorithm>\n#include <unordered_set>\n')

# Forward declaration for the full SyncLevel fallback implemented in EditorHooks.cpp.
remote_cpp = replace_once(
    remote_cpp,
    '''namespace mpedit {\n\n    namespace {''',
    '''namespace mpedit {\n\n    void sendFullLevelSyncTo(int targetPlayerId);\n\n    namespace {''',
    "full sync helper forward declaration",
)

# Stable FNV-1a helper; unlike std::hash this is deterministic across processes.
remote_cpp = replace_once(
    remote_cpp,
    '''        void applyTransformSafe(GameObject* obj, float rotation, float scaleX, float scaleY, bool flipX, bool flipY) {''',
    '''        std::string stableIntegrityHash(std::string const& value) {\n            uint64_t hash = 1469598103934665603ull;\n            for (unsigned char c : value) {\n                hash ^= static_cast<uint64_t>(c);\n                hash *= 1099511628211ull;\n            }\n            std::ostringstream out;\n            out << std::hex << std::setw(16) << std::setfill('0') << hash;\n            return out.str();\n        }\n\n        void applyTransformSafe(GameObject* obj, float rotation, float scaleX, float scaleY, bool flipX, bool flipY) {''',
    "stable integrity hash helper",
)

# Integrity handlers are registered alongside existing editor handlers.
remote_cpp = replace_once(
    remote_cpp,
    '''        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {''',
    '''        net.on(proto::Opcode::LevelDigest, [this](int playerId, proto::Reader& reader) {\n            auto msg = proto::deserializeLevelDigest(reader);\n            if (reader.hasError()) return;\n            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;\n\n            auto [localCount, localHash] = computeLevelDigest();\n            if (localCount == msg.objectCount && localHash == msg.hash) {\n                log::debug(\n                    "RemoteActionHandler: LEVEL HASH match player={} objects={} hash={}",\n                    playerId, localCount, localHash\n                );\n                return;\n            }\n\n            log::warn(\n                "RemoteActionHandler: LEVEL HASH mismatch player={} local={}/{} remote={}/{}",\n                playerId, localCount, localHash, msg.objectCount, msg.hash\n            );\n            sendLevelManifestTo(playerId);\n        });\n\n        net.on(proto::Opcode::LevelManifest, [this](int playerId, proto::Reader& reader) {\n            auto msg = proto::deserializeLevelManifest(reader);\n            if (reader.hasError() || msg.totalChunks == 0 || msg.chunkIndex >= msg.totalChunks) return;\n            if (SessionManager::get().getRole() != SessionManager::Role::Client || playerId != 0) return;\n\n            if (!m_repairManifest.active || m_repairManifest.scanId != msg.scanId) {\n                m_repairManifest = {};\n                m_repairManifest.active = true;\n                m_repairManifest.hostPlayerId = playerId;\n                m_repairManifest.scanId = msg.scanId;\n                m_repairManifest.totalChunks = msg.totalChunks;\n                m_repairManifest.received.assign(msg.totalChunks, false);\n            }\n            if (m_repairManifest.totalChunks != msg.totalChunks) return;\n            if (!m_repairManifest.received[msg.chunkIndex]) {\n                m_repairManifest.received[msg.chunkIndex] = true;\n                for (auto const& entry : msg.entries) {\n                    m_repairManifest.entries.push_back({entry.uuid, entry.hash});\n                }\n            }\n\n            bool complete = std::all_of(\n                m_repairManifest.received.begin(),\n                m_repairManifest.received.end(),\n                [](bool v) { return v; }\n            );\n            if (!complete) return;\n\n            auto localEntries = buildLevelManifest();\n            std::unordered_map<std::string, std::string> localMap;\n            std::unordered_map<std::string, std::string> hostMap;\n            for (auto const& entry : localEntries) localMap[entry.uuid] = entry.hash;\n            for (auto const& entry : m_repairManifest.entries) hostMap[entry.uuid] = entry.hash;\n\n            std::vector<std::string> missing;\n            std::vector<std::string> changed;\n            std::vector<std::string> extra;\n\n            for (auto const& [uuid, hostHash] : hostMap) {\n                auto it = localMap.find(uuid);\n                if (it == localMap.end()) missing.push_back(uuid);\n                else if (it->second != hostHash) changed.push_back(uuid);\n            }\n            for (auto const& [uuid, _] : localMap) {\n                if (!hostMap.contains(uuid)) extra.push_back(uuid);\n            }\n\n            size_t diffCount = missing.size() + changed.size() + extra.size();\n            size_t relativeLimit = std::max<size_t>(64, hostMap.size() / 5);\n            if (diffCount > 256 || diffCount > relativeLimit) {\n                log::warn(\n                    "RemoteActionHandler: integrity diff too large ({} objects); requesting full SyncLevel",\n                    diffCount\n                );\n                auto request = proto::serializeFullResyncRequest();\n                P2PManager::get().sendTo(0, request, ChannelType::Reliable);\n                m_repairManifest = {};\n                return;\n            }\n\n            if (!extra.empty()) {\n                handleRemoteDeleteObjects(playerId, extra);\n            }\n\n            constexpr size_t kRepairRequestBatch = 80;\n            size_t missingOffset = 0;\n            size_t changedOffset = 0;\n            while (missingOffset < missing.size() || changedOffset < changed.size()) {\n                std::vector<std::string> missingBatch;\n                std::vector<std::string> changedBatch;\n                for (size_t i = 0; i < kRepairRequestBatch && missingOffset < missing.size(); ++i) {\n                    missingBatch.push_back(missing[missingOffset++]);\n                }\n                for (size_t i = 0; i < kRepairRequestBatch && changedOffset < changed.size(); ++i) {\n                    changedBatch.push_back(changed[changedOffset++]);\n                }\n                auto request = proto::serializeLevelRepairRequest(\n                    msg.scanId, missingBatch, changedBatch\n                );\n                P2PManager::get().sendTo(0, request, ChannelType::Reliable);\n            }\n\n            log::info(\n                "RemoteActionHandler: targeted repair requested missing={} changed={} deleted-extra={}",\n                missing.size(), changed.size(), extra.size()\n            );\n            m_repairManifest = {};\n        });\n\n        net.on(proto::Opcode::LevelRepairRequest, [this](int playerId, proto::Reader& reader) {\n            auto msg = proto::deserializeLevelRepairRequest(reader);\n            if (reader.hasError()) return;\n            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;\n\n            auto missingData = getObjectDataForUuids(msg.missing);\n            if (!missingData.empty()) {\n                auto packet = proto::serializePlaceObjects(missingData);\n                P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);\n            }\n\n            if (!msg.changed.empty()) {\n                auto deletePacket = proto::serializeDeleteObjects(msg.changed);\n                P2PManager::get().sendTo(playerId, deletePacket, ChannelType::Reliable);\n                auto changedData = getObjectDataForUuids(msg.changed);\n                if (!changedData.empty()) {\n                    auto placePacket = proto::serializePlaceObjects(changedData);\n                    P2PManager::get().sendTo(playerId, placePacket, ChannelType::Reliable);\n                }\n            }\n\n            log::info(\n                "RemoteActionHandler: repair response to player {} missing={} changed={}",\n                playerId, msg.missing.size(), msg.changed.size()\n            );\n        });\n\n        net.on(proto::Opcode::FullResyncRequest, [this](int playerId, proto::Reader& reader) {\n            (void)proto::deserializeFullResyncRequest(reader);\n            if (reader.hasError()) return;\n            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;\n            log::warn("RemoteActionHandler: full SyncLevel requested by player {}", playerId);\n            sendFullLevelSyncTo(playerId);\n        });\n\n        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {''',
    "integrity network handlers",
)

# Integrity implementation before clearHandlers().
remote_cpp = replace_once(
    remote_cpp,
    '''    void RemoteActionHandler::clearHandlers() {''',
    '''    std::vector<RemoteActionHandler::IntegrityEntry> RemoteActionHandler::buildLevelManifest() const {\n        std::vector<IntegrityEntry> entries;\n        auto* editor = getEditorLayer();\n        if (!editor || !editor->m_objects) return entries;\n\n        entries.reserve(editor->m_objects->count());\n        for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {\n            if (!obj) continue;\n            auto uuid = getUUIDForObject(obj);\n            if (uuid.empty()) continue;\n            std::string save = obj->getSaveString(editor);\n            entries.push_back({uuid, stableIntegrityHash(save)});\n        }\n        std::sort(entries.begin(), entries.end(), [](auto const& a, auto const& b) {\n            return a.uuid < b.uuid;\n        });\n        return entries;\n    }\n\n    std::pair<uint32_t, std::string> RemoteActionHandler::computeLevelDigest() const {\n        auto entries = buildLevelManifest();\n        std::string material;\n        material.reserve(entries.size() * 48);\n        for (auto const& entry : entries) {\n            material += entry.uuid;\n            material.push_back('=');\n            material += entry.hash;\n            material.push_back(';');\n        }\n        return {static_cast<uint32_t>(entries.size()), stableIntegrityHash(material)};\n    }\n\n    std::vector<ActionSerializer::ObjectData> RemoteActionHandler::getObjectDataForUuids(\n        std::vector<std::string> const& uuids) const\n    {\n        std::vector<ActionSerializer::ObjectData> result;\n        auto* editor = getEditorLayer();\n        if (!editor || !editor->m_objects || uuids.empty()) return result;\n\n        std::unordered_set<std::string> wanted(uuids.begin(), uuids.end());\n        result.reserve(wanted.size());\n        for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {\n            if (!obj) continue;\n            auto uuid = getUUIDForObject(obj);\n            if (uuid.empty() || !wanted.contains(uuid)) continue;\n            result.push_back(ActionSerializer::extractObjectData(obj, uuid));\n        }\n        return result;\n    }\n\n    void RemoteActionHandler::sendLevelDigestTo(int playerId) {\n        auto [count, hash] = computeLevelDigest();\n        auto packet = proto::serializeLevelDigest(count, hash);\n        P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);\n        log::debug(\n            "RemoteActionHandler: sent LEVEL HASH player={} objects={} hash={}",\n            playerId, count, hash\n        );\n    }\n\n    void RemoteActionHandler::sendLevelManifestTo(int playerId) {\n        auto entries = buildLevelManifest();\n        static uint32_t s_scanId = 1;\n        uint32_t scanId = s_scanId++;\n        constexpr size_t kEntriesPerChunk = 100;\n        uint32_t totalChunks = static_cast<uint32_t>(\n            std::max<size_t>(1, (entries.size() + kEntriesPerChunk - 1) / kEntriesPerChunk)\n        );\n\n        for (uint32_t chunk = 0; chunk < totalChunks; ++chunk) {\n            size_t begin = static_cast<size_t>(chunk) * kEntriesPerChunk;\n            size_t end = std::min(entries.size(), begin + kEntriesPerChunk);\n            std::vector<proto::LevelManifestEntry> wireEntries;\n            wireEntries.reserve(end - begin);\n            for (size_t i = begin; i < end; ++i) {\n                wireEntries.push_back({entries[i].uuid, entries[i].hash});\n            }\n            auto packet = proto::serializeLevelManifest(scanId, chunk, totalChunks, wireEntries);\n            P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);\n        }\n\n        log::info(\n            "RemoteActionHandler: sent integrity manifest scan={} player={} objects={} chunks={}",\n            scanId, playerId, entries.size(), totalChunks\n        );\n    }\n\n    void RemoteActionHandler::clearHandlers() {''',
    "integrity helper implementation",
)

remote_cpp = replace_once(
    remote_cpp,
    '''        m_chunkedSync.uuidChunks.clear();\n        P2PManager::get().clearHandlers();''',
    '''        m_chunkedSync.uuidChunks.clear();\n        m_repairManifest = {};\n        P2PManager::get().clearHandlers();''',
    "clear repair manifest state",
)

remote_cpp_path.write_text(remote_cpp, encoding="utf-8")


# =============================================================================
# EditorHooks: periodic digest, reconnect-aware join, full SyncLevel fallback.
# =============================================================================
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

# Export the existing chunked sync routine without duplicating serialization.
hooks = replace_once(
    hooks,
    '''}\n\nclass $modify(MPLevelEditorLayer, LevelEditorLayer) {''',
    '''}\n\nnamespace mpedit {\n    void sendFullLevelSyncTo(int targetPlayerId) {\n        if (auto* editor = LevelEditorLayer::get()) {\n            sendChunkedSync(editor, targetPlayerId);\n        }\n    }\n}\n\nclass $modify(MPLevelEditorLayer, LevelEditorLayer) {''',
    "export full level sync helper",
)

hooks = replace_once(
    hooks,
    '''        float m_externalCompatScanTimer = 0.f;\n        std::unordered_set<std::string> m_externalCompatLiveUuids;''',
    '''        float m_externalCompatScanTimer = 0.f;\n        std::unordered_set<std::string> m_externalCompatLiveUuids;\n        float m_integrityCheckTimer = 0.f;\n        bool m_forceIntegrityCheck = false;''',
    "integrity timer fields",
)

hooks = replace_once(
    hooks,
    '''        SessionManager::get().onSessionStarted([this]() {\n            auto& session = SessionManager::get();''',
    '''        SessionManager::get().onSessionStarted([this]() {\n            auto& session = SessionManager::get();\n            m_fields->m_forceIntegrityCheck = true;''',
    "force digest after reconnect/session start",
)

hooks = replace_once(
    hooks,
    '''            if (session.getRole() == SessionManager::Role::Host && info.id != session.getLocalPlayerId()) {\n                sendChunkedSync(this, info.id);\n                log::info("EditorHooks: Sent chunked sync_level to new player {}", info.id);\n            }''',
    '''            if (session.getRole() == SessionManager::Role::Host && info.id != session.getLocalPlayerId()) {\n                if (P2PManager::get().isPeerReconnect(info.id)) {\n                    log::info(\n                        "EditorHooks: reconnecting player {}; waiting for digest before repair/resync",\n                        info.id\n                    );\n                } else {\n                    sendChunkedSync(this, info.id);\n                    log::info("EditorHooks: Sent chunked sync_level to new player {}", info.id);\n                }\n            }''',
    "reconnect-aware initial sync",
)

# Periodic digest after normal network dispatch; client compares against host.
hooks = replace_once(
    hooks,
    '''        // Compatibility fallback for third-party editor mods (Layout Generator,''',
    '''        // Periodic integrity verification. The host is authoritative; clients\n        // send a stable UUID/saveString digest and receive targeted repair only\n        // when the state differs. Reconnect forces an immediate digest.\n        m_fields->m_integrityCheckTimer += dt;\n        if (\n            session.getRole() == SessionManager::Role::Client &&\n            handler.isInitialSyncCompleted() &&\n            !handler.isProcessingRemote() &&\n            (m_fields->m_forceIntegrityCheck || m_fields->m_integrityCheckTimer >= 3.0f)\n        ) {\n            m_fields->m_integrityCheckTimer = 0.f;\n            m_fields->m_forceIntegrityCheck = false;\n            handler.sendLevelDigestTo(0);\n        }\n\n        // Compatibility fallback for third-party editor mods (Layout Generator,''',
    "periodic level integrity digest",
)

hooks_path.write_text(hooks, encoding="utf-8")

print("Applied ACK/dedup, integrity repair, full-resync fallback and reconnect reliability layer")
