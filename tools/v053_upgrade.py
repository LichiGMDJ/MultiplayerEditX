from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    return text.replace(old, new, 1)


# Binary protocol: capability-bearing hello, backward-readable by v8.
hpp_path = Path("src/BinaryProtocol.hpp")
hpp = hpp_path.read_text(encoding="utf-8")
hpp = once(
    hpp,
    "    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion);",
    "    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion, uint64_t capabilities);",
    "protocol hello declaration",
)
hpp = once(
    hpp,
    "    struct ProtocolHelloMsg {\n        uint32_t protocolVersion = 0;\n    };",
    "    struct ProtocolHelloMsg {\n        uint32_t protocolVersion = 0;\n        uint64_t capabilities = 0;\n    };",
    "protocol hello struct",
)
hpp_path.write_text(hpp, encoding="utf-8")

cpp_path = Path("src/BinaryProtocol.cpp")
cpp = cpp_path.read_text(encoding="utf-8")
cpp = once(
    cpp,
    """    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion) {
        Writer w;
        w.writeOpcode(Opcode::ProtocolHello);
        w.writeVarInt(protocolVersion);
        return std::move(w.takeData());
    }""",
    """    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion, uint64_t capabilities) {
        Writer w;
        w.writeOpcode(Opcode::ProtocolHello);
        w.writeVarInt(protocolVersion);
        w.writeU32(static_cast<uint32_t>(capabilities & 0xffffffffull));
        w.writeU32(static_cast<uint32_t>(capabilities >> 32));
        return std::move(w.takeData());
    }""",
    "protocol hello serializer",
)
cpp = once(
    cpp,
    """    ProtocolHelloMsg deserializeProtocolHello(Reader& r) {
        ProtocolHelloMsg msg;
        msg.protocolVersion = r.readVarInt();
        return msg;
    }""",
    """    ProtocolHelloMsg deserializeProtocolHello(Reader& r) {
        ProtocolHelloMsg msg;
        msg.protocolVersion = r.readVarInt();
        if (r.remaining() >= 8) {
            uint64_t low = r.readU32();
            uint64_t high = r.readU32();
            msg.capabilities = low | (high << 32);
        }
        return msg;
    }""",
    "protocol hello deserializer",
)
cpp_path.write_text(cpp, encoding="utf-8")


# P2PManager public state and signaling migration state.
p2p_hpp_path = Path("src/P2PManager.hpp")
p2p_hpp = p2p_hpp_path.read_text(encoding="utf-8")
p2p_hpp = once(
    p2p_hpp,
    '#include "BinaryProtocol.hpp"\n',
    '#include "BinaryProtocol.hpp"\n#include "net/ProtocolCapabilities.hpp"\n',
    "p2p capability include",
)
p2p_hpp = once(
    p2p_hpp,
    """        bool isPeerReconnect(int playerId);
        uint32_t getGlobalRevision() const { return m_globalRevision.load(); }""",
    """        bool isPeerReconnect(int playerId);
        bool supportsCapability(int playerId, net::Capability capability);
        std::size_t getTotalReliableQueueDepth();
        uint32_t getGlobalRevision() const { return m_globalRevision.load(); }""",
    "p2p diagnostics api",
)
p2p_hpp = once(
    p2p_hpp,
    """            uint32_t protocolVersion = 0;
            std::vector<std::vector<uint8_t>> preHandshakeMessages;""",
    """            uint32_t protocolVersion = 0;
            uint64_t capabilities = 0;
            std::vector<std::vector<uint8_t>> preHandshakeMessages;""",
    "peer capabilities",
)
p2p_hpp = once(
    p2p_hpp,
    """        void flushBulkReliableQueues();
        void scheduleClientReconnect();""",
    """        void flushBulkReliableQueues();
        void requestHostMigration();
        void becomeMigratedHost(std::string const& token, uint32_t generation);
        void scheduleClientReconnect();""",
    "migration methods",
)
p2p_hpp = once(
    p2p_hpp,
    """        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalingListener;  // room create/join
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalPollListener; // long-poll loop
        std::atomic<bool> m_signalingActive{false};
        std::string m_signalingRoomId;   // server-side room ID""",
    """        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalingListener;  // room create/join
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalPollListener; // long-poll loop
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_migrationListener;
        std::atomic<bool> m_signalingActive{false};
        std::atomic<bool> m_hostMigrationAvailable{false};
        std::string m_signalingRoomId;   // server-side room ID
        std::string m_signalingToken;
        uint32_t m_signalingGeneration = 0;
        uint32_t m_signalingApi = 1;""",
    "signaling security state",
)
p2p_hpp_path.write_text(p2p_hpp, encoding="utf-8")


p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = once(
    p2p,
    '#include "BinaryProtocol.hpp"\n',
    '#include "BinaryProtocol.hpp"\n#include "net/NetworkConfig.hpp"\n#include "net/ProtocolCapabilities.hpp"\n#include "sync/SyncMetrics.hpp"\n',
    "p2p architecture includes",
)
p2p = p2p.replace("        constexpr uint32_t kProtocolVersion = 7;\n\n", "", 1)

start = p2p.index("    rtc::Configuration P2PManager::makeRtcConfig() {")
end = p2p.index("    P2PManager::State P2PManager::getState() const {", start)
p2p = p2p[:start] + """    rtc::Configuration P2PManager::makeRtcConfig() {
        rtc::Configuration config;
        config.iceServers.push_back({"stun:stun.l.google.com:19302"});
        config.iceServers.push_back({"stun:stun.cloudflare.com:3478"});

        auto network = net::NetworkConfig::load();
        if (network.hasTurn()) {
            rtc::IceServer turn(
                network.turnHost, 3478, network.turnUsername, network.turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(turn);
            if (network.forceTurnRelay) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
                log::warn("P2PManager: Force TURN diagnostic mode enabled");
            } else {
                log::info("P2PManager: ICE auto mode: direct/STUN preferred, TURN fallback available");
            }
        } else {
            log::info("P2PManager: ICE direct/STUN mode; TURN is not configured");
        }
        return config;
    }

    std::string P2PManager::getSignalingUrl() {
        return net::NetworkConfig::load().signalingUrl;
    }


""" + p2p[end:]

p2p = once(
    p2p,
    """    std::string P2PManager::getError() const {
        std::lock_guard lock(m_stateMutex);
        return m_error;
    }""",
    """    std::string P2PManager::getError() const {
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
    }""",
    "p2p diagnostics implementation",
)

old_handshake = """            auto hello = proto::deserializeProtocolHello(helloReader);
            if (helloReader.hasError() || hello.protocolVersion != kProtocolVersion) {
                log::warn(
                    "P2PManager: incompatible protocol from player {} (remote={}, local={})",
                    fromPlayerId,
                    hello.protocolVersion,
                    kProtocolVersion
                );

                auto errorMsg = proto::serializeError(
                    "Incompatible Multiplayer Edit protocol. Both players must use v0.5.1 or newer compatible builds."
                );"""
new_handshake = """            auto hello = proto::deserializeProtocolHello(helloReader);
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
                );"""
p2p = once(p2p, old_handshake, new_handshake, "capability handshake")
p2p = once(
    p2p,
    """                    it->second.protocolVerified = true;
                    it->second.protocolVersion = hello.protocolVersion;""",
    """                    it->second.protocolVerified = true;
                    it->second.protocolVersion = hello.protocolVersion;
                    it->second.capabilities = remoteCapabilities;
                    if (m_role == Role::Client && fromPlayerId == 0) {
                        m_hostMigrationAvailable.store(
                            net::hasCapability(remoteCapabilities, net::Capability::HostMigration)
                        );
                    }""",
    "store peer capabilities",
)
p2p = p2p.replace(
    "proto::serializeProtocolHello(kProtocolVersion)",
    "proto::serializeProtocolHello(net::kCurrentProtocol, net::kLocalCapabilities)",
)

p2p = once(
    p2p,
    """    void P2PManager::sendTo(int playerId, std::vector<uint8_t> const& data, ChannelType channel) {
        std::lock_guard lock(m_peersMutex);""",
    """    void P2PManager::sendTo(int playerId, std::vector<uint8_t> const& data, ChannelType channel) {
        sync::SyncMetrics::get().recordOutboundBytes(data.size());
        std::lock_guard lock(m_peersMutex);""",
    "outbound metrics",
)

# Create request and response security metadata.
p2p = once(
    p2p,
    """        body["playerName"] = playerName;
        req.bodyJSON(body);""",
    """        body["playerName"] = playerName;
        body["protocol"] = static_cast<int>(net::kCurrentProtocol);
        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);
        req.bodyJSON(body);""",
    "create signaling metadata",
)
p2p = once(
    p2p,
    '                    m_signalingRoomId = json.get<std::string>("roomId").unwrapOr("");',
    '                    m_signalingRoomId = json.get<std::string>("roomId").unwrapOr("");\n'
    '                    m_signalingToken = json.get<std::string>("sessionToken").unwrapOr("");\n'
    '                    m_signalingGeneration = static_cast<uint32_t>(json.get<int>("generation").unwrapOr(0));\n'
    '                    m_signalingApi = static_cast<uint32_t>(json.get<int>("signalingApi").unwrapOr(1));',
    "create token response",
)

p2p = once(
    p2p,
    """        auto req = web::WebRequest();
        req.timeout(std::chrono::seconds(30));""",
    """        auto req = web::WebRequest();
        if (!m_signalingToken.empty()) {
            req.header("Authorization", "Bearer " + m_signalingToken);
        }
        req.timeout(std::chrono::seconds(30));""",
    "poll bearer auth",
)
p2p = once(
    p2p,
    """        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        req.bodyJSON(msg);
        async::spawn(req.post(url));""",
    """        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        if (!m_signalingToken.empty()) {
            req.header("Authorization", "Bearer " + m_signalingToken);
        }
        req.bodyJSON(msg);
        async::spawn(req.post(url));""",
    "signal post bearer auth",
)

join_at = p2p.index("    void P2PManager::signalingJoinRoom(")
join_tail = p2p[join_at:]
join_tail = once(
    join_tail,
    """        body["playerName"] = playerName;
        req.bodyJSON(body);""",
    """        body["playerName"] = playerName;
        body["protocol"] = static_cast<int>(net::kCurrentProtocol);
        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);
        req.bodyJSON(body);""",
    "join signaling metadata",
)
join_tail = once(
    join_tail,
    """                    m_localPlayerId = json.get<int>("playerId").unwrapOr(-1);
                    auto hostName = json.get<std::string>("hostName").unwrapOr("Host");""",
    """                    m_localPlayerId = json.get<int>("playerId").unwrapOr(-1);
                    auto hostName = json.get<std::string>("hostName").unwrapOr("Host");
                    m_signalingToken = json.get<std::string>("sessionToken").unwrapOr(m_signalingToken);
                    m_signalingGeneration = static_cast<uint32_t>(json.get<int>("generation").unwrapOr(static_cast<int>(m_signalingGeneration)));
                    m_signalingApi = static_cast<uint32_t>(json.get<int>("signalingApi").unwrapOr(static_cast<int>(m_signalingApi)));""",
    "join token response",
)
p2p = p2p[:join_at] + join_tail

p2p = once(
    p2p,
    """                if (unexpected) {
                    m_state.store(State::Reconnecting);
                    scheduleClientReconnect();
                    return;
                }""",
    """                if (unexpected) {
                    m_state.store(State::Reconnecting);
                    if (m_hostMigrationAvailable.load() && !m_signalingToken.empty()) {
                        requestHostMigration();
                    } else {
                        scheduleClientReconnect();
                    }
                    return;
                }""",
    "host loss migration path",
)

migration_impl = r'''    void P2PManager::requestHostMigration() {
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

'''
p2p = once(
    p2p,
    "    void P2PManager::scheduleClientReconnect() {",
    migration_impl + "    void P2PManager::scheduleClientReconnect() {",
    "migration implementation",
)
p2p = once(
    p2p,
    """            auto req = web::WebRequest();
            async::spawn(req.send("DELETE", url));""",
    """            auto req = web::WebRequest();
            if (!m_signalingToken.empty()) {
                req.header("Authorization", "Bearer " + m_signalingToken);
            }
            async::spawn(req.send("DELETE", url));""",
    "authenticated host leave",
)
p2p = once(
    p2p,
    """        m_signalingRoomId.clear();

        log::info("P2PManager: Session ended");""",
    """        m_signalingRoomId.clear();
        m_signalingToken.clear();
        m_signalingGeneration = 0;
        m_signalingApi = 1;
        m_hostMigrationAvailable.store(false);

        log::info("P2PManager: Session ended");""",
    "clear signaling security state",
)
p2p_path.write_text(p2p, encoding="utf-8")


# Serialization performance counter.
action_path = Path("src/ActionSerializer.cpp")
action = action_path.read_text(encoding="utf-8")
action = once(
    action,
    '#include "ActionSerializer.hpp"\n',
    '#include "ActionSerializer.hpp"\n#include "sync/SyncMetrics.hpp"\n',
    "serializer metrics include",
)
action = once(
    action,
    """        if (!obj) return data;

        data.objectID = obj->m_objectID;""",
    """        if (!obj) return data;
        sync::SyncMetrics::get().recordSerializedObjects(1);

        data.objectID = obj->m_objectID;""",
    "serializer metrics count",
)
action_path.write_text(action, encoding="utf-8")


# Adaptive editor policy for O(n) maintenance work.
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
hooks = once(
    hooks,
    '#include "ui/UpdateHelperNode.hpp"\n',
    '#include "ui/UpdateHelperNode.hpp"\n#include "sync/AdaptiveSyncPolicy.hpp"\n#include "sync/SyncMetrics.hpp"\n',
    "adaptive sync includes",
)
hooks = once(
    hooks,
    "        float m_externalCompatScanTimer = 0.f;",
    "        float m_externalCompatScanTimer = 0.f;\n        float m_syncMetricsTimer = 0.f;",
    "metrics timer field",
)
hooks = once(
    hooks,
    """        uint32_t totalChunks = static_cast<uint32_t>(chunks.size());
        uint32_t totalObjects = static_cast<uint32_t>(allUuids.size());""",
    """        uint32_t totalChunks = static_cast<uint32_t>(chunks.size());
        uint32_t totalObjects = static_cast<uint32_t>(allUuids.size());
        sync::SyncMetrics::get().recordSerializedObjects(totalObjects);
        sync::SyncMetrics::get().recordOutboundBytes(compressedBytes.size());
        if (totalObjects >= sync::AdaptiveSyncPolicy::fullSnapshotWarningThreshold()) {
            log::warn("EditorHooks: large authoritative snapshot: {} objects, {} compressed bytes", totalObjects, compressedBytes.size());
        }""",
    "full snapshot metrics",
)
hooks = once(
    hooks,
    """        m_fields->m_integrityCheckTimer += dt;
        if (
            session.getRole() == SessionManager::Role::Client &&
            handler.isInitialSyncCompleted() &&
            !handler.isProcessingRemote() &&
            (m_fields->m_forceIntegrityCheck || m_fields->m_integrityCheckTimer >= 20.0f)
        ) {
            m_fields->m_integrityCheckTimer = 0.f;
            m_fields->m_forceIntegrityCheck = false;
            handler.sendLevelDigestTo(0);
        }""",
    """        m_fields->m_integrityCheckTimer += dt;
        std::size_t liveObjectCount = this->m_objects ? this->m_objects->count() : 0;
        float integrityInterval = sync::AdaptiveSyncPolicy::integrityIntervalSeconds(liveObjectCount);
        bool periodicIntegrityDue =
            sync::AdaptiveSyncPolicy::periodicIntegrityEnabled(liveObjectCount) &&
            m_fields->m_integrityCheckTimer >= integrityInterval;
        if (
            session.getRole() == SessionManager::Role::Client &&
            handler.isInitialSyncCompleted() &&
            !handler.isProcessingRemote() &&
            (m_fields->m_forceIntegrityCheck || periodicIntegrityDue)
        ) {
            m_fields->m_integrityCheckTimer = 0.f;
            m_fields->m_forceIntegrityCheck = false;
            handler.sendLevelDigestTo(0);
        }""",
    "adaptive integrity cadence",
)
hooks = once(
    hooks,
    """            m_fields->m_externalCompatScanTimer >= 0.25f &&
            !isPlaytesting &&""",
    """            m_fields->m_externalCompatScanTimer >=
                sync::AdaptiveSyncPolicy::externalCompatibilityScanIntervalSeconds(liveObjectCount) &&
            !isPlaytesting &&""",
    "adaptive compatibility scan",
)
hooks = once(
    hooks,
    """        // Send cursor position periodically
        m_fields->m_cursorSendTimer += dt;""",
    """        m_fields->m_syncMetricsTimer += dt;
        if (m_fields->m_syncMetricsTimer >= 5.f) {
            m_fields->m_syncMetricsTimer = 0.f;
            auto& metrics = sync::SyncMetrics::get();
            metrics.setReliableQueueDepth(P2PManager::get().getTotalReliableQueueDepth());
            auto sample = metrics.sample();
            log::info(
                "SYNC PERF objects/s={} bytes/s={} reliableQueue={} objectsTotal={} bytesTotal={}",
                sample.objectsPerSecond, sample.bytesPerSecond, sample.reliableQueueDepth,
                sample.totalObjectsSerialized, sample.totalBytesQueued
            );
        }

        // Send cursor position periodically
        m_fields->m_cursorSendTimer += dt;""",
    "sync metrics sampling",
)
hooks_path.write_text(hooks, encoding="utf-8")


cmake_path = Path("CMakeLists.txt")
cmake = cmake_path.read_text(encoding="utf-8")
cmake = cmake.replace("project(MultiplayerEdit VERSION 0.5.1)", "project(MultiplayerEdit VERSION 0.5.3)", 1)
cmake_path.write_text(cmake, encoding="utf-8")

wf_path = Path(".github/workflows/multi-platform-release.yml")
wf = wf_path.read_text(encoding="utf-8")
wf = wf.replace('assert "kProtocolVersion = 7" in p2p', 'assert "net::kCurrentProtocol" in p2p')
wf = once(
    wf,
    '          assert "applyEditorLayers(match, tagged.layer1, tagged.layer2)" in remote\n',
    '          assert "applyEditorLayers(match, tagged.layer1, tagged.layer2)" in remote\n'
    '          capabilities = Path("src/net/ProtocolCapabilities.hpp").read_text(encoding="utf-8")\n'
    '          adaptive = Path("src/sync/AdaptiveSyncPolicy.hpp").read_text(encoding="utf-8")\n'
    '          signaling = Path("server/signaling/server.ts").read_text(encoding="utf-8")\n'
    '          assert "kCurrentProtocol = 8" in capabilities\n'
    '          assert "HostMigration" in capabilities and "AdaptiveSync" in capabilities\n'
    '          assert "periodicIntegrityEnabled" in adaptive\n'
    '          assert "sessionToken" in signaling and "/migrate" in signaling\n'
    '          assert "194.226.126.115" not in p2p\n',
    "workflow architecture checks",
)
wf_path.write_text(wf, encoding="utf-8")

# Remove temporary integration machinery, including the earlier invalid workflow.
for temporary in [
    Path("tools/v053_upgrade.py"),
    Path(".github/workflows/v053-run-upgrade.yml"),
    Path(".github/workflows/v053-universal-network-upgrade.yml"),
]:
    if temporary.exists():
        temporary.unlink()

print("v0.5.3 universal networking architecture integrated")
