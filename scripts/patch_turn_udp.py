from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# P2PManager: self-hosted TURN, local-only credentials, packet safety.
# -----------------------------------------------------------------------------
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")

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

# Avoid leaking ICE credentials / addressing details into normal logs.
p2p = p2p.replace(
    'log::info("Answer SDP:\\n{}", sdp);',
    'log::debug("P2PManager: Received SDP answer ({} bytes)", sdp.size());',
)
p2p = p2p.replace(
    'log::info("Offer SDP:\\n{}", sdp);',
    'log::debug("P2PManager: Generated SDP offer ({} bytes)", sdp.size());',
)

# Bound messages waiting for a peer that has not opened its data channel yet.
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

# libdatachannel throws std::invalid_argument for oversized SCTP messages. Split
# bulk PlaceObjects traffic (Object Workshop / large pastes) and contain all send
# exceptions so a third-party editor operation cannot crash Geometry Dash.
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

# Bound remote allocations and queue growth before copying untrusted peer data.
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

        if (len == 0) return;
        if (!data || len > kMaxInboundMessageBytes) {
            log::warn(
                "P2PManager: rejected inbound message from player {} ({} bytes)",
                fromPlayerId,
                len
            );
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
        }''',
    "inbound packet safety patch",
)

# A malformed peer packet or third-party editor edge case must not escape a
# message handler and terminate the game process.
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

p2p_path.write_text(p2p, encoding="utf-8")


# -----------------------------------------------------------------------------
# EditorHooks: piggy-back player music state onto the existing cursor status.
# This keeps the protocol backwards-compatible: existing mode/playtest parsers
# still read their original leading fields and ignore the appended suffix.
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
# CursorNode: show the remote player's active song next to their name.
# Custom songs use their song ID; official songs use the audio-track index.
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
                        playerLabel += "  [♪ " + std::to_string(songId) + "]";
                    } else if (audioTrack > 0) {
                        playerLabel += "  [♪ GD " + std::to_string(audioTrack) + "]";
                    }
                }
            }
            pc.label->setString(playerLabel.c_str());''',
    "cursor music label patch",
)
cursor_path.write_text(cursor, encoding="utf-8")

print("Applied MultiplayerEditX 0.5.1 safety, compatibility, TURN and player-music patches")
