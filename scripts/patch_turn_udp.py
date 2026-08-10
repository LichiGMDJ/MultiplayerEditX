from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Binary protocol: add an explicit compatibility handshake for 0.5.1+.
# -----------------------------------------------------------------------------
proto_hpp_path = Path("src/BinaryProtocol.hpp")
proto_hpp = proto_hpp_path.read_text(encoding="utf-8")
proto_hpp = replace_once(
    proto_hpp,
    '''        Reconnect         = 0x34,\n\n        // Cursor (unreliable channel)''',
    '''        Reconnect         = 0x34,\n        ProtocolHello     = 0x35,\n\n        // Cursor (unreliable channel)''',
    "ProtocolHello opcode",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    std::vector<uint8_t> serializePlayerLeft(int playerId);\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    '''    std::vector<uint8_t> serializePlayerLeft(int playerId);\n    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion);\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    "ProtocolHello serializer declaration",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    struct PlayerLeftMsg {\n        int playerId;\n    };\n    PlayerLeftMsg deserializePlayerLeft(Reader& r);\n\n    struct ErrorMsg {''',
    '''    struct PlayerLeftMsg {\n        int playerId;\n    };\n    PlayerLeftMsg deserializePlayerLeft(Reader& r);\n\n    struct ProtocolHelloMsg {\n        uint32_t protocolVersion = 0;\n    };\n    ProtocolHelloMsg deserializeProtocolHello(Reader& r);\n\n    struct ErrorMsg {''',
    "ProtocolHello message declaration",
)
proto_hpp_path.write_text(proto_hpp, encoding="utf-8")

proto_cpp_path = Path("src/BinaryProtocol.cpp")
proto_cpp = proto_cpp_path.read_text(encoding="utf-8")
proto_cpp = replace_once(
    proto_cpp,
    '''    std::vector<uint8_t> serializePlayerLeft(int playerId) {\n        Writer w;\n        w.writeOpcode(Opcode::PlayerLeft);\n        w.writeVarInt(static_cast<uint32_t>(playerId));\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    '''    std::vector<uint8_t> serializePlayerLeft(int playerId) {\n        Writer w;\n        w.writeOpcode(Opcode::PlayerLeft);\n        w.writeVarInt(static_cast<uint32_t>(playerId));\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion) {\n        Writer w;\n        w.writeOpcode(Opcode::ProtocolHello);\n        w.writeVarInt(protocolVersion);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    "ProtocolHello serializer",
)
proto_cpp = replace_once(
    proto_cpp,
    '''    PlayerLeftMsg deserializePlayerLeft(Reader& r) {\n        PlayerLeftMsg msg;\n        msg.playerId = static_cast<int>(r.readVarInt());\n        return msg;\n    }\n\n    ErrorMsg deserializeError(Reader& r) {''',
    '''    PlayerLeftMsg deserializePlayerLeft(Reader& r) {\n        PlayerLeftMsg msg;\n        msg.playerId = static_cast<int>(r.readVarInt());\n        return msg;\n    }\n\n    ProtocolHelloMsg deserializeProtocolHello(Reader& r) {\n        ProtocolHelloMsg msg;\n        msg.protocolVersion = r.readVarInt();\n        return msg;\n    }\n\n    ErrorMsg deserializeError(Reader& r) {''',
    "ProtocolHello deserializer",
)
proto_cpp_path.write_text(proto_cpp, encoding="utf-8")


# Track whether each peer completed the compatibility handshake and temporarily
# retain early ordered packets until ProtocolHello is processed.
p2p_hpp_path = Path("src/P2PManager.hpp")
p2p_hpp = p2p_hpp_path.read_text(encoding="utf-8")
p2p_hpp = replace_once(
    p2p_hpp,
    '''            bool ready = false; // both channels open\n            std::vector<PendingMessage> pendingMessages;''',
    '''            bool ready = false; // both channels open\n            bool protocolVerified = false;\n            uint32_t protocolVersion = 0;\n            std::vector<std::vector<uint8_t>> preHandshakeMessages;\n            std::vector<PendingMessage> pendingMessages;''',
    "peer protocol state",
)
p2p_hpp_path.write_text(p2p_hpp, encoding="utf-8")


# -----------------------------------------------------------------------------
# P2PManager: self-hosted TURN, local-only credentials, packet safety and
# protocol compatibility gating.
# -----------------------------------------------------------------------------
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")

p2p = replace_once(
    p2p,
    '''namespace mpedit {\n\n\n\n    P2PManager& P2PManager::get() {''',
    '''namespace mpedit {\n\n    namespace {\n        constexpr uint32_t kProtocolVersion = 1;\n    }\n\n    P2PManager& P2PManager::get() {''',
    "protocol version constant",
)

p2p = replace_once(
    p2p,
    '''        rtc::IceServer turn("openrelay.metered.ca", 443, "openrelayproject", "openrelayproject", rtc::IceServer::RelayType::TurnTcp);\n        config.iceServers.push_back(turn);''',
    '''        auto turnHost = Mod::get()->getSettingValue<std::string>("turn-host");
        auto turnUsername = Mod::get()->getSettingValue<std::string>("turn-username");
        auto turnPassword = Mod::get()->getSettingValue<std::string>("turn-password");
        auto forceTurnRelay = Mod::get()->getSettingValue<bool>("force-turn-relay");

        if (turnHost.empty()) turnHost = "194.226.126.115";
        if (turnUsername.empty()) turnUsername = "mpedit";

        if (!turnPassword.empty()) {
            rtc::IceServer turn(
                turnHost,
                3478,
                turnUsername,
                turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(turn);

            if (forceTurnRelay) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            }

            log::info(
                "P2PManager: TURN/UDP configured at {}:3478 (forceRelay={})",
                turnHost,
                forceTurnRelay
            );
        } else {
            log::warn("P2PManager: TURN password is empty; TURN relay disabled for this client");
        }''',
    "TURN patch",
)

p2p = replace_once(
    p2p,
    'if (url.empty()) return "https://dewy-flea-9364.d050.deno.net";',
    'if (url.empty()) return "https://194.226.126.115:8443";',
    "signaling URL patch",
)

p2p = p2p.replace(
    'log::info("Answer SDP:\\n{}", sdp);',
    'log::debug("P2PManager: Received SDP answer ({} bytes)", sdp.size());',
)
p2p = p2p.replace(
    'log::info("Offer SDP:\\n{}", sdp);',
    'log::debug("P2PManager: Generated SDP offer ({} bytes)", sdp.size());',
)

p2p = replace_once(
    p2p,
    '''        if (!peer.ready) {
            peer.pendingMessages.push_back({data, channel});
            return;
        }''',
    '''        if (!peer.ready) {
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
        }''',
    "pending queue safety patch",
)

p2p = replace_once(
    p2p,
    '''        if (dc && dc->isOpen()) {
            dc->send(reinterpret_cast<const std::byte*>(data.data()), data.size());
        }''',
    '''        if (dc && dc->isOpen()) {
            constexpr size_t kSafeMessageBytes = 48 * 1024;

            auto sendRaw = [&](std::vector<uint8_t> const& payload) -> bool {
                try {
                    dc->send(reinterpret_cast<const std::byte*>(payload.data()), payload.size());
                    return true;
                } catch (std::exception const& e) {
                    log::error(
                        "P2PManager: data-channel send failed for player {} ({} bytes): {}",
                        playerId,
                        payload.size(),
                        e.what()
                    );
                    return false;
                } catch (...) {
                    log::error(
                        "P2PManager: data-channel send failed for player {} ({} bytes): unknown exception",
                        playerId,
                        payload.size()
                    );
                    return false;
                }
            };

            if (data.size() <= kSafeMessageBytes) {
                sendRaw(data);
                return;
            }

            if (
                channel == ChannelType::Reliable &&
                !data.empty() &&
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
                            batch.size(),
                            payload.size()
                        );
                        batch.clear();
                        return false;
                    }
                    bool ok = sendRaw(payload);
                    if (ok) sentObjects += batch.size();
                    batch.clear();
                    return ok;
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
                    "P2PManager: split oversized PlaceObjects payload: {} objects -> safe SCTP messages",
                    sentObjects
                );
                return;
            }

            log::warn(
                "P2PManager: dropping oversized unsupported message (opcode={}, {} bytes)",
                data.empty() ? -1 : static_cast<int>(data[0]),
                data.size()
            );
        }''',
    "safe data-channel send patch",
)

# Validate ProtocolHello before accepting editor traffic. Any packet that races
# ahead of the hello is buffered instead of discarded; once the hello is valid,
# buffered packets are replayed through the normal validation path.
p2p = replace_once(
    p2p,
    '''    void P2PManager::onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len) {
        if (len == 0) return;

        {
            std::lock_guard lock(m_incomingMutex);
            m_incoming.push(QueuedMessage{
                fromPlayerId,
                std::vector<uint8_t>(data, data + len)
            });
        }''',
    '''    void P2PManager::onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len) {
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
            if (helloReader.hasError() || hello.protocolVersion != kProtocolVersion) {
                log::warn(
                    "P2PManager: incompatible protocol from player {} (remote={}, local={})",
                    fromPlayerId,
                    hello.protocolVersion,
                    kProtocolVersion
                );

                auto errorMsg = proto::serializeError(
                    "Incompatible Multiplayer Edit protocol. Both players must use v0.5.1 or newer compatible builds."
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
        }''',
    "protocol and inbound packet safety patch",
)

p2p = p2p.replace(
    '''        if (m_role == Role::Host) {\n            uint8_t opcode = data[0];\n            ChannelType ch = ChannelType::Reliable;''',
    '''        if (m_role == Role::Host) {\n            uint8_t opcode = data[0];\n            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;\n            ChannelType ch = ChannelType::Reliable;''',
    1,
)

p2p = replace_once(
    p2p,
    '''                        proto::Reader handlerReader(msg.data.data() + 1, msg.data.size() - 1);
                        handler(msg.fromPlayerId, handlerReader);
                        if (m_handlers.empty()) break;''',
    '''                        proto::Reader handlerReader(msg.data.data() + 1, msg.data.size() - 1);
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
                        if (m_handlers.empty()) break;''',
    "handler exception containment patch",
)

p2p = replace_once(
    p2p,
    '''        if (!becameReady) return;

        for (auto& msg : pending) {
            sendTo(pid, msg.data, msg.channel);
        }''',
    '''        if (!becameReady) return;

        auto hello = proto::serializeProtocolHello(kProtocolVersion);
        sendTo(pid, hello, ChannelType::Reliable);

        for (auto& msg : pending) {
            sendTo(pid, msg.data, msg.channel);
        }''',
    "ProtocolHello send",
)

p2p_path.write_text(p2p, encoding="utf-8")


# -----------------------------------------------------------------------------
# EditorHooks: piggy-back player music state onto the existing cursor status.
# Existing mode/playtest parsers keep their original leading fields.
# -----------------------------------------------------------------------------
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
hooks = replace_once(
    hooks,
    '''                auto data = proto::serializeCursorUpdate(levelPos.x, levelPos.y, statusStr);
                P2PManager::get().send(std::move(data), ChannelType::Unreliable);''',
    '''                int currentSongId = 0;
                int currentAudioTrack = 0;
                if (this->m_level) {
                    currentSongId = this->m_level->m_songID;
                    currentAudioTrack = this->m_level->m_audioTrack;
                }
                statusStr += ":music:" + std::to_string(currentSongId) + ":" + std::to_string(currentAudioTrack);

                auto data = proto::serializeCursorUpdate(levelPos.x, levelPos.y, statusStr);
                P2PManager::get().send(std::move(data), ChannelType::Unreliable);''',
    "player music status patch",
)
hooks_path.write_text(hooks, encoding="utf-8")


# -----------------------------------------------------------------------------
# CursorNode: show human-readable song information when GD already has the song
# metadata cached. Fall back to the custom song ID if metadata is unavailable.
# -----------------------------------------------------------------------------
cursor_path = Path("src/ui/CursorNode.cpp")
cursor = cursor_path.read_text(encoding="utf-8")
cursor = replace_once(
    cursor,
    '''            pc.drawNode->setPosition({newX, newY});
            pc.label->setString(player.name.c_str());''',
    '''            pc.drawNode->setPosition({newX, newY});

            std::string playerLabel = player.name;
            auto musicPos = player.status.rfind(":music:");
            if (musicPos != std::string::npos) {
                auto musicData = player.status.substr(musicPos + 7);
                auto sep = musicData.find(':');
                if (sep != std::string::npos) {
                    int songId = geode::utils::numFromString<int>(musicData.substr(0, sep)).unwrapOr(0);
                    int audioTrack = geode::utils::numFromString<int>(musicData.substr(sep + 1)).unwrapOr(0);
                    if (songId > 0) {
                        std::string songText;
                        if (auto* song = LevelTools::getSongObject(songId)) {
                            std::string songName = song->m_songName;
                            std::string artistName = song->m_artistName;
                            if (!songName.empty()) {
                                songText = artistName.empty() ? songName : artistName + " - " + songName;
                            }
                        }
                        if (songText.empty()) songText = "ID " + std::to_string(songId);
                        if (songText.size() > 42) songText = songText.substr(0, 39) + "...";
                        playerLabel += "  [♪ " + songText + "]";
                    } else if (audioTrack > 0) {
                        std::string title = LevelTools::getAudioTitle(audioTrack);
                        if (title.empty()) title = "GD " + std::to_string(audioTrack);
                        playerLabel += "  [♪ " + title + "]";
                    }
                }
            }
            pc.label->setString(playerLabel.c_str());''',
    "cursor music label patch",
)
cursor_path.write_text(cursor, encoding="utf-8")

print("Applied MultiplayerEditX 0.5.1 safety, protocol, TURN and player-music patches")
