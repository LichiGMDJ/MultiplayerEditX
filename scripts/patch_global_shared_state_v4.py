from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


def replace_handler(text: str, opcode: str, new_block: str, label: str) -> str:
    marker = f"        net.on(proto::Opcode::{opcode},"
    start = text.find(marker)
    if start == -1:
        raise SystemExit(f"{label}: handler start not found")
    brace = text.find('{', start)
    if brace == -1:
        raise SystemExit(f"{label}: opening brace not found")
    depth = 0
    close = -1
    for i in range(brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                close = i + 1
                break
    if close == -1:
        raise SystemExit(f"{label}: closing brace not found")
    semi = text.find(';', close)
    if semi == -1:
        raise SystemExit(f"{label}: handler terminator not found")
    return text[:start] + new_block + text[semi + 1:]


# =============================================================================
# Binary protocol v4: global shared state + host kick.
# =============================================================================
proto_hpp_path = Path("src/BinaryProtocol.hpp")
proto_hpp = proto_hpp_path.read_text(encoding="utf-8")
proto_hpp = replace_once(
    proto_hpp,
    '''        BulkPasteEnd       = 0x3F,\n\n        // Cursor (unreliable channel)''',
    '''        BulkPasteEnd       = 0x3F,\n\n        // Global shared-state coordination (reliable channel)\n        GlobalRevision        = 0x42,\n        SharedDigest          = 0x43,\n        GlobalSnapshotRequest = 0x44,\n        KickPlayer            = 0x45,\n\n        // Cursor (unreliable channel)''',
    "global shared-state opcodes",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId);\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    '''    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId);\n\n    std::vector<uint8_t> serializeGlobalRevision(uint32_t revision, int authorPlayerId);\n    std::vector<uint8_t> serializeSharedDigest(\n        uint32_t revision, uint32_t objectCount, std::string const& hash);\n    std::vector<uint8_t> serializeGlobalSnapshotRequest(uint32_t revision);\n    std::vector<uint8_t> serializeKickPlayer(int targetPlayerId, std::string const& reason);\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    "global shared-state serializer declarations",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    struct ErrorMsg {\n        std::string message;\n    };''',
    '''    struct GlobalRevisionMsg {\n        uint32_t revision = 0;\n        int authorPlayerId = 0;\n    };\n    GlobalRevisionMsg deserializeGlobalRevision(Reader& r);\n\n    struct SharedDigestMsg {\n        uint32_t revision = 0;\n        uint32_t objectCount = 0;\n        std::string hash;\n    };\n    SharedDigestMsg deserializeSharedDigest(Reader& r);\n\n    struct GlobalSnapshotRequestMsg {\n        uint32_t revision = 0;\n    };\n    GlobalSnapshotRequestMsg deserializeGlobalSnapshotRequest(Reader& r);\n\n    struct KickPlayerMsg {\n        int targetPlayerId = -1;\n        std::string reason;\n    };\n    KickPlayerMsg deserializeKickPlayer(Reader& r);\n\n    struct ErrorMsg {\n        std::string message;\n    };''',
    "global shared-state deserializer declarations",
)
proto_hpp_path.write_text(proto_hpp, encoding="utf-8")

proto_cpp_path = Path("src/BinaryProtocol.cpp")
proto_cpp = proto_cpp_path.read_text(encoding="utf-8")
proto_cpp = replace_once(
    proto_cpp,
    '''    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId) {\n        Writer w;\n        w.writeOpcode(Opcode::BulkPasteEnd);\n        w.writeVarInt(pasteId);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    '''    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId) {\n        Writer w;\n        w.writeOpcode(Opcode::BulkPasteEnd);\n        w.writeVarInt(pasteId);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeGlobalRevision(uint32_t revision, int authorPlayerId) {\n        Writer w;\n        w.writeOpcode(Opcode::GlobalRevision);\n        w.writeVarInt(revision);\n        w.writeI32(authorPlayerId);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeSharedDigest(\n        uint32_t revision, uint32_t objectCount, std::string const& hash)\n    {\n        Writer w;\n        w.writeOpcode(Opcode::SharedDigest);\n        w.writeVarInt(revision);\n        w.writeVarInt(objectCount);\n        w.writeString(hash);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeGlobalSnapshotRequest(uint32_t revision) {\n        Writer w;\n        w.writeOpcode(Opcode::GlobalSnapshotRequest);\n        w.writeVarInt(revision);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeKickPlayer(int targetPlayerId, std::string const& reason) {\n        Writer w;\n        w.writeOpcode(Opcode::KickPlayer);\n        w.writeI32(targetPlayerId);\n        w.writeString(reason);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    "global shared-state serializers",
)
proto_cpp = replace_once(
    proto_cpp,
    '''    ErrorMsg deserializeError(Reader& r) {''',
    '''    GlobalRevisionMsg deserializeGlobalRevision(Reader& r) {\n        GlobalRevisionMsg msg;\n        msg.revision = r.readVarInt();\n        msg.authorPlayerId = r.readI32();\n        return msg;\n    }\n\n    SharedDigestMsg deserializeSharedDigest(Reader& r) {\n        SharedDigestMsg msg;\n        msg.revision = r.readVarInt();\n        msg.objectCount = r.readVarInt();\n        msg.hash = r.readString();\n        return msg;\n    }\n\n    GlobalSnapshotRequestMsg deserializeGlobalSnapshotRequest(Reader& r) {\n        GlobalSnapshotRequestMsg msg;\n        msg.revision = r.readVarInt();\n        return msg;\n    }\n\n    KickPlayerMsg deserializeKickPlayer(Reader& r) {\n        KickPlayerMsg msg;\n        msg.targetPlayerId = r.readI32();\n        msg.reason = r.readString();\n        return msg;\n    }\n\n    ErrorMsg deserializeError(Reader& r) {''',
    "global shared-state deserializers",
)
proto_cpp_path.write_text(proto_cpp, encoding="utf-8")


# =============================================================================
# P2P manager: global revision sequencer + kick/session-ban.
# =============================================================================
p2p_hpp_path = Path("src/P2PManager.hpp")
p2p_hpp = p2p_hpp_path.read_text(encoding="utf-8")
p2p_hpp = replace_once(
    p2p_hpp,
    '''        bool isPeerReconnect(int playerId);''',
    '''        bool isPeerReconnect(int playerId);\n        uint32_t getGlobalRevision() const { return m_globalRevision.load(); }\n        int getLastGlobalAuthor() const { return m_lastGlobalAuthor.load(); }\n        void kickPlayer(int playerId);''',
    "global state and kick public API",
)
p2p_hpp = replace_once(
    p2p_hpp,
    '''        int m_reconnectAttempts = 0;''',
    '''        int m_reconnectAttempts = 0;\n        std::atomic<uint32_t> m_globalRevision{0};\n        std::atomic<int> m_lastGlobalAuthor{0};\n        std::unordered_set<std::string> m_kickedNames;''',
    "global state fields",
)
p2p_hpp_path.write_text(p2p_hpp, encoding="utf-8")

p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(
    p2p,
    'constexpr uint32_t kProtocolVersion = 3;',
    'constexpr uint32_t kProtocolVersion = 4;',
    "protocol v4",
)

# Classify only completed semantic edits, not bootstrap/recovery/control traffic.
p2p = replace_once(
    p2p,
    '''        uint64_t reliabilityNowMs() {\n            return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(\n                std::chrono::steady_clock::now().time_since_epoch()\n            ).count());\n        }''',
    '''        uint64_t reliabilityNowMs() {\n            return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(\n                std::chrono::steady_clock::now().time_since_epoch()\n            ).count());\n        }\n\n        bool isGlobalEditOpcode(uint8_t raw) {\n            auto opcode = static_cast<proto::Opcode>(raw);\n            return\n                opcode == proto::Opcode::PlaceObjects ||\n                opcode == proto::Opcode::DeleteObjects ||\n                opcode == proto::Opcode::MoveObjects ||\n                opcode == proto::Opcode::TransformObjects ||\n                opcode == proto::Opcode::ReconcileObjects ||\n                opcode == proto::Opcode::UpdateObjects ||\n                opcode == proto::Opcode::UpdateSettings ||\n                opcode == proto::Opcode::BulkPasteEnd;\n        }''',
    "global edit opcode classifier",
)

# All v4 coordination frames use reliable ordered ACK delivery.
p2p = replace_once(
    p2p,
    '''                        opcode == proto::Opcode::BulkPasteEnd;''',
    '''                        opcode == proto::Opcode::BulkPasteEnd ||\n                        opcode == proto::Opcode::GlobalRevision ||\n                        opcode == proto::Opcode::SharedDigest ||\n                        opcode == proto::Opcode::GlobalSnapshotRequest ||\n                        opcode == proto::Opcode::KickPlayer;''',
    "v4 messages in ACK FIFO",
)

# Host-originated edits also advance the shared revision.
p2p = replace_once(
    p2p,
    '''    void P2PManager::send(std::vector<uint8_t> const& data, ChannelType channel) {\n        if (m_role == Role::Host) {\n            broadcast(data, channel);\n        } else if (m_role == Role::Client) {\n            sendTo(0, data, channel);\n        }\n    }''',
    '''    void P2PManager::send(std::vector<uint8_t> const& data, ChannelType channel) {\n        if (m_role == Role::Host) {\n            broadcast(data, channel);\n            if (!data.empty() && isGlobalEditOpcode(data[0])) {\n                uint32_t revision = m_globalRevision.fetch_add(1) + 1;\n                m_lastGlobalAuthor.store(0);\n                auto rev = proto::serializeGlobalRevision(revision, 0);\n                broadcast(rev, ChannelType::Reliable);\n                log::debug("P2PManager: GLOBAL REV {} author=host opcode={}", revision, static_cast<int>(data[0]));\n            }\n        } else if (m_role == Role::Client) {\n            sendTo(0, data, channel);\n        }\n    }''',
    "host global revision sequencing",
)

# Replace host relay tail: integrity/control stays point-to-point, client edits
# relay globally and then advance one common revision.
old_relay = '''        if (m_role == Role::Host) {\n            uint8_t opcode = data[0];\n            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;\n            if (\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelDigest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelManifest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelRepairRequest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::FullResyncRequest)\n            ) return;\n            ChannelType ch = ChannelType::Reliable;\n            if (opcode == static_cast<uint8_t>(proto::Opcode::CursorUpdate) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::MoveBatch)) {\n                ch = ChannelType::Unreliable;\n            }\n            relayMessage(fromPlayerId, data, len, ch);\n        }'''
new_relay = '''        if (m_role == Role::Host) {\n            uint8_t opcode = data[0];\n            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;\n            if (\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelDigest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelManifest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelRepairRequest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::FullResyncRequest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::SharedDigest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::GlobalSnapshotRequest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::GlobalRevision) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::KickPlayer)\n            ) return;\n            ChannelType ch = ChannelType::Reliable;\n            if (opcode == static_cast<uint8_t>(proto::Opcode::CursorUpdate) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::MoveBatch)) {\n                ch = ChannelType::Unreliable;\n            }\n            relayMessage(fromPlayerId, data, len, ch);\n\n            if (isGlobalEditOpcode(opcode)) {\n                uint32_t revision = m_globalRevision.fetch_add(1) + 1;\n                m_lastGlobalAuthor.store(fromPlayerId);\n                auto rev = proto::serializeGlobalRevision(revision, fromPlayerId);\n                broadcast(rev, ChannelType::Reliable);\n                log::debug("P2PManager: GLOBAL REV {} author={} opcode={}", revision, fromPlayerId, static_cast<int>(opcode));\n            }\n        }'''
p2p = replace_once(p2p, old_relay, new_relay, "global relay sequencing")

# Consume GlobalRevision and KickPlayer at the P2P control layer after envelope
# unwrap, before normal editor handlers.
control_anchor = '''        if (!protocolVerified) return;\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::ReliableAck)) {'''
control_new = '''        if (!protocolVerified) return;\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::GlobalRevision)) {\n            proto::Reader revisionReader(data + 1, len - 1);\n            auto msg = proto::deserializeGlobalRevision(revisionReader);\n            if (!revisionReader.hasError()) {\n                uint32_t current = m_globalRevision.load();\n                if (msg.revision >= current) {\n                    m_globalRevision.store(msg.revision);\n                    m_lastGlobalAuthor.store(msg.authorPlayerId);\n                    log::debug("P2PManager: GLOBAL REV applied {} author={}", msg.revision, msg.authorPlayerId);\n                }\n            }\n            return;\n        }\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::KickPlayer)) {\n            proto::Reader kickReader(data + 1, len - 1);\n            auto msg = proto::deserializeKickPlayer(kickReader);\n            if (kickReader.hasError()) return;\n            if (m_role == Role::Client && msg.targetPlayerId == m_localPlayerId) {\n                m_state.store(State::Error);\n                m_reconnectScheduled.store(false);\n                stopSignalPolling();\n                auto reason = msg.reason.empty() ? std::string("Kicked by host") : msg.reason;\n                queueInMainThread([this, reason]() {\n                    for (auto& cb : m_onError) cb(reason);\n                });\n            }\n            return;\n        }\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::ReliableAck)) {'''
p2p = replace_once(p2p, control_anchor, control_new, "v4 P2P control handling")

# Session reset of revision and kick ban-list.
p2p = replace_once(
    p2p,
    '''        m_state.store(State::Connecting);\n        m_nextPlayerId = 1;\n\n        signalingCreateRoom(playerName);''',
    '''        m_state.store(State::Connecting);\n        m_nextPlayerId = 1;\n        m_globalRevision.store(0);\n        m_lastGlobalAuthor.store(0);\n        m_kickedNames.clear();\n\n        signalingCreateRoom(playerName);''',
    "host global session reset",
)
p2p = replace_once(
    p2p,
    '''        m_state.store(State::Connecting);\n\n        signalingJoinRoom(roomCode, playerName);''',
    '''        m_state.store(State::Connecting);\n        m_globalRevision.store(0);\n        m_lastGlobalAuthor.store(0);\n\n        signalingJoinRoom(roomCode, playerName);''',
    "client global session reset",
)
p2p = replace_once(
    p2p,
    '''        m_recentDisconnectedNames.clear();\n        m_signalingRoomId.clear();''',
    '''        m_recentDisconnectedNames.clear();\n        m_kickedNames.clear();\n        m_globalRevision.store(0);\n        m_lastGlobalAuthor.store(0);\n        m_signalingRoomId.clear();''',
    "leave global session reset",
)

# Refuse a session-banned name after protocol handshake; establish transport just
# long enough to deliver the explicit kick reason instead of leaving Joining hung.
finalize_anchor = '''        log::info(\n            "P2PManager: protocol handshake complete for player {}; releasing {} pending messages",\n            pid,\n            pending.size()\n        );'''
finalize_new = '''        if (m_role == Role::Host && m_kickedNames.contains(name)) {\n            log::warn("P2PManager: rejected session-banned player {} ({})", pid, name);\n            kickPlayer(pid);\n            return;\n        }\n\n        log::info(\n            "P2PManager: protocol handshake complete for player {}; releasing {} pending messages",\n            pid,\n            pending.size()\n        );'''
p2p = replace_once(p2p, finalize_anchor, finalize_new, "session-ban handshake rejection")

# Host kick implementation. Packet is queued first; disconnect after a short
# grace interval so the reliable queue can deliver the reason.
kick_impl_anchor = '''    bool P2PManager::isPeerReconnect(int playerId) {\n        std::lock_guard lock(m_peersMutex);\n        auto it = m_peers.find(playerId);\n        return it != m_peers.end() && it->second.reconnecting;\n    }'''
kick_impl_new = '''    bool P2PManager::isPeerReconnect(int playerId) {\n        std::lock_guard lock(m_peersMutex);\n        auto it = m_peers.find(playerId);\n        return it != m_peers.end() && it->second.reconnecting;\n    }\n\n    void P2PManager::kickPlayer(int playerId) {\n        if (m_role != Role::Host || playerId <= 0) return;\n\n        std::string name;\n        {\n            std::lock_guard lock(m_peersMutex);\n            auto it = m_peers.find(playerId);\n            if (it == m_peers.end()) return;\n            name = it->second.playerName;\n            if (!name.empty()) m_kickedNames.insert(name);\n        }\n\n        auto packet = proto::serializeKickPlayer(playerId, "Kicked by host");\n        sendTo(playerId, packet, ChannelType::Reliable);\n        log::warn("P2PManager: host kicked player {} ({})", playerId, name);\n\n        std::thread([this, playerId]() {\n            std::this_thread::sleep_for(std::chrono::milliseconds(250));\n            onPeerDisconnected(playerId, false);\n        }).detach();\n    }'''
p2p = replace_once(p2p, kick_impl_anchor, kick_impl_new, "host kick implementation")
p2p_path.write_text(p2p, encoding="utf-8")


# =============================================================================
# Integrity: compare against common revision, recover from last edit author.
# Existing manifest/targeted-repair code remains as a safety fallback but is no
# longer the normal convergence path.
# =============================================================================
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

# Recovery cooldown state in anonymous namespace.
remote = replace_once(
    remote,
    '''        std::unordered_map<int, RawBulkPasteRx> s_rawBulkPasteRx;''',
    '''        std::unordered_map<int, RawBulkPasteRx> s_rawBulkPasteRx;\n        uint32_t s_lastGlobalRecoveryRevision = 0;''',
    "global recovery cooldown state",
)

shared_handler = r'''        net.on(proto::Opcode::SharedDigest, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeSharedDigest(reader);
            if (reader.hasError()) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;

            auto& p2p = P2PManager::get();
            uint32_t revision = p2p.getGlobalRevision();
            if (msg.revision != revision) {
                log::debug(
                    "RemoteActionHandler: ignoring stale shared digest player={} remoteRev={} globalRev={}",
                    playerId, msg.revision, revision
                );
                return;
            }

            auto [localCount, localHash] = computeLevelDigest();
            if (localCount == msg.objectCount && localHash == msg.hash) {
                log::debug(
                    "RemoteActionHandler: GLOBAL HASH match rev={} player={} objects={} hash={}",
                    revision, playerId, localCount, localHash
                );
                return;
            }

            log::warn(
                "RemoteActionHandler: GLOBAL HASH mismatch rev={} player={} host={}/{} remote={}/{} author={}",
                revision, playerId, localCount, localHash, msg.objectCount, msg.hash,
                p2p.getLastGlobalAuthor()
            );

            if (revision != 0 && s_lastGlobalRecoveryRevision == revision) {
                log::warn(
                    "RemoteActionHandler: divergence persists after recovery for global revision {}; waiting for next edit",
                    revision
                );
                return;
            }
            s_lastGlobalRecoveryRevision = revision;

            int author = p2p.getLastGlobalAuthor();
            if (author <= 0) {
                // Host authored the latest shared edit. Broadcast the host snapshot
                // to every guest so convergence is global, not peer-specific.
                for (auto const& participant : SessionManager::get().getPlayers()) {
                    if (participant.id == SessionManager::get().getLocalPlayerId()) continue;
                    sendFullLevelSyncTo(participant.id);
                }
                log::warn(
                    "RemoteActionHandler: GLOBAL RECOVERY rev={} source=host -> all participants",
                    revision
                );
            } else {
                // A guest authored the latest edit. Ask that author for a snapshot;
                // its SyncLevel stream reaches host and is relayed to every other guest.
                auto request = proto::serializeGlobalSnapshotRequest(revision);
                P2PManager::get().sendTo(author, request, ChannelType::Reliable);
                log::warn(
                    "RemoteActionHandler: GLOBAL RECOVERY rev={} requested snapshot from last author {}",
                    revision, author
                );
            }
        });'''
remote = replace_handler(remote, "LevelDigest", shared_handler, "replace host-authoritative digest handler")

# Last-edit author responds with a full snapshot only for the current revision.
snapshot_handler = r'''        net.on(proto::Opcode::GlobalSnapshotRequest, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeGlobalSnapshotRequest(reader);
            if (reader.hasError()) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Client || playerId != 0) return;
            if (msg.revision != P2PManager::get().getGlobalRevision()) {
                log::debug(
                    "RemoteActionHandler: ignored stale GlobalSnapshotRequest rev={} localRev={}",
                    msg.revision, P2PManager::get().getGlobalRevision()
                );
                return;
            }
            sendFullLevelSyncTo(0);
            log::warn(
                "RemoteActionHandler: sent GLOBAL SNAPSHOT rev={} to host for room-wide convergence",
                msg.revision
            );
        });

'''
anchor = '        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {'
if anchor not in remote:
    raise SystemExit("global snapshot handler anchor missing")
remote = remote.replace(anchor, snapshot_handler + anchor, 1)

# Periodic digest uses shared revision instead of host-authoritative LevelDigest.
remote = replace_once(
    remote,
    '''        auto packet = proto::serializeLevelDigest(count, hash);\n        P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);\n        log::debug(\n            "RemoteActionHandler: sent LEVEL HASH player={} objects={} hash={}",\n            playerId, count, hash\n        );''',
    '''        uint32_t revision = P2PManager::get().getGlobalRevision();\n        auto packet = proto::serializeSharedDigest(revision, count, hash);\n        P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);\n        log::debug(\n            "RemoteActionHandler: sent GLOBAL HASH rev={} player={} objects={} hash={}",\n            revision, playerId, count, hash\n        );''',
    "shared revision digest sender",
)
remote_path.write_text(remote, encoding="utf-8")


# =============================================================================
# Multiplayer popup: host-only X button beside every guest.
# =============================================================================
popup_hpp_path = Path("src/ui/MultiplayerPopup.hpp")
popup_hpp = popup_hpp_path.read_text(encoding="utf-8")
popup_hpp = replace_once(
    popup_hpp,
    '''        void onCopyCode(cocos2d::CCObject*);\n        void onPatreon(cocos2d::CCObject*);''',
    '''        void onCopyCode(cocos2d::CCObject*);\n        void onKick(cocos2d::CCObject*);\n        void onPatreon(cocos2d::CCObject*);''',
    "popup kick callback declaration",
)
popup_hpp_path.write_text(popup_hpp, encoding="utf-8")

popup_path = Path("src/ui/MultiplayerPopup.cpp")
popup = popup_path.read_text(encoding="utf-8")

old_player_loop = '''        float yOffset = center.height - 30.f;\n        for (auto& player : session.getPlayers()) {\n            auto* label = CCLabelBMFont::create(player.name.c_str(), "chatFont.fnt");\n            label->setScale(0.5f);\n            label->setPosition({center.width, yOffset});\n            label->setColor(colors[player.colorIndex % colors.size()]);\n            m_contentNode->addChild(label);\n            yOffset -= 18.f;\n        }'''
new_player_loop = '''        float yOffset = center.height - 30.f;\n        for (auto& player : session.getPlayers()) {\n            auto* label = CCLabelBMFont::create(player.name.c_str(), "chatFont.fnt");\n            label->setScale(0.5f);\n            label->setPosition({center.width, yOffset});\n            label->setColor(colors[player.colorIndex % colors.size()]);\n            m_contentNode->addChild(label);\n\n            if (\n                session.getRole() == SessionManager::Role::Host &&\n                player.id != session.getLocalPlayerId()\n            ) {\n                auto* kickMenu = CCMenu::create();\n                kickMenu->setPosition({0.f, 0.f});\n                auto* kickSprite = ButtonSprite::create(\n                    "X", 28, true, "bigFont.fnt", "GJ_button_06.png", 18.f, 0.5f\n                );\n                auto* kickButton = CCMenuItemSpriteExtra::create(\n                    kickSprite, this, menu_selector(MultiplayerPopup::onKick)\n                );\n                kickButton->setTag(player.id);\n                kickButton->setPosition({center.width + 105.f, yOffset});\n                kickMenu->addChild(kickButton);\n                m_contentNode->addChild(kickMenu);\n            }\n\n            yOffset -= 18.f;\n        }'''
popup = replace_once(popup, old_player_loop, new_player_loop, "host kick UI")

popup = replace_once(
    popup,
    '''    void MultiplayerPopup::onCopyCode(CCObject*) {\n        auto code = SessionManager::get().getRoomCode();\n        utils::clipboard::write(code);\n        Notification::create("Room code copied!", NotificationIcon::Success)->show();\n    }\n\n    void MultiplayerPopup::onPatreon(CCObject*) {''',
    '''    void MultiplayerPopup::onCopyCode(CCObject*) {\n        auto code = SessionManager::get().getRoomCode();\n        utils::clipboard::write(code);\n        Notification::create("Room code copied!", NotificationIcon::Success)->show();\n    }\n\n    void MultiplayerPopup::onKick(CCObject* sender) {\n        if (SessionManager::get().getRole() != SessionManager::Role::Host || !sender) return;\n        auto* node = typeinfo_cast<CCNode*>(sender);\n        if (!node) return;\n        int playerId = node->getTag();\n        if (playerId <= 0) return;\n        P2PManager::get().kickPlayer(playerId);\n        Notification::create("Player kicked", NotificationIcon::Info)->show();\n    }\n\n    void MultiplayerPopup::onPatreon(CCObject*) {''',
    "popup kick callback implementation",
)
popup_path.write_text(popup, encoding="utf-8")

print("Applied Protocol v4 global shared-state convergence and host kick controls")
