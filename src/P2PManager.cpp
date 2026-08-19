#include "P2PManager.hpp"
#include "BinaryProtocol.hpp"
#include "net/NetworkConfig.hpp"
#include "net/ProtocolCapabilities.hpp"
#include "sync/SyncMetrics.hpp"

#include <rtc/rtc.hpp>
#include <Geode/Geode.hpp>
#include <Geode/utils/web.hpp>
#include <thread>
#include <chrono>

using namespace geode::prelude;

namespace mpedit {

    namespace {
        uint64_t reliabilityNowMs() {
            return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now().time_since_epoch()
            ).count());
        }

        bool isGlobalEditOpcode(uint8_t raw) {
            auto opcode = static_cast<proto::Opcode>(raw);
            return
                opcode == proto::Opcode::PlaceObjects ||
                opcode == proto::Opcode::DeleteObjects ||
                opcode == proto::Opcode::MoveObjects ||
                opcode == proto::Opcode::TransformObjects ||
                opcode == proto::Opcode::ReconcileObjects ||
                opcode == proto::Opcode::UpdateObjects ||
                opcode == proto::Opcode::UpdateSettings ||
                opcode == proto::Opcode::BulkPasteEnd;
        }

        bool isOrderedReliableOpcode(uint8_t raw) {
            auto opcode = static_cast<proto::Opcode>(raw);
            return
                opcode == proto::Opcode::PlaceObjects ||
                opcode == proto::Opcode::DeleteObjects ||
                opcode == proto::Opcode::MoveObjects ||
                opcode == proto::Opcode::MoveBatch ||
                opcode == proto::Opcode::TransformObjects ||
                opcode == proto::Opcode::ReconcileObjects ||
                opcode == proto::Opcode::UpdateObjects ||
                opcode == proto::Opcode::LockObjects ||
                opcode == proto::Opcode::UpdateSettings ||
                opcode == proto::Opcode::SyncLevelStart ||
                opcode == proto::Opcode::SyncLevelChunk ||
                opcode == proto::Opcode::SyncLevelEnd ||
                opcode == proto::Opcode::LevelDigest ||
                opcode == proto::Opcode::LevelManifest ||
                opcode == proto::Opcode::LevelRepairRequest ||
                opcode == proto::Opcode::FullResyncRequest ||
                opcode == proto::Opcode::BulkPasteStart ||
                opcode == proto::Opcode::BulkPasteChunk ||
                opcode == proto::Opcode::BulkPasteEnd ||
                opcode == proto::Opcode::GlobalRevision ||
                opcode == proto::Opcode::SharedDigest ||
                opcode == proto::Opcode::GlobalSnapshotRequest ||
                opcode == proto::Opcode::KickPlayer ||
                opcode == proto::Opcode::MusicChanged ||
                opcode == proto::Opcode::RoomSettingsChanged;
        }

        std::string bytesToHex(std::vector<uint8_t> const& data) {
            static constexpr char kHex[] = "0123456789abcdef";
            std::string out;
            out.resize(data.size() * 2);
            for (size_t i = 0; i < data.size(); ++i) {
                out[i * 2] = kHex[(data[i] >> 4) & 0x0f];
                out[i * 2 + 1] = kHex[data[i] & 0x0f];
            }
            return out;
        }

        int hexNibble(char c) {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        }

        bool hexToBytes(std::string const& text, std::vector<uint8_t>& out) {
            if (text.empty() || (text.size() % 2) != 0) return false;
            out.clear();
            out.reserve(text.size() / 2);
            for (size_t i = 0; i < text.size(); i += 2) {
                int hi = hexNibble(text[i]);
                int lo = hexNibble(text[i + 1]);
                if (hi < 0 || lo < 0) return false;
                out.push_back(static_cast<uint8_t>((hi << 4) | lo));
            }
            return true;
        }
    }

    P2PManager& P2PManager::get() {
        static P2PManager instance;
        return instance;
    }

    P2PManager::P2PManager() {
        rtc::InitLogger(rtc::LogLevel::Warning);
    }

    P2PManager::~P2PManager() {
        leaveSession();
    }



    rtc::Configuration P2PManager::makeRtcConfig(bool forceRelay) {
        rtc::Configuration config;
        auto network = net::NetworkConfig::load();

        // Keep the proven upstream 0.5.0 direct/STUN path unchanged whenever
        // WebRTC is enabled. Transport selection only layers policy on top.
        if (!network.httpRelayImmediate()) {
            config.iceServers.push_back({"stun:stun.l.google.com:19302"});
            config.iceServers.push_back({"stun:stun.cloudflare.com:3478"});
        }

        bool customTurnAvailable = network.hasTurn();
        bool allowConfiguredTurn =
            network.connectionMode == net::ConnectionMode::Auto ||
            network.connectionMode == net::ConnectionMode::Turn ||
            network.forceTurnRelay || forceRelay;

        if (customTurnAvailable && allowConfiguredTurn) {
            rtc::IceServer customTurn(
                network.turnHost, 3478, network.turnUsername, network.turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(customTurn);
        }

        bool relayOnly = network.forceTurnTransport() || forceRelay;
        if (relayOnly && customTurnAvailable) {
            config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            if (forceRelay && !network.forceTurnTransport()) {
                log::warn("P2PManager: stable WebRTC path failed; retrying through configured TURN/UDP");
            } else {
                log::warn("P2PManager: TURN relay transport selected");
            }
        } else if (network.httpRelayImmediate()) {
            log::info("P2PManager: HTTP Relay transport selected; ICE will not be used");
        } else if (network.directWebRtcOnly()) {
            log::info("P2PManager: stable 0.5.0 WebRTC direct/STUN transport selected");
        } else if (customTurnAvailable) {
            log::info("P2PManager: stable 0.5.0 WebRTC direct/STUN path with TURN/UDP fallback available");
        } else {
            log::info("P2PManager: stable 0.5.0 WebRTC direct/STUN path; HTTP Relay fallback available");
        }

        return config;
    }

    std::string P2PManager::getSignalingUrl() {
        return net::NetworkConfig::load().signalingUrl;
    }


    P2PManager::State P2PManager::getState() const {
        return m_state.load();
    }

    P2PManager::Role P2PManager::getRole() const {
        std::lock_guard lock(m_stateMutex);
        return m_role;
    }

    bool P2PManager::isConnected() const {
        return m_state.load() == State::Connected;
    }

    std::string P2PManager::getRoomCode() const {
        std::lock_guard lock(m_stateMutex);
        return m_roomCode;
    }

    int P2PManager::getLocalPlayerId() const {
        return m_localPlayerId;
    }

    std::string P2PManager::getError() const {
        std::lock_guard lock(m_stateMutex);
        return m_error;
    }

    bool P2PManager::supportsCapability(int playerId, net::Capability capability) {
        std::lock_guard lock(m_peersMutex);
        auto it = m_peers.find(playerId);
        return it != m_peers.end() && net::hasCapability(it->second.capabilities, capability);
    }

    std::size_t P2PManager::getTotalReliableQueueDepth() {
        std::lock_guard lock(m_peersMutex);
        std::size_t depth = 0;
        for (auto const& [id, peer] : m_peers) {
            (void)id;
            depth += peer.bulkReliableQueue.size();
        }
        return depth;
    }

    bool P2PManager::isPeerReconnect(int playerId) {
        std::lock_guard lock(m_peersMutex);
        auto it = m_peers.find(playerId);
        return it != m_peers.end() && it->second.reconnecting;
    }

    P2PManager::RoomSettings P2PManager::getRoomSettings() const {
        std::lock_guard lock(m_roomSettingsMutex);
        return m_roomSettings;
    }

    void P2PManager::setRoomSettings(RoomSettings const& settings) {
        if (m_role != Role::Host) return;
        RoomSettings safe = settings;
        safe.maxPlayers = std::clamp<uint32_t>(safe.maxPlayers, 2, 16);
        {
            std::lock_guard lock(m_roomSettingsMutex);
            m_roomSettings = safe;
        }
        auto packet = proto::serializeRoomSettingsChanged(
            safe.maxPlayers, safe.allowBuild, safe.allowDelete, safe.allowWorkshop,
            safe.allowLevelSettings, safe.autoRepair, safe.locked
        );
        broadcast(packet, ChannelType::Reliable);
        log::info(
            "P2PManager: ROOM SETTINGS max={} build={} delete={} workshop={} settings={} repair={} locked={}",
            safe.maxPlayers, safe.allowBuild, safe.allowDelete, safe.allowWorkshop,
            safe.allowLevelSettings, safe.autoRepair, safe.locked
        );
    }

    void P2PManager::kickPlayer(int playerId) {
        if (m_role != Role::Host || playerId <= 0) return;

        std::string name;
        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) return;
            name = it->second.playerName;
            if (!name.empty()) m_kickedNames.insert(name);
        }

        auto packet = proto::serializeKickPlayer(playerId, "Kicked by host");
        sendTo(playerId, packet, ChannelType::Reliable);
        log::warn("P2PManager: host kicked player {} ({})", playerId, name);

        std::thread([this, playerId]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
            onPeerDisconnected(playerId, false);
        }).detach();
    }



    void P2PManager::onSessionStarted(SessionStartedCb cb) {
        m_onSessionStarted.push_back(std::move(cb));
    }
    void P2PManager::onPeerConnected(PeerConnectedCb cb) {
        m_onPeerConnected.push_back(std::move(cb));
    }
    void P2PManager::onPeerDisconnected(PeerDisconnectedCb cb) {
        m_onPeerDisconnected.push_back(std::move(cb));
    }
    void P2PManager::onError(ErrorCb cb) {
        m_onError.push_back(std::move(cb));
    }
    void P2PManager::clearCallbacks() {
        m_onSessionStarted.clear();
        m_onPeerConnected.clear();
        m_onPeerDisconnected.clear();
        m_onError.clear();
    }



    void P2PManager::on(proto::Opcode opcode, MessageCallback callback) {
        m_handlers[static_cast<uint8_t>(opcode)].push_back(std::move(callback));
    }

    void P2PManager::clearHandlers() {
        m_handlers.clear();
    }



    void P2PManager::dispatchMessages() {
        flushBulkReliableQueues();

        if (m_dispatching) return;
        m_dispatching = true;

        std::queue<QueuedMessage> messages;
        {
            std::lock_guard lock(m_incomingMutex);
            std::swap(messages, m_incoming);
        }

        while (!messages.empty()) {
            auto& msg = messages.front();

            if (!msg.data.empty()) {
                uint8_t opcodeRaw = msg.data[0];

                auto it = m_handlers.find(opcodeRaw);
                if (it != m_handlers.end()) {
                    auto handlersCopy = it->second;
                    for (auto const& handler : handlersCopy) {
                        proto::Reader handlerReader(msg.data.data() + 1, msg.data.size() - 1);
                        try {
                            handler(msg.fromPlayerId, handlerReader);
                            if (handlerReader.hasError()) {
                                log::warn(
                                    "P2PManager: malformed payload rejected (opcode={}, from={})",
                                    static_cast<int>(opcodeRaw),
                                    msg.fromPlayerId
                                );
                            }
                        } catch (std::exception const& e) {
                            log::error(
                                "P2PManager: message handler contained exception (opcode={}, from={}): {}",
                                static_cast<int>(opcodeRaw),
                                msg.fromPlayerId,
                                e.what()
                            );
                        } catch (...) {
                            log::error(
                                "P2PManager: message handler contained unknown exception (opcode={}, from={})",
                                static_cast<int>(opcodeRaw),
                                msg.fromPlayerId
                            );
                        }
                        if (m_handlers.empty()) break;
                    }
                }
            }

            if (m_handlers.empty()) break;
            messages.pop();
        }

        m_dispatching = false;
    }



    void P2PManager::send(std::vector<uint8_t> const& data, ChannelType channel) {
        if (m_role == Role::Host) {
            broadcast(data, channel);
            if (!data.empty() && isGlobalEditOpcode(data[0])) {
                uint32_t revision = m_globalRevision.fetch_add(1) + 1;
                m_lastGlobalAuthor.store(0);
                auto rev = proto::serializeGlobalRevision(revision, 0);
                broadcast(rev, ChannelType::Reliable);
                log::debug("P2PManager: GLOBAL REV {} author=host opcode={}", revision, static_cast<int>(data[0]));
            }
        } else if (m_role == Role::Client) {
            sendTo(0, data, channel);
        }
    }

    void P2PManager::send(std::vector<uint8_t>&& data, ChannelType channel) {
        send(static_cast<std::vector<uint8_t> const&>(data), channel);
    }

    void P2PManager::sendTo(int playerId, std::vector<uint8_t> const& data, ChannelType channel) {
        sync::SyncMetrics::get().recordOutboundBytes(data.size());
        std::lock_guard lock(m_peersMutex);
        auto it = m_peers.find(playerId);
        if (it == m_peers.end()) return;

        auto& peer = it->second;
        if (!peer.ready) {
            constexpr size_t kMaxPendingMessagesPerPeer = 512;
            if (peer.pendingMessages.size() >= kMaxPendingMessagesPerPeer) {
                log::warn(
                    "P2PManager: dropping queued message for player {} because pending queue reached {} entries",
                    playerId,
                    kMaxPendingMessagesPerPeer
                );
                return;
            }
            peer.pendingMessages.push_back({data, channel});
            return;
        }

        constexpr size_t kSafeMessageBytes = 24 * 1024;

        auto queueTrackedReliable = [&](std::vector<uint8_t> const& payload) -> bool {
            constexpr size_t kMaxTrackedReliable = 8192;
            if (peer.pendingReliableAcks.size() >= kMaxTrackedReliable) {
                log::error(
                    "P2PManager: tracked reliable window full for player {}; opcode {} rejected",
                    playerId,
                    payload.empty() ? -1 : static_cast<int>(payload[0])
                );
                return false;
            }

            uint32_t sequence = peer.nextReliableSequence++;
            if (sequence == 0) sequence = peer.nextReliableSequence++;
            auto envelope = proto::serializeReliableEnvelope(sequence, payload);
            peer.pendingReliableAcks[sequence] = PeerInfo::PendingAck {
                envelope, 0, 0, true
            };
            peer.bulkReliableQueue.push_back(std::move(envelope));
            log::debug(
                "P2PManager: TX queued #{} opcode={} player={} transport={}",
                sequence,
                payload.empty() ? -1 : static_cast<int>(payload[0]),
                playerId,
                peer.httpRelay ? "http-relay" : "webrtc"
            );
            return true;
        };

        // Ordered editor traffic always enters the same sequence/ACK pipeline,
        // regardless of whether the physical transport is SCTP or HTTP Relay.
        // This is critical for initial level chunks, start positions and bulk edits.
        if (
            channel == ChannelType::Reliable &&
            !data.empty() &&
            data.size() <= kSafeMessageBytes &&
            isOrderedReliableOpcode(data[0])
        ) {
            constexpr size_t kMaxOrderedReliableQueue = 8192;
            if (peer.bulkReliableQueue.size() < kMaxOrderedReliableQueue) {
                queueTrackedReliable(data);
            } else {
                log::error(
                    "P2PManager: ordered reliable queue full for player {}; opcode {} could not be retained",
                    playerId,
                    static_cast<int>(data[0])
                );
            }
            return;
        }

        if (
            channel == ChannelType::Reliable &&
            !data.empty() &&
            data.size() > kSafeMessageBytes &&
            data[0] == static_cast<uint8_t>(proto::Opcode::PlaceObjects)
        ) {
            proto::Reader reader(data.data() + 1, data.size() - 1);
            auto msg = proto::deserializePlaceObjects(reader);
            if (reader.hasError()) {
                log::warn("P2PManager: refusing to split malformed PlaceObjects payload");
                return;
            }

            std::vector<ActionSerializer::ObjectData> batch;
            batch.reserve(64);
            size_t sentObjects = 0;

            auto flushBatch = [&]() -> bool {
                if (batch.empty()) return true;
                auto payload = proto::serializePlaceObjects(batch);
                if (payload.size() > kSafeMessageBytes) {
                    log::warn(
                        "P2PManager: dropping oversized PlaceObjects sub-batch ({} objects, {} bytes)",
                        batch.size(), payload.size()
                    );
                    batch.clear();
                    return false;
                }
                queueTrackedReliable(payload);
                sentObjects += batch.size();
                batch.clear();
                return true;
            };

            for (auto const& object : msg.objects) {
                batch.push_back(object);
                auto probe = proto::serializePlaceObjects(batch);
                if (probe.size() > kSafeMessageBytes) {
                    auto last = std::move(batch.back());
                    batch.pop_back();
                    flushBatch();
                    batch.push_back(std::move(last));
                    auto single = proto::serializePlaceObjects(batch);
                    if (single.size() > kSafeMessageBytes) {
                        log::warn(
                            "P2PManager: one object is too large to synchronize safely ({} bytes); skipping it",
                            single.size()
                        );
                        batch.clear();
                    }
                }
            }
            flushBatch();

            log::info(
                "P2PManager: queued oversized PlaceObjects payload: {} objects in {} paced reliable messages",
                sentObjects,
                peer.bulkReliableQueue.size()
            );
            return;
        }

        if (peer.httpRelay) {
            if (data.size() > 48 * 1024) {
                log::warn(
                    "P2PManager: dropping oversized HTTP relay message (opcode={}, {} bytes)",
                    data.empty() ? -1 : static_cast<int>(data[0]), data.size()
                );
                return;
            }
            sendHttpRelayPacket(playerId, data, channel);
            return;
        }

        auto& dc = (channel == ChannelType::Reliable) ? peer.reliable : peer.unreliable;
        if (!dc || !dc->isOpen()) return;

        auto sendRaw = [&](std::vector<uint8_t> const& payload) -> bool {
            try {
                dc->send(reinterpret_cast<const std::byte*>(payload.data()), payload.size());
                return true;
            } catch (std::exception const& e) {
                log::error(
                    "P2PManager: data-channel send failed for player {} ({} bytes): {}",
                    playerId, payload.size(), e.what()
                );
                return false;
            } catch (...) {
                log::error(
                    "P2PManager: data-channel send failed for player {} ({} bytes): unknown exception",
                    playerId, payload.size()
                );
                return false;
            }
        };

        if (data.size() <= kSafeMessageBytes) {
            // Handshake/session-control traffic and unreliable cursor state stay
            // immediate. Ordered editor traffic was queued above.
            sendRaw(data);
            return;
        }

        log::warn(
            "P2PManager: dropping oversized unsupported message (opcode={}, {} bytes)",
            data.empty() ? -1 : static_cast<int>(data[0]), data.size()
        );
    }

    void P2PManager::broadcast(std::vector<uint8_t> const& data, ChannelType channel, int excludePlayerId) {
        std::vector<int> peerIds;
        {
            std::lock_guard lock(m_peersMutex);
            for (auto& [id, peer] : m_peers) {
                if (id != excludePlayerId && peer.ready) {
                    peerIds.push_back(id);
                }
            }
        }

        for (int id : peerIds) {
            sendTo(id, data, channel);
        }
    }



    void P2PManager::flushBulkReliableQueues() {
        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 8;
        constexpr uint64_t kAckTimeoutMs = 900;
        auto now = reliabilityNowMs();

        std::lock_guard lock(m_peersMutex);
        for (auto& [playerId, peer] : m_peers) {
            if (!peer.ready) continue;

            bool webRtcReliableOpen = peer.reliable && peer.reliable->isOpen();
            if (!peer.httpRelay && !webRtcReliableOpen) continue;

            for (auto& [sequence, pending] : peer.pendingReliableAcks) {
                if (!pending.queued && pending.lastSentMs > 0 && now - pending.lastSentMs >= kAckTimeoutMs) {
                    peer.bulkReliableQueue.push_back(pending.envelope);
                    pending.queued = true;
                    log::warn(
                        "P2PManager: RETRY #{} player={} attempt={} transport={}",
                        sequence, playerId, pending.attempts + 1,
                        peer.httpRelay ? "http-relay" : "webrtc"
                    );
                }
            }

            if (peer.httpRelay) {
                // Preserve HTTP application ordering: never issue the next
                // reliable editor POST until the previous POST was accepted by
                // the relay server. ACK then provides end-to-end delivery.
                if (peer.httpRelayPostInFlight || peer.bulkReliableQueue.empty()) continue;

                auto payload = peer.bulkReliableQueue.front();
                peer.bulkReliableQueue.erase(peer.bulkReliableQueue.begin());

                uint32_t trackedSequence = 0;
                if (!payload.empty() && payload[0] == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {
                    proto::Reader sentReader(payload.data() + 1, payload.size() - 1);
                    auto sentEnvelope = proto::deserializeReliableEnvelope(sentReader);
                    if (!sentReader.hasError()) {
                        trackedSequence = sentEnvelope.sequence;
                        auto pendingIt = peer.pendingReliableAcks.find(trackedSequence);
                        if (pendingIt != peer.pendingReliableAcks.end()) {
                            pendingIt->second.lastSentMs = now;
                            pendingIt->second.attempts += 1;
                            pendingIt->second.queued = false;
                        }
                    }
                }

                peer.httpRelayPostInFlight = true;
                sendHttpRelayPacket(playerId, payload, ChannelType::Reliable, trackedSequence);
                continue;
            }

            size_t sentThisTick = 0;
            while (!peer.bulkReliableQueue.empty() && sentThisTick < kMaxBulkPacketsPerPeerPerTick) {
                auto const& payload = peer.bulkReliableQueue.front();
                try {
                    peer.reliable->send(
                        reinterpret_cast<const std::byte*>(payload.data()),
                        payload.size()
                    );

                    if (!payload.empty() && payload[0] == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {
                        proto::Reader sentReader(payload.data() + 1, payload.size() - 1);
                        auto sentEnvelope = proto::deserializeReliableEnvelope(sentReader);
                        if (!sentReader.hasError()) {
                            auto pendingIt = peer.pendingReliableAcks.find(sentEnvelope.sequence);
                            if (pendingIt != peer.pendingReliableAcks.end()) {
                                pendingIt->second.lastSentMs = reliabilityNowMs();
                                pendingIt->second.attempts += 1;
                                pendingIt->second.queued = false;
                            }
                        }
                    }

                    peer.bulkReliableQueue.erase(peer.bulkReliableQueue.begin());
                    ++sentThisTick;
                } catch (std::exception const& e) {
                    log::warn(
                        "P2PManager: reliable FIFO send deferred for player {} ({} bytes): {}",
                        playerId, payload.size(), e.what()
                    );
                    break;
                } catch (...) {
                    log::warn(
                        "P2PManager: reliable FIFO send deferred for player {} ({} bytes): unknown exception",
                        playerId, payload.size()
                    );
                    break;
                }
            }
        }
    }

    void P2PManager::onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len) {
        constexpr size_t kMaxInboundMessageBytes = 256 * 1024;
        constexpr size_t kMaxIncomingQueue = 1024;
        constexpr size_t kMaxPreHandshakeMessages = 64;

        if (len == 0) return;
        if (!data || len > kMaxInboundMessageBytes) {
            log::warn(
                "P2PManager: rejected inbound message from player {} ({} bytes)",
                fromPlayerId,
                len
            );
            return;
        }

        uint8_t opcode = data[0];
        if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) {
            proto::Reader helloReader(data + 1, len - 1);
            auto hello = proto::deserializeProtocolHello(helloReader);
            auto remoteCapabilities = net::normalizeCapabilities(hello.protocolVersion, hello.capabilities);
            if (helloReader.hasError() || !net::isCompatible(hello.protocolVersion, remoteCapabilities)) {
                log::warn(
                    "P2PManager: incompatible peer {} (protocol={}, capabilities={}, localProtocol={})",
                    fromPlayerId,
                    hello.protocolVersion,
                    remoteCapabilities,
                    net::kCurrentProtocol
                );

                auto errorMsg = proto::serializeError(
                    "Incompatible Multiplayer Edit capabilities"
                );
                sendTo(fromPlayerId, errorMsg, ChannelType::Reliable);

                if (m_role == Role::Client && fromPlayerId == 0) {
                    queueInMainThread([this]() {
                        for (auto& cb : m_onError) {
                            cb("Incompatible Multiplayer Edit protocol");
                        }
                    });
                }
                return;
            }

            std::vector<std::vector<uint8_t>> buffered;
            {
                std::lock_guard lock(m_peersMutex);
                auto it = m_peers.find(fromPlayerId);
                if (it != m_peers.end()) {
                    it->second.protocolVerified = true;
                    it->second.protocolVersion = hello.protocolVersion;
                    it->second.capabilities = remoteCapabilities;
                    if (m_role == Role::Client && fromPlayerId == 0) {
                        m_hostMigrationAvailable.store(
                            net::hasCapability(remoteCapabilities, net::Capability::HostMigration)
                        );
                    }
                    buffered = std::move(it->second.preHandshakeMessages);
                    it->second.preHandshakeMessages.clear();
                }
            }
            log::info(
                "P2PManager: protocol v{} verified for player {} (replaying {} buffered packets)",
                hello.protocolVersion,
                fromPlayerId,
                buffered.size()
            );

            // Data channels being open is not enough to expose the peer to the
            // editor. Only a mutually compatible protocol handshake may release
            // pending editor traffic and fire Session/Peer callbacks.
            finalizePeerHandshake(fromPlayerId);

            for (auto const& packet : buffered) {
                if (!packet.empty()) {
                    onPeerMessage(fromPlayerId, packet.data(), packet.size());
                }
            }
            return;
        }

        bool protocolVerified = false;
        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(fromPlayerId);
            if (it != m_peers.end()) {
                protocolVerified = it->second.protocolVerified;
                if (!protocolVerified) {
                    if (it->second.preHandshakeMessages.size() < kMaxPreHandshakeMessages) {
                        it->second.preHandshakeMessages.emplace_back(data, data + len);
                        log::debug(
                            "P2PManager: buffered opcode {} from player {} until protocol handshake",
                            static_cast<int>(opcode),
                            fromPlayerId
                        );
                    } else {
                        log::warn(
                            "P2PManager: pre-handshake queue full for player {}; dropping opcode {}",
                            fromPlayerId,
                            static_cast<int>(opcode)
                        );
                    }
                }
            }
        }
        if (!protocolVerified) return;

        if (m_role == Role::Host && fromPlayerId > 0) {
            auto settings = getRoomSettings();
            auto op = static_cast<proto::Opcode>(opcode);
            bool denied = false;
            const char* deniedReason = nullptr;

            if (!settings.allowWorkshop && (
                op == proto::Opcode::BulkPasteStart ||
                op == proto::Opcode::BulkPasteChunk ||
                op == proto::Opcode::BulkPasteEnd
            )) {
                denied = true;
                deniedReason = "Object Workshop is disabled by host";
            } else if (!settings.allowDelete && op == proto::Opcode::DeleteObjects) {
                denied = true;
                deniedReason = "Guest deletion is disabled by host";
            } else if (!settings.allowLevelSettings && op == proto::Opcode::UpdateSettings) {
                denied = true;
                deniedReason = "Level settings are host-only";
            } else if (!settings.allowBuild && (
                op == proto::Opcode::PlaceObjects ||
                op == proto::Opcode::MoveObjects ||
                op == proto::Opcode::MoveBatch ||
                op == proto::Opcode::TransformObjects ||
                op == proto::Opcode::ReconcileObjects ||
                op == proto::Opcode::UpdateObjects
            )) {
                denied = true;
                deniedReason = "Guest building/editing is disabled by host";
            }

            if (denied) {
                log::warn("P2PManager: blocked guest {} opcode {}: {}", fromPlayerId, static_cast<int>(opcode), deniedReason);
                return;
            }
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::RoomSettingsChanged)) {
            if (m_role != Role::Client || fromPlayerId != 0) return;
            proto::Reader roomReader(data + 1, len - 1);
            auto msg = proto::deserializeRoomSettingsChanged(roomReader);
            if (roomReader.hasError()) return;
            RoomSettings settings;
            settings.maxPlayers = std::clamp<uint32_t>(msg.maxPlayers, 2, 16);
            settings.allowBuild = msg.allowBuild;
            settings.allowDelete = msg.allowDelete;
            settings.allowWorkshop = msg.allowWorkshop;
            settings.allowLevelSettings = msg.allowLevelSettings;
            settings.autoRepair = msg.autoRepair;
            settings.locked = msg.locked;
            {
                std::lock_guard lock(m_roomSettingsMutex);
                m_roomSettings = settings;
            }
            log::info("P2PManager: applied ROOM SETTINGS from host");
            return;
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::GlobalRevision)) {
            proto::Reader revisionReader(data + 1, len - 1);
            auto msg = proto::deserializeGlobalRevision(revisionReader);
            if (!revisionReader.hasError()) {
                uint32_t current = m_globalRevision.load();
                if (msg.revision >= current) {
                    m_globalRevision.store(msg.revision);
                    m_lastGlobalAuthor.store(msg.authorPlayerId);
                    log::debug("P2PManager: GLOBAL REV applied {} author={}", msg.revision, msg.authorPlayerId);
                }
            }
            return;
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::KickPlayer)) {
            proto::Reader kickReader(data + 1, len - 1);
            auto msg = proto::deserializeKickPlayer(kickReader);
            if (kickReader.hasError()) return;
            if (m_role == Role::Client && msg.targetPlayerId == m_localPlayerId) {
                m_state.store(State::Error);
                m_reconnectScheduled.store(false);
                stopSignalPolling();
                auto reason = msg.reason.empty() ? std::string("Kicked by host") : msg.reason;
                queueInMainThread([this, reason]() {
                    for (auto& cb : m_onError) cb(reason);
                });
            }
            return;
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::ReliableAck)) {
            proto::Reader ackReader(data + 1, len - 1);
            auto ack = proto::deserializeReliableAck(ackReader);
            if (ackReader.hasError()) return;

            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(fromPlayerId);
            if (it != m_peers.end()) {
                it->second.pendingReliableAcks.erase(ack.sequence);
                auto& queue = it->second.bulkReliableQueue;
                for (auto qit = queue.begin(); qit != queue.end(); ) {
                    if (!qit->empty() && (*qit)[0] == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {
                        proto::Reader qr(qit->data() + 1, qit->size() - 1);
                        auto qm = proto::deserializeReliableEnvelope(qr);
                        if (!qr.hasError() && qm.sequence == ack.sequence) {
                            qit = queue.erase(qit);
                            continue;
                        }
                    }
                    ++qit;
                }
                log::debug("P2PManager: ACK #{} from player {}", ack.sequence, fromPlayerId);
            }
            return;
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::ReliableEnvelope)) {
            proto::Reader envelopeReader(data + 1, len - 1);
            auto envelope = proto::deserializeReliableEnvelope(envelopeReader);
            if (envelopeReader.hasError() || envelope.payload.empty()) {
                log::warn("P2PManager: malformed reliable envelope from player {}", fromPlayerId);
                return;
            }

            auto ack = proto::serializeReliableAck(envelope.sequence);
            sendTo(fromPlayerId, ack, ChannelType::Reliable);

            bool duplicate = false;
            {
                std::lock_guard lock(m_peersMutex);
                auto it = m_peers.find(fromPlayerId);
                if (it != m_peers.end()) {
                    auto& seen = it->second.receivedReliableSequences;
                    duplicate = seen.contains(envelope.sequence);
                    if (!duplicate) {
                        seen.insert(envelope.sequence);
                        it->second.receivedReliableOrder.push_back(envelope.sequence);
                        constexpr size_t kMaxRememberedSequences = 4096;
                        while (it->second.receivedReliableOrder.size() > kMaxRememberedSequences) {
                            auto old = it->second.receivedReliableOrder.front();
                            it->second.receivedReliableOrder.pop_front();
                            seen.erase(old);
                        }
                    }
                }
            }

            if (duplicate) {
                log::debug("P2PManager: duplicate #{} from player {} ACKed and ignored", envelope.sequence, fromPlayerId);
                return;
            }

            log::debug(
                "P2PManager: RX #{} opcode={} player={}",
                envelope.sequence,
                static_cast<int>(envelope.payload[0]),
                fromPlayerId
            );
            onPeerMessage(fromPlayerId, envelope.payload.data(), envelope.payload.size());
            return;
        }

        {
            std::lock_guard lock(m_incomingMutex);
            if (m_incoming.size() >= kMaxIncomingQueue) {
                log::warn("P2PManager: incoming message queue full; dropping packet from player {}", fromPlayerId);
                return;
            }
            m_incoming.push(QueuedMessage{
                fromPlayerId,
                std::vector<uint8_t>(data, data + len)
            });
        }

        if (m_role == Role::Host) {
            uint8_t opcode = data[0];
            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;
            if (
                opcode == static_cast<uint8_t>(proto::Opcode::LevelDigest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::LevelManifest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::LevelRepairRequest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::FullResyncRequest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::SharedDigest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::GlobalSnapshotRequest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::GlobalRevision) ||
                opcode == static_cast<uint8_t>(proto::Opcode::KickPlayer)
            ) return;
            ChannelType ch = ChannelType::Reliable;
            if (opcode == static_cast<uint8_t>(proto::Opcode::CursorUpdate) ||
                opcode == static_cast<uint8_t>(proto::Opcode::MoveBatch)) {
                ch = ChannelType::Unreliable;
            }
            relayMessage(fromPlayerId, data, len, ch);

            if (isGlobalEditOpcode(opcode)) {
                uint32_t revision = m_globalRevision.fetch_add(1) + 1;
                m_lastGlobalAuthor.store(fromPlayerId);
                auto rev = proto::serializeGlobalRevision(revision, fromPlayerId);
                broadcast(rev, ChannelType::Reliable);
                log::debug("P2PManager: GLOBAL REV {} author={} opcode={}", revision, fromPlayerId, static_cast<int>(opcode));
            }
        }
    }

    void P2PManager::relayMessage(int fromPlayerId, const uint8_t* data, size_t len, ChannelType channel) {
        std::vector<uint8_t> relayData(data, data + len);
        broadcast(relayData, channel, fromPlayerId);
    }

    void P2PManager::onPeerDisconnected(int playerId, bool unexpected) {
        std::shared_ptr<rtc::PeerConnection> pcToClose;
        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) {
                log::debug("P2PManager: ignoring duplicate disconnect for player {}", playerId);
                return;
            }
            if (unexpected && m_role == Role::Host && !it->second.playerName.empty()) {
                m_recentDisconnectedNames[it->second.playerName] = reliabilityNowMs();
            }
            pcToClose = it->second.pc;
            m_peers.erase(it);
        }
        if (pcToClose) pcToClose->close();

        log::info("P2PManager: Player {} disconnected (unexpected={})", playerId, unexpected);

        queueInMainThread([this, playerId, unexpected]() {
            if (m_role == Role::Client && playerId == 0) {
                if (unexpected) {
                    m_state.store(State::Reconnecting);
                    if (m_hostMigrationAvailable.load() && !m_signalingToken.empty()) {
                        requestHostMigration();
                    } else {
                        scheduleClientReconnect();
                    }
                    return;
                }
                for (auto& cb : m_onError) {
                    cb("Host disconnected");
                }
                return;
            }

            for (auto& cb : m_onPeerDisconnected) {
                cb(playerId);
            }

            if (m_role == Role::Host) {
                auto msg = proto::serializePlayerLeft(playerId);
                broadcast(msg, ChannelType::Reliable);
            }
        });
    }



    void P2PManager::hostSession(
        std::string const& playerName,
        std::string const& roomName,
        std::string const& description,
        int playerLimit,
        bool isPrivate,
        std::string const& password
    ) {
        auto selectedNetwork = net::NetworkConfig::load();
        if (selectedNetwork.connectionMode == net::ConnectionMode::Turn && !selectedNetwork.hasTurn()) {
            m_state.store(State::Error);
            m_error = "TURN mode requires TURN host, username and password";
            for (auto& cb : m_onError) cb(m_error);
            return;
        }
        {
            std::lock_guard lock(m_stateMutex);
            m_role = Role::Host;
            m_localPlayerId = 0;
            m_localPlayerName = playerName;
            m_error.clear();
        }
        m_pendingRoomName = roomName.empty() ? (playerName + "'s Room") : roomName;
        m_pendingRoomDescription = description;
        m_pendingRoomPassword = password;
        m_pendingPlayerLimit = std::clamp(playerLimit, 2, 16);
        m_pendingRoomPrivate = isPrivate;

        m_state.store(State::Connecting);
        m_nextPlayerId = 1;
        {
            std::lock_guard lock(m_roomSettingsMutex);
            m_roomSettings = RoomSettings{};
            m_roomSettings.maxPlayers = static_cast<uint32_t>(m_pendingPlayerLimit);
        }
        m_globalRevision.store(0);
        m_lastGlobalAuthor.store(0);
        m_kickedNames.clear();

        signalingCreateRoom(playerName);
    }

    void P2PManager::signalingCreateRoom(std::string const& playerName) {
        auto url = getSignalingUrl() + "/rooms";
        log::info("P2PManager: Creating room on signaling server: {}", url);

        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        auto body = matjson::Value();
        body["playerName"] = playerName;
        body["protocol"] = static_cast<int>(net::kCurrentProtocol);
        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);
        body["transportMode"] = net::NetworkConfig::load().transportModeName();
        body["roomName"] = m_pendingRoomName;
        body["description"] = m_pendingRoomDescription;
        body["playerLimit"] = m_pendingPlayerLimit;
        body["isPrivate"] = m_pendingRoomPrivate;
        body["password"] = m_pendingRoomPassword;
        req.bodyJSON(body);

        m_signalingListener.spawn(
            req.post(url),
            [this](web::WebResponse res) {
                if (res.ok()) {
                    auto json = res.json().unwrapOr(matjson::Value());
                    auto roomCode = json.get<std::string>("roomCode").unwrapOr("");
                    m_signalingRoomId = json.get<std::string>("roomId").unwrapOr("");
                    m_signalingToken = json.get<std::string>("sessionToken").unwrapOr("");
                    m_signalingGeneration = static_cast<uint32_t>(json.get<int>("generation").unwrapOr(0));
                    m_signalingApi = static_cast<uint32_t>(json.get<int>("signalingApi").unwrapOr(1));

                     if (roomCode.empty()) {
                        std::vector<ErrorCb> callbacks;
                        std::string err;
                        {
                            std::lock_guard lock(m_stateMutex);
                            m_error = "Failed to create room: no room code";
                            m_state.store(State::Error);
                            callbacks = m_onError;
                            err = m_error;
                        }
                        for (auto& cb : callbacks) cb(err);
                        return;
                    }

                    {
                        std::lock_guard lock(m_stateMutex);
                        m_roomCode = roomCode;
                    }
                    m_state.store(State::Connected);

                    log::info("P2PManager: Room created with code: {}", roomCode);

                    for (auto& cb : m_onSessionStarted) {
                        cb(roomCode, 0);
                    }

                    startSignalPolling(roomCode, "host", 0);
                    if (net::NetworkConfig::load().allowsHttpRelayFallback()) {
                        startHttpRelayPolling(roomCode);
                    }
                } else {
                    std::vector<ErrorCb> callbacks;
                    std::string err;
                    {
                        std::lock_guard lock(m_stateMutex);
                        m_error = "Signaling server error: " + std::to_string(res.code());
                        m_state.store(State::Error);
                        callbacks = m_onError;
                        err = m_error;
                    }
                    for (auto& cb : callbacks) cb(err);
                }
            }
        );
    }



    void P2PManager::startSignalPolling(std::string const& code, std::string const& role, int playerId) {
        m_signalingActive.store(true);
        log::info("P2PManager: Starting signaling long poll (role={}, playerId={})", role, playerId);
        pollSignalOnce(code, role, playerId);
    }

    void P2PManager::pollSignalOnce(std::string const& code, std::string const& role, int playerId) {
        if (!m_signalingActive.load()) return;

        auto url = getSignalingUrl() + "/rooms/" + code + "/signal?role=" + role + "&playerId=" + std::to_string(playerId);

        auto req = web::WebRequest();
        if (!m_signalingToken.empty()) {
            req.header("Authorization", "Bearer " + m_signalingToken);
        }
        req.timeout(std::chrono::seconds(30));

        m_signalPollListener.spawn(
            req.get(url),
            [this, code, role, playerId](web::WebResponse res) {
                if (!m_signalingActive.load()) return;

                if (res.ok()) {
                    auto json = res.json().unwrapOr(matjson::Value());
                    handleSignalingMessages(json);
                } else {
                    log::warn("P2PManager: Signal poll returned {}", res.code());
                    if (res.code() == 401 || res.code() == 403) {
                        m_signalingActive.store(false);
                        if (m_role == Role::Client) {
                            m_state.store(State::Reconnecting);
                            queueInMainThread([this]() { scheduleClientReconnect(); });
                        } else {
                            queueInMainThread([this]() {
                                for (auto& cb : m_onError) cb("Signaling authentication failed");
                            });
                        }
                        return;
                    }
                }

                if (m_signalingActive.load()) {
                    pollSignalOnce(code, role, playerId);
                }
            }
        );
    }

    void P2PManager::stopSignalPolling() {
        m_signalingActive.store(false);
        m_signalPollListener.cancel();
    }

    void P2PManager::sendSignalingMessage(std::string const& roomCode, matjson::Value const& msg) {
        auto url = getSignalingUrl() + "/rooms/" + roomCode + "/signal";
        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        if (!m_signalingToken.empty()) {
            req.header("Authorization", "Bearer " + m_signalingToken);
        }
        req.bodyJSON(msg);
        async::spawn(
            req.post(url),
            [url](web::WebResponse res) {
                if (!res.ok()) {
                    log::warn(
                        "P2PManager: signaling POST {} failed code={} error={}",
                        url, res.code(), res.errorMessage()
                    );
                }
            }
        );
    }

    void P2PManager::handleSignalingMessages(matjson::Value const& messages) {
        if (!messages.isArray()) return;

        for (size_t i = 0; i < messages.size(); i++) {
            auto msgOpt = messages.get(i);
            if (!msgOpt.isOk()) continue;
            auto msg = msgOpt.unwrap();

            auto type = msg.get<std::string>("type").unwrapOr("");

            if (type == "client_joined") {
                int clientId = msg.get<int>("playerId").unwrapOr(-1);
                auto clientName = msg.get<std::string>("playerName").unwrapOr("Player " + std::to_string(clientId));
                if (clientId >= 0) {
                    auto clientTransport = msg.get<std::string>("transportMode").unwrapOr("auto");
                    auto network = net::NetworkConfig::load();
                    log::info(
                        "P2PManager: Client {} ({}) connecting via signal poll (transport={})",
                        clientId, clientName, clientTransport
                    );
                    m_nextPlayerId = std::max(m_nextPlayerId, clientId + 1);

                    bool immediateHttpRelay =
                        network.httpRelayImmediate() || clientTransport == "http-relay";
                    if (immediateHttpRelay) {
                        PeerInfo peer;
                        peer.playerId = clientId;
                        peer.playerName = clientName;
                        peer.colorIndex = clientId % 6;
                        {
                            std::lock_guard lock(m_peersMutex);
                            m_peers[clientId] = std::move(peer);
                        }
                        startHttpRelayPolling(getRoomCode());
                        activateHttpRelayForPeer(clientId);
                    } else {
                        createHostPeer(clientId, clientName);
                    }
                }
            } else if (type == "answer") {
                auto sdp = msg.get<std::string>("sdp").unwrapOr("");
                int clientId = msg.get<int>("playerId").unwrapOr(-1);
                if (!sdp.empty() && clientId >= 0) {
                    log::info("P2PManager: Received SDP answer from client {} via poll", clientId);

                    size_t setupPos = sdp.find("a=setup:actpass");
                    while (setupPos != std::string::npos) {
                        sdp.replace(setupPos, 15, "a=setup:active");
                        setupPos = sdp.find("a=setup:actpass", setupPos);
                    }

                    log::debug("P2PManager: Received SDP answer ({} bytes)", sdp.size());
                    std::lock_guard lock(m_peersMutex);
                    auto it = m_peers.find(clientId);
                    if (it != m_peers.end() && it->second.pc) {
                        auto state = it->second.pc->signalingState();
                        if (state == rtc::PeerConnection::SignalingState::HaveLocalOffer) {
                            it->second.pc->setRemoteDescription(
                                rtc::Description(sdp, rtc::Description::Type::Answer, rtc::Description::Role::Active));
                            
                            for (auto const& pCand : it->second.pendingCandidates) {
                                try {
                                    it->second.pc->addRemoteCandidate(rtc::Candidate(pCand.candidate, pCand.mid));
                                } catch (std::exception const& e) {
                                    log::warn("P2PManager: buffered ICE candidate rejected: {}", e.what());
                                }
                            }
                            it->second.pendingCandidates.clear();
                        } else {
                            log::warn("P2PManager: Ignoring duplicate answer from client {} (state={})", clientId, (int)state);
                        }
                    }
                }
            } else if (type == "offer") {
                auto sdp = msg.get<std::string>("sdp").unwrapOr("");
                if (!sdp.empty()) {
                    std::lock_guard lock(m_peersMutex);
                    auto it = m_peers.find(0);
                    if (it != m_peers.end() && it->second.pc) {
                        auto state = it->second.pc->signalingState();
                        if (state == rtc::PeerConnection::SignalingState::Stable) {
                            log::info("P2PManager: Received host's SDP offer via poll");
                            it->second.pc->setRemoteDescription(
                                rtc::Description(sdp, rtc::Description::Type::Offer, rtc::Description::Role::ActPass));
                            
                            for (auto const& pCand : it->second.pendingCandidates) {
                                try {
                                    it->second.pc->addRemoteCandidate(rtc::Candidate(pCand.candidate, pCand.mid));
                                } catch (std::exception const& e) {
                                    log::warn("P2PManager: buffered ICE candidate rejected: {}", e.what());
                                }
                            }
                            it->second.pendingCandidates.clear();

                            // libdatachannel generates the answer after a remote offer.
                            // Do not force a second local description here; Android was
                            // producing duplicate SDP answers from this path.
                        } else {
                            log::warn("P2PManager: Ignoring duplicate offer (state={})", (int)state);
                        }
                    }
                }
            } else if (type == "candidate") {
                auto cand = msg.get<std::string>("candidate").unwrapOr("");
                auto mid = msg.get<std::string>("mid").unwrapOr("");
                int clientId = msg.get<int>("playerId").unwrapOr(-1);
                int fromId = (m_role == Role::Host) ? clientId : 0;
                
                if (!cand.empty() && fromId >= 0) {
                    std::lock_guard lock(m_peersMutex);
                    auto it = m_peers.find(fromId);
                    if (it != m_peers.end() && it->second.pc) {
                        log::debug(
                            "P2PManager: remote ICE candidate from {} received (mid='{}', bytes={})",
                            fromId,
                            mid,
                            cand.size()
                        );
                        if (it->second.pc->remoteDescription().has_value()) {
                            try {
                                it->second.pc->addRemoteCandidate(rtc::Candidate(cand, mid));
                            } catch (std::exception const& e) {
                                log::warn(
                                    "P2PManager: failed to apply remote ICE candidate from {}: {}",
                                    fromId,
                                    e.what()
                                );
                            }
                        } else {
                            log::info("P2PManager: Remote description not set, buffering candidate from {}", fromId);
                            it->second.pendingCandidates.push_back({cand, mid});
                        }
                    }
                }
            }
        }
    }



    void P2PManager::joinSession(
        std::string const& roomCode,
        std::string const& playerName,
        std::string const& password
    ) {
        auto selectedNetwork = net::NetworkConfig::load();
        if (selectedNetwork.connectionMode == net::ConnectionMode::Turn && !selectedNetwork.hasTurn()) {
            m_state.store(State::Error);
            m_error = "TURN mode requires TURN host, username and password";
            for (auto& cb : m_onError) cb(m_error);
            return;
        }
        {
            std::lock_guard lock(m_stateMutex);
            m_role = Role::Client;
            m_roomCode = roomCode;
            m_localPlayerName = playerName;
            m_error.clear();
        }
        m_pendingJoinPassword = password;
        m_state.store(State::Connecting);
        m_globalRevision.store(0);
        m_lastGlobalAuthor.store(0);
        m_forceRelayNextJoin.store(false);

        signalingJoinRoom(roomCode, playerName);
    }

    void P2PManager::signalingJoinRoom(std::string const& roomCode, std::string const& playerName) {
        auto url = getSignalingUrl() + "/rooms/" + roomCode + "/join";
        log::info("P2PManager: Joining room {} on signaling server", roomCode);

        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        if (!m_signalingToken.empty()) {
            req.header("Authorization", "Bearer " + m_signalingToken);
        }
        auto body = matjson::Value();
        body["playerName"] = playerName;
        body["protocol"] = static_cast<int>(net::kCurrentProtocol);
        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);
        body["transportMode"] = net::NetworkConfig::load().transportModeName();
        body["password"] = m_pendingJoinPassword;
        req.bodyJSON(body);

        m_signalingListener.spawn(
            req.post(url),
            [this, roomCode, playerName](web::WebResponse res) {
                if (res.ok()) {
                    auto json = res.json().unwrapOr(matjson::Value());
                    m_localPlayerId = json.get<int>("playerId").unwrapOr(-1);
                    auto hostName = json.get<std::string>("hostName").unwrapOr("Host");
                    auto hostTransportMode = json.get<std::string>("hostTransportMode").unwrapOr("auto");
                    m_signalingToken = json.get<std::string>("sessionToken").unwrapOr(m_signalingToken);
                    m_signalingGeneration = static_cast<uint32_t>(json.get<int>("generation").unwrapOr(static_cast<int>(m_signalingGeneration)));
                    m_signalingApi = static_cast<uint32_t>(json.get<int>("signalingApi").unwrapOr(static_cast<int>(m_signalingApi)));

                    if (m_localPlayerId < 0) {
                        if (m_state.load() == State::Reconnecting) {
                            log::warn("P2PManager: reconnect response had no playerId; retrying");
                            scheduleClientReconnect();
                            return;
                        }
                        std::vector<ErrorCb> callbacks;
                        std::string err;
                        {
                            std::lock_guard lock(m_stateMutex);
                            m_error = "Failed to join room";
                            m_state.store(State::Error);
                            callbacks = m_onError;
                            err = m_error;
                        }
                        for (auto& cb : callbacks) cb(err);
                        return;
                    }

                    log::info(
                        "P2PManager: Joined room {} as player {} (host transport={})",
                        roomCode, m_localPlayerId, hostTransportMode
                    );

                    auto network = net::NetworkConfig::load();
                    bool immediateHttpRelay =
                        network.httpRelayImmediate() || hostTransportMode == "http-relay";
                    if (immediateHttpRelay) {
                        PeerInfo hostPeer;
                        hostPeer.playerId = 0;
                        hostPeer.playerName = hostName;
                        hostPeer.colorIndex = 0;
                        {
                            std::lock_guard lock(m_peersMutex);
                            m_peers[0] = std::move(hostPeer);
                        }
                        startSignalPolling(roomCode, "client", m_localPlayerId);
                        startHttpRelayPolling(roomCode);
                        activateHttpRelayForPeer(0);
                        return;
                    }

                    bool relayRetry = m_forceRelayNextJoin.exchange(false);
                    auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig(relayRetry));

                    PeerInfo hostPeer;
                    hostPeer.pc = pc;
                    hostPeer.playerId = 0;
                    hostPeer.playerName = hostName;
                    hostPeer.colorIndex = 0;

                    int myId = m_localPlayerId;

                    pc->onDataChannel([this](std::shared_ptr<rtc::DataChannel> dc) {
                        bool isReliable = dc->label() == "reliable";
                        log::info("P2PManager: Received {} data channel", dc->label());
                        
                        {
                            std::lock_guard lock(m_peersMutex);
                            auto it = m_peers.find(0);
                            if (it != m_peers.end()) {
                                if (isReliable) it->second.reliable = dc;
                                else it->second.unreliable = dc;
                            }
                        }

                        dc->onOpen([this, isReliable]() {
                            log::info("P2PManager: {} channel to host opened", isReliable ? "Reliable" : "Unreliable");
                            checkPeerReady(0);
                        });

                        dc->onMessage([this](auto data) {
                            if (auto* binaryMsg = std::get_if<rtc::binary>(&data)) {
                                onPeerMessage(0, reinterpret_cast<const uint8_t*>(binaryMsg->data()), binaryMsg->size());
                            }
                        });

                        dc->onClosed([this]() { log::info("P2PManager: Channel to host closed"); });
                    });

                    auto answerSent = std::make_shared<bool>(false);

                    pc->onLocalCandidate([this, myId, roomCode](rtc::Candidate candidate) {
                        auto candidateText = std::string(candidate.candidate());
                        auto candidateMid = std::string(candidate.mid());
                        log::debug(
                            "P2PManager: local ICE candidate client->host (mid='{}', bytes={})",
                            candidateMid,
                            candidateText.size()
                        );
                        auto body = matjson::Value();
                        body["type"] = "candidate";
                        body["candidate"] = candidateText;
                        body["mid"] = candidateMid;
                        body["playerId"] = myId;
                        queueInMainThread([this, roomCode, body]() {
                            sendSignalingMessage(roomCode, body);
                        });
                    });

                    pc->onLocalDescription([this, pc, myId, roomCode, answerSent](rtc::Description desc) {
                        std::string sdp = std::string(desc);
                        
                        size_t setupPos = sdp.find("a=setup:actpass");
                        while (setupPos != std::string::npos) {
                            sdp.replace(setupPos, 15, "a=setup:active");
                            setupPos = sdp.find("a=setup:actpass", setupPos);
                        }
                        
                        log::info("P2PManager: Local description set, sending SDP answer via HTTP (early/trickle)");

                        queueInMainThread([this, sdp, myId, roomCode, answerSent]() {
                            if (*answerSent) return;
                            *answerSent = true;
                            auto body = matjson::Value();
                            body["type"] = "answer";
                            body["sdp"] = sdp;
                            body["playerId"] = myId;
                            sendSignalingMessage(roomCode, body);
                        });
                    });

                    pc->onGatheringStateChange([this, pc, myId, roomCode, answerSent](
                        rtc::PeerConnection::GatheringState state)
                    {
                        if (state == rtc::PeerConnection::GatheringState::Complete) {
                            auto desc = pc->localDescription();
                            if (desc.has_value()) {
                                std::string sdp = std::string(desc.value());

                                size_t setupPos = sdp.find("a=setup:actpass");
                                while (setupPos != std::string::npos) {
                                    sdp.replace(setupPos, 15, "a=setup:active");
                                    setupPos = sdp.find("a=setup:actpass", setupPos);
                                }

                                queueInMainThread([this, sdp, myId, roomCode, answerSent]() {
                                    if (*answerSent) return;
                                    *answerSent = true;
                                    log::info("P2PManager: ICE gathering complete, sending SDP answer via HTTP (fallback)");
                                    auto body = matjson::Value();
                                    body["type"] = "answer";
                                    body["sdp"] = sdp;
                                    body["playerId"] = myId;
                                    sendSignalingMessage(roomCode, body);
                                });
                            }
                        }
                    });

                    pc->onStateChange([this, pc, relayRetry](rtc::PeerConnection::State state) {
                        log::info("P2PManager: client PeerConnection state={}", static_cast<int>(state));
                        if (state != rtc::PeerConnection::State::Disconnected &&
                            state != rtc::PeerConnection::State::Failed &&
                            state != rtc::PeerConnection::State::Closed) {
                            return;
                        }

                        queueInMainThread([this, pc, relayRetry]() {
                            bool currentPeer = false;
                            bool transportReady = false;
                            {
                                std::lock_guard lock(m_peersMutex);
                                auto it = m_peers.find(0);
                                if (it != m_peers.end() && it->second.pc == pc) {
                                    currentPeer = true;
                                    transportReady = it->second.ready || it->second.connectionAnnounced;
                                }
                            }
                            if (!currentPeer) return; // stale Closed/Failed callback
                            {
                                std::lock_guard lock(m_peersMutex);
                                auto it = m_peers.find(0);
                                if (it != m_peers.end() && it->second.httpRelay) {
                                    log::debug("P2PManager: ignoring WebRTC state change after HTTP relay takeover");
                                    return;
                                }
                            }

                            auto network = net::NetworkConfig::load();
                            if (
                                network.connectionMode == net::ConnectionMode::Auto &&
                                !transportReady && !relayRetry && !network.forceTurnRelay && network.hasTurn()
                            ) {
                                log::warn("P2PManager: initial direct/STUN ICE failed; scheduling relay-only retry");
                                {
                                    std::lock_guard lock(m_peersMutex);
                                    auto it = m_peers.find(0);
                                    if (it != m_peers.end() && it->second.pc == pc) {
                                        m_peers.erase(it);
                                    }
                                }
                                pc->close();
                                stopSignalPolling();
                                m_forceRelayNextJoin.store(true);
                                m_state.store(State::Reconnecting);
                                scheduleClientReconnect();
                                return;
                            }

                            onPeerDisconnected(0, true);
                        });
                    });

                    {
                        std::lock_guard lock(m_peersMutex);
                        m_peers[0] = std::move(hostPeer);
                    }

                    startSignalPolling(roomCode, "client", m_localPlayerId);
                    if (network.connectionMode == net::ConnectionMode::Auto) {
                        scheduleHttpRelayFallback(0);
                    }

                } else if (res.code() == 403) {
                    if (m_state.load() == State::Reconnecting) {
                        log::warn("P2PManager: reconnect join rejected with 403; stopping reconnect");
                    }
                    std::vector<ErrorCb> callbacks;
                    std::string err;
                    {
                        std::lock_guard lock(m_stateMutex);
                        m_error = "Invalid room password";
                        m_state.store(State::Error);
                        callbacks = m_onError;
                        err = m_error;
                    }
                    for (auto& cb : callbacks) cb(err);
                } else if (res.code() == 404) {
                    if (m_state.load() == State::Reconnecting) {
                        log::warn("P2PManager: reconnect join returned 404; retrying");
                        scheduleClientReconnect();
                        return;
                    }
                    std::vector<ErrorCb> callbacks;
                    std::string err;
                    {
                        std::lock_guard lock(m_stateMutex);
                        m_error = "Room not found";
                        m_state.store(State::Error);
                        callbacks = m_onError;
                        err = m_error;
                    }
                    for (auto& cb : callbacks) cb(err);
                } else {
                    if (m_state.load() == State::Reconnecting) {
                        log::warn("P2PManager: reconnect join failed with {}; retrying", res.code());
                        scheduleClientReconnect();
                        return;
                    }
                    std::vector<ErrorCb> callbacks;
                    std::string err;
                    {
                        std::lock_guard lock(m_stateMutex);
                        m_error = "Failed to join room: " + std::to_string(res.code());
                        m_state.store(State::Error);
                        callbacks = m_onError;
                        err = m_error;
                    }
                    for (auto& cb : callbacks) cb(err);
                }
            }
        );
    }



    void P2PManager::createHostPeer(int clientPlayerId, std::string const& clientName) {
        auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig(false));
        auto roomCode = getRoomCode();
        auto offerSent = std::make_shared<bool>(false);

        // Register negotiation callbacks before creating data channels. Creating
        // the first data channel can immediately trigger negotiation in
        // libdatachannel; registering these callbacks afterwards can lose the
        // first local description or early ICE candidates.
        pc->onLocalCandidate([this, clientPlayerId, roomCode](rtc::Candidate candidate) {
            auto candidateText = std::string(candidate.candidate());
            auto candidateMid = std::string(candidate.mid());
            log::debug(
                "P2PManager: local ICE candidate host->{} (mid='{}', bytes={})",
                clientPlayerId,
                candidateMid,
                candidateText.size()
            );
            auto body = matjson::Value();
            body["type"] = "candidate";
            body["candidate"] = candidateText;
            body["mid"] = candidateMid;
            body["targetPlayerId"] = clientPlayerId;
            queueInMainThread([this, roomCode, body]() {
                sendSignalingMessage(roomCode, body);
            });
        });

        pc->onLocalDescription([this, clientPlayerId, roomCode, offerSent](rtc::Description desc) {
            std::string sdp = std::string(desc);
            log::info(
                "P2PManager: Local description set, sending SDP offer for player {} via HTTP (early/trickle)",
                clientPlayerId
            );

            queueInMainThread([this, sdp, clientPlayerId, roomCode, offerSent]() {
                if (*offerSent) return;
                *offerSent = true;
                auto body = matjson::Value();
                body["type"] = "offer";
                body["sdp"] = sdp;
                body["targetPlayerId"] = clientPlayerId;
                sendSignalingMessage(roomCode, body);
            });
        });

        pc->onGatheringStateChange([this, pc, clientPlayerId, roomCode, offerSent](
            rtc::PeerConnection::GatheringState state
        ) {
            log::debug(
                "P2PManager: host ICE gathering state={} player={}",
                static_cast<int>(state),
                clientPlayerId
            );
            if (state != rtc::PeerConnection::GatheringState::Complete) return;

            auto desc = pc->localDescription();
            if (!desc.has_value()) return;
            std::string sdp = std::string(desc.value());

            queueInMainThread([this, sdp, clientPlayerId, roomCode, offerSent]() {
                if (*offerSent) return;
                *offerSent = true;
                log::info(
                    "P2PManager: ICE gathering complete, sending SDP offer for player {} via HTTP (fallback)",
                    clientPlayerId
                );
                auto body = matjson::Value();
                body["type"] = "offer";
                body["sdp"] = sdp;
                body["targetPlayerId"] = clientPlayerId;
                sendSignalingMessage(roomCode, body);
            });
        });

        pc->onStateChange([this, pc, clientPlayerId](rtc::PeerConnection::State state) {
            log::info(
                "P2PManager: host PeerConnection state={} player={}",
                static_cast<int>(state),
                clientPlayerId
            );
            if (state == rtc::PeerConnection::State::Disconnected ||
                state == rtc::PeerConnection::State::Failed ||
                state == rtc::PeerConnection::State::Closed) {
                queueInMainThread([this, clientPlayerId]() {
                    {
                        std::lock_guard lock(m_peersMutex);
                        auto it = m_peers.find(clientPlayerId);
                        if (it != m_peers.end() && it->second.httpRelay) {
                            log::debug("P2PManager: ignoring host WebRTC failure for HTTP relay peer {}", clientPlayerId);
                            return;
                        }
                    }
                    onPeerDisconnected(clientPlayerId, true);
                });
            }
        });

        auto reliable = pc->createDataChannel("reliable");

        rtc::DataChannelInit unreliableInit;
        unreliableInit.reliability.maxRetransmits = 0;
        auto unreliable = pc->createDataChannel("unreliable", unreliableInit);

        PeerInfo peer;
        peer.pc = pc;
        peer.reliable = reliable;
        peer.unreliable = unreliable;
        peer.playerId = clientPlayerId;
        peer.playerName = clientName;
        peer.colorIndex = clientPlayerId % 6;

        auto recentIt = m_recentDisconnectedNames.find(clientName);
        if (recentIt != m_recentDisconnectedNames.end()) {
            constexpr uint64_t kReconnectIdentityWindowMs = 20000;
            if (reliabilityNowMs() - recentIt->second <= kReconnectIdentityWindowMs) {
                peer.reconnecting = true;
                log::info("P2PManager: player {} ({}) classified as reconnect", clientPlayerId, clientName);
            }
            m_recentDisconnectedNames.erase(recentIt);
        }

        auto setupChannelCallbacks = [this, clientPlayerId](std::shared_ptr<rtc::DataChannel> dc, bool isReliable) {
            dc->onOpen([this, clientPlayerId, isReliable]() {
                log::info(
                    "P2PManager: {} channel to player {} opened",
                    isReliable ? "Reliable" : "Unreliable",
                    clientPlayerId
                );
                checkPeerReady(clientPlayerId);
            });

            dc->onMessage([this, clientPlayerId](auto data) {
                if (auto* binaryMsg = std::get_if<rtc::binary>(&data)) {
                    onPeerMessage(
                        clientPlayerId,
                        reinterpret_cast<const uint8_t*>(binaryMsg->data()),
                        binaryMsg->size()
                    );
                }
            });

            dc->onClosed([this, clientPlayerId]() {
                log::info("P2PManager: Channel to player {} closed", clientPlayerId);
            });
        };

        setupChannelCallbacks(reliable, true);
        setupChannelCallbacks(unreliable, false);

        {
            std::lock_guard lock(m_peersMutex);
            m_peers[clientPlayerId] = std::move(peer);
        }

        // createDataChannel() normally starts negotiation automatically. Only
        // request a local description explicitly when the connection is still
        // stable, avoiding duplicate HaveLocalOffer transitions.
        if (pc->signalingState() == rtc::PeerConnection::SignalingState::Stable) {
            pc->setLocalDescription();
        } else {
            log::debug(
                "P2PManager: offer already generated for player {}; skipping duplicate setLocalDescription",
                clientPlayerId
            );
        }
    }



    void P2PManager::finalizePeerHandshake(int playerId) {
        int pid = -1;
        std::string name;
        int colorIdx = 0;
        std::vector<PendingMessage> pending;

        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) return;

            auto& peer = it->second;
            if (!peer.ready || !peer.protocolVerified || peer.connectionAnnounced) return;

            peer.connectionAnnounced = true;
            pid = peer.playerId;
            name = peer.playerName;
            colorIdx = peer.colorIndex;
            pending = std::move(peer.pendingMessages);
            peer.pendingMessages.clear();
        }

        if (m_role == Role::Host && m_kickedNames.contains(name)) {
            log::warn("P2PManager: rejected session-banned player {} ({})", pid, name);
            kickPlayer(pid);
            return;
        }

        if (m_role == Role::Host && pid > 0 && !isPeerReconnect(pid)) {
            auto settings = getRoomSettings();
            size_t peerCount = 0;
            {
                std::lock_guard lock(m_peersMutex);
                peerCount = m_peers.size() + 1; // + host
            }
            std::string rejection;
            if (settings.locked) rejection = "Room is locked by host";
            else if (peerCount > settings.maxPlayers) rejection = "Room is full";
            if (!rejection.empty()) {
                auto packet = proto::serializeKickPlayer(pid, rejection);
                sendTo(pid, packet, ChannelType::Reliable);
                log::warn("P2PManager: rejected player {}: {}", pid, rejection);
                std::thread([this, pid]() {
                    std::this_thread::sleep_for(std::chrono::milliseconds(300));
                    onPeerDisconnected(pid, false);
                }).detach();
                return;
            }
        }

        log::info(
            "P2PManager: protocol handshake complete for player {}; releasing {} pending messages",
            pid,
            pending.size()
        );

        if (m_role == Role::Host && pid > 0) {
            auto settings = getRoomSettings();
            auto roomPacket = proto::serializeRoomSettingsChanged(
                settings.maxPlayers, settings.allowBuild, settings.allowDelete, settings.allowWorkshop,
                settings.allowLevelSettings, settings.autoRepair, settings.locked
            );
            sendTo(pid, roomPacket, ChannelType::Reliable);
        }

        for (auto& msg : pending) {
            sendTo(pid, msg.data, msg.channel);
        }

        if (m_role == Role::Client && pid == 0) {
            m_state.store(State::Connected);
            m_reconnectAttempts = 0;
            m_reconnectScheduled.store(false);
            stopSignalPolling();

            auto syncRequest = proto::serializeInitialSyncRequest();
            sendTo(0, syncRequest, ChannelType::Reliable);
            log::info("P2PManager: requested authoritative initial sync from host");
        }

        queueInMainThread([this, pid, name, colorIdx]() {
            if (m_role == Role::Client && pid == 0) {
                auto roomCode = getRoomCode();
                for (auto& cb : m_onSessionStarted) {
                    cb(roomCode, m_localPlayerId);
                }
            }

            for (auto& cb : m_onPeerConnected) {
                cb(pid, name, colorIdx);
            }

            if (m_role == Role::Host) {
                auto msg = proto::serializePlayerJoined(pid, name, colorIdx);
                broadcast(msg, ChannelType::Reliable, pid);
            }
        });
    }

    void P2PManager::checkPeerReady(int playerId) {
        bool becameTransportReady = false;
        int pid = -1;
        std::string name;

        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) return;

            auto& peer = it->second;
            bool reliableOpen = peer.reliable && peer.reliable->isOpen();
            bool unreliableOpen = peer.unreliable && peer.unreliable->isOpen();
            bool transportOpen = peer.httpRelay || (reliableOpen && unreliableOpen);

            if (transportOpen && !peer.ready) {
                peer.ready = true;
                pid = peer.playerId;
                name = peer.playerName;
                becameTransportReady = true;
                log::info(
                    "P2PManager: transport ready for player {} ({}); waiting for protocol handshake",
                    pid,
                    name
                );
            }
        }

        if (!becameTransportReady) return;

        auto hello = proto::serializeProtocolHello(net::kCurrentProtocol, net::kLocalCapabilities);
        sendTo(pid, hello, ChannelType::Reliable);
    }




    void P2PManager::startHttpRelayPolling(std::string const& code) {
        if (m_httpRelayPollingActive.exchange(true)) return;
        log::info("P2PManager: Starting HTTP relay long poll");
        pollHttpRelayOnce(code);
    }

    void P2PManager::stopHttpRelayPolling() {
        m_httpRelayPollingActive.store(false);
        m_httpRelayPollListener.cancel();
    }

    void P2PManager::pollHttpRelayOnce(std::string const& code) {
        if (!m_httpRelayPollingActive.load() || m_signalingToken.empty()) return;

        auto req = web::WebRequest();
        req.header("Authorization", "Bearer " + m_signalingToken);
        req.timeout(std::chrono::seconds(35));
        auto url = getSignalingUrl() + "/rooms/" + code + "/relay";

        m_httpRelayPollListener.spawn(
            req.get(url),
            [this, code](web::WebResponse res) {
                if (!m_httpRelayPollingActive.load()) return;
                if (res.ok()) {
                    handleHttpRelayMessages(res.json().unwrapOr(matjson::Value()));
                } else if (res.code() == 401 || res.code() == 403 || res.code() == 404) {
                    log::warn("P2PManager: HTTP relay poll stopped with {}", res.code());
                    m_httpRelayPollingActive.store(false);
                    return;
                } else if (res.code() == -28) {
                    log::debug("P2PManager: HTTP relay long poll idle timeout; retrying");
                } else {
                    log::warn(
                        "P2PManager: HTTP relay poll returned {} error={}",
                        res.code(), res.errorMessage()
                    );
                }

                if (m_httpRelayPollingActive.load()) pollHttpRelayOnce(code);
            }
        );
    }

    void P2PManager::sendHttpRelayPacket(
        int playerId,
        std::vector<uint8_t> const& data,
        ChannelType channel,
        uint32_t trackedSequence
    ) {
        if (data.empty() || m_signalingToken.empty()) {
            if (trackedSequence != 0) {
                std::lock_guard lock(m_peersMutex);
                auto it = m_peers.find(playerId);
                if (it != m_peers.end()) it->second.httpRelayPostInFlight = false;
            }
            return;
        }
        constexpr size_t kMaxRelayPacketBytes = 48 * 1024;
        if (data.size() > kMaxRelayPacketBytes) {
            log::warn("P2PManager: HTTP relay packet too large ({} bytes)", data.size());
            if (trackedSequence != 0) {
                std::lock_guard lock(m_peersMutex);
                auto it = m_peers.find(playerId);
                if (it != m_peers.end()) it->second.httpRelayPostInFlight = false;
            }
            return;
        }

        auto body = matjson::Value();
        body["targetPlayerId"] = playerId;
        body["channel"] = channel == ChannelType::Reliable ? "reliable" : "unreliable";
        body["payload"] = bytesToHex(data);

        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        req.header("Authorization", "Bearer " + m_signalingToken);
        req.bodyJSON(body);
        auto url = getSignalingUrl() + "/rooms/" + getRoomCode() + "/relay";
        async::spawn(
            req.post(url),
            [this, playerId, trackedSequence](web::WebResponse res) {
                if (trackedSequence != 0) {
                    std::lock_guard lock(m_peersMutex);
                    auto it = m_peers.find(playerId);
                    if (it != m_peers.end()) {
                        auto& peer = it->second;
                        peer.httpRelayPostInFlight = false;
                        if (!res.ok()) {
                            auto pendingIt = peer.pendingReliableAcks.find(trackedSequence);
                            if (pendingIt != peer.pendingReliableAcks.end() && !pendingIt->second.queued) {
                                pendingIt->second.lastSentMs = 0;
                                pendingIt->second.queued = true;
                                peer.bulkReliableQueue.insert(
                                    peer.bulkReliableQueue.begin(),
                                    pendingIt->second.envelope
                                );
                            }
                        }
                    }
                }

                if (!res.ok()) {
                    log::warn(
                        "P2PManager: HTTP relay POST to player {} failed code={} error={} sequence={}",
                        playerId, res.code(), res.errorMessage(), trackedSequence
                    );
                } else if (trackedSequence != 0) {
                    log::debug(
                        "P2PManager: HTTP relay accepted reliable sequence #{} for player {}",
                        trackedSequence, playerId
                    );
                }
            }
        );
    }

    void P2PManager::handleHttpRelayMessages(matjson::Value const& messages) {
        if (!messages.isArray()) return;

        for (size_t i = 0; i < messages.size(); ++i) {
            auto item = messages.get(i);
            if (!item.isOk()) continue;
            auto msg = item.unwrap();
            int fromId = msg.get<int>("fromPlayerId").unwrapOr(-1);
            auto payloadHex = msg.get<std::string>("payload").unwrapOr("");
            if (fromId < 0 || payloadHex.empty()) continue;

            std::vector<uint8_t> payload;
            if (!hexToBytes(payloadHex, payload) || payload.empty() || payload.size() > 48 * 1024) {
                log::warn("P2PManager: rejected malformed HTTP relay packet from {}", fromId);
                continue;
            }

            bool newlyRelayed = false;
            {
                std::lock_guard lock(m_peersMutex);
                auto it = m_peers.find(fromId);
                if (it == m_peers.end()) continue;
                if (!it->second.httpRelay) {
                    it->second.httpRelay = true;
                    newlyRelayed = true;
                }
            }
            if (newlyRelayed) {
                log::warn("P2PManager: peer {} switched to HTTP relay transport", fromId);
                checkPeerReady(fromId);
            }

            onPeerMessage(fromId, payload.data(), payload.size());
        }
    }

    void P2PManager::activateHttpRelayForPeer(int playerId) {
        bool activate = false;
        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) return;
            if (it->second.connectionAnnounced || it->second.httpRelay) return;
            it->second.httpRelay = true;
            activate = true;
        }
        if (!activate) return;

        log::warn("P2PManager: activating HTTP relay transport for player {}", playerId);
        startHttpRelayPolling(getRoomCode());
        checkPeerReady(playerId);
    }

    void P2PManager::scheduleHttpRelayFallback(int playerId) {
        if (net::NetworkConfig::load().connectionMode != net::ConnectionMode::Auto) return;
        std::thread([this, playerId]() {
            std::this_thread::sleep_for(std::chrono::seconds(8));
            queueInMainThread([this, playerId]() {
                if (m_state.load() == State::Disconnected || m_state.load() == State::Error) return;
                activateHttpRelayForPeer(playerId);
            });
        }).detach();
    }

    void P2PManager::requestHostMigration() {
        if (m_role != Role::Client || m_roomCode.empty() || m_signalingToken.empty()) {
            scheduleClientReconnect();
            return;
        }

        auto url = getSignalingUrl() + "/rooms/" + m_roomCode + "/migrate";
        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        req.header("Authorization", "Bearer " + m_signalingToken);
        auto body = matjson::Value();
        body["generation"] = static_cast<int>(m_signalingGeneration);
        body["playerName"] = m_localPlayerName;
        req.bodyJSON(body);

        log::warn("P2PManager: host lost; requesting migration for generation {}", m_signalingGeneration);
        m_migrationListener.spawn(
            req.post(url),
            [this](web::WebResponse res) {
                if (m_role != Role::Client || m_state.load() != State::Reconnecting) return;
                if (!res.ok()) {
                    log::warn("P2PManager: migration endpoint returned {}; reconnect fallback", res.code());
                    scheduleClientReconnect();
                    return;
                }

                auto json = res.json().unwrapOr(matjson::Value());
                auto role = json.get<std::string>("role").unwrapOr("client");
                auto generation = static_cast<uint32_t>(
                    json.get<int>("generation").unwrapOr(static_cast<int>(m_signalingGeneration))
                );
                m_signalingGeneration = generation;

                if (role == "host") {
                    auto token = json.get<std::string>("sessionToken").unwrapOr(m_signalingToken);
                    becomeMigratedHost(token, generation);
                } else {
                    scheduleClientReconnect();
                }
            }
        );
    }

    void P2PManager::becomeMigratedHost(std::string const& token, uint32_t generation) {
        stopSignalPolling();
        {
            std::lock_guard lock(m_peersMutex);
            for (auto& [id, peer] : m_peers) {
                (void)id;
                if (peer.reliable) peer.reliable->close();
                if (peer.unreliable) peer.unreliable->close();
                if (peer.pc) peer.pc->close();
            }
            m_peers.clear();
        }

        {
            std::lock_guard lock(m_stateMutex);
            m_role = Role::Host;
            m_localPlayerId = 0;
        }
        m_signalingToken = token;
        m_signalingGeneration = generation;
        m_nextPlayerId = 1;
        m_reconnectAttempts = 0;
        m_reconnectScheduled.store(false);
        m_hostMigrationAvailable.store(false);
        m_state.store(State::Connected);

        auto room = getRoomCode();
        startSignalPolling(room, "host", 0);
        log::info("P2PManager: promoted to host for room {} generation {}", room, generation);
        queueInMainThread([this, room]() {
            for (auto& cb : m_onSessionStarted) cb(room, 0);
        });
    }

    void P2PManager::scheduleClientReconnect() {
        if (m_role != Role::Client) return;
        if (m_reconnectScheduled.exchange(true)) return;

        constexpr int kMaxReconnectAttempts = 6;
        if (m_reconnectAttempts >= kMaxReconnectAttempts) {
            m_reconnectScheduled.store(false);
            m_state.store(State::Error);
            for (auto& cb : m_onError) cb("Reconnect failed");
            return;
        }

        int attempt = ++m_reconnectAttempts;
        int delayMs = std::min(5000, 500 * (1 << std::min(attempt - 1, 3)));
        auto room = getRoomCode();
        auto name = m_localPlayerName;

        log::warn(
            "P2PManager: scheduling reconnect attempt {} in {} ms",
            attempt,
            delayMs
        );

        std::thread([this, delayMs, room, name]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(delayMs));
            queueInMainThread([this, room, name]() {
                m_reconnectScheduled.store(false);
                if (m_role != Role::Client || m_state.load() != State::Reconnecting) return;
                stopSignalPolling();
                log::info("P2PManager: reconnecting to room {}", room);
                signalingJoinRoom(room, name);
            });
        }).detach();
    }


    void P2PManager::leaveSession() {
        stopSignalPolling();
        stopHttpRelayPolling();

        {
            std::lock_guard lock(m_peersMutex);
            for (auto& [id, peer] : m_peers) {
                if (peer.reliable) peer.reliable->close();
                if (peer.unreliable) peer.unreliable->close();
                if (peer.pc) peer.pc->close();
            }
            m_peers.clear();
        }

        // Every participant explicitly leaves the signaling directory.
        // Previously only the host sent DELETE, so departed guests remained in
        // room.clients and could later be elected as a ghost migration host.
        if (m_role != Role::None && !m_roomCode.empty() && !m_signalingToken.empty()) {
            auto url = getSignalingUrl() + "/rooms/" + m_roomCode;
            auto req = web::WebRequest();
            req.header("Authorization", "Bearer " + m_signalingToken);
            async::spawn(req.send("DELETE", url));
        }

        {
            std::lock_guard lock(m_incomingMutex);
            std::queue<QueuedMessage> empty;
            std::swap(m_incoming, empty);
        }

        {
            std::lock_guard lock(m_stateMutex);
            m_role = Role::None;
            m_roomCode.clear();
            m_localPlayerId = -1;
            m_localPlayerName.clear();
            m_error.clear();
        }

        m_state.store(State::Disconnected);
        m_nextPlayerId = 1;
        m_reconnectAttempts = 0;
        m_reconnectScheduled.store(false);
        m_recentDisconnectedNames.clear();
        m_kickedNames.clear();
        m_globalRevision.store(0);
        m_lastGlobalAuthor.store(0);
        m_signalingRoomId.clear();
        m_signalingToken.clear();
        m_signalingGeneration = 0;
        m_signalingApi = 1;
        m_pendingRoomName.clear();
        m_pendingRoomDescription.clear();
        m_pendingRoomPassword.clear();
        m_pendingJoinPassword.clear();
        m_pendingPlayerLimit = 8;
        m_pendingRoomPrivate = false;
        m_hostMigrationAvailable.store(false);

        log::info("P2PManager: Session ended");
    }

} // namespace mpedit

