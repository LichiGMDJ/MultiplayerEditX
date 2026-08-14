from pathlib import Path

cpp_path = Path('src/P2PManager.cpp')
hpp_path = Path('src/P2PManager.hpp')
server_path = Path('server/signaling/server.ts')

cpp = cpp_path.read_text(encoding='utf-8')
hpp = hpp_path.read_text(encoding='utf-8')
server = server_path.read_text(encoding='utf-8')

# ---- C++ helpers ---------------------------------------------------------
needle = '''        bool isGlobalEditOpcode(uint8_t raw) {
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
'''
replacement = needle + '''
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
'''
if needle not in cpp:
    raise SystemExit('helper insertion point missing')
cpp = cpp.replace(needle, replacement, 1)

# Remove unsupported compatibility TURN/TCP. Direct/STUN remains primary; custom TURN/UDP remains optional.
old_config = '''        // 0.5.2 always exposed this TURN/TCP relay to ICE. Restoring it as a
        // compatibility fallback reproduces the old zero-configuration behavior:
        // direct/STUN candidates are still preferred, but restrictive NAT/CGNAT or
        // blocked UDP can transparently fall back to TURN over TCP/443.
        rtc::IceServer compatibilityTurn(
            "openrelay.metered.ca", 443,
            "openrelayproject", "openrelayproject",
            rtc::IceServer::RelayType::TurnTcp
        );
        config.iceServers.push_back(compatibilityTurn);

        if (network.forceTurnRelay || forceRelay) {
            config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            if (forceRelay && !network.forceTurnRelay) {
                log::warn("P2PManager: direct/STUN negotiation failed; retrying with relay-only ICE");
            } else {
                log::warn("P2PManager: Force TURN diagnostic mode enabled");
            }
        } else if (customTurnAvailable) {
            log::info(
                "P2PManager: ICE auto mode: direct/STUN preferred, custom TURN/UDP + compatibility TURN/TCP fallback available"
            );
        } else {
            log::info(
                "P2PManager: ICE auto mode: direct/STUN preferred, compatibility TURN/TCP fallback available"
            );
        }
'''
new_config = '''        if (network.forceTurnRelay || forceRelay) {
            if (customTurnAvailable) {
                config.iceTransportPolicy = rtc::TransportPolicy::Relay;
                if (forceRelay && !network.forceTurnRelay) {
                    log::warn("P2PManager: direct/STUN negotiation failed; retrying with configured TURN/UDP");
                } else {
                    log::warn("P2PManager: Force TURN diagnostic mode enabled");
                }
            } else {
                log::warn("P2PManager: relay-only ICE requested but custom TURN is not configured; HTTP relay remains available");
            }
        } else if (customTurnAvailable) {
            log::info("P2PManager: ICE auto mode: direct/STUN preferred, custom TURN/UDP fallback available");
        } else {
            log::info("P2PManager: ICE direct/STUN mode; HTTP relay fallback available");
        }
'''
if old_config not in cpp:
    raise SystemExit('legacy compatibility TURN block missing')
cpp = cpp.replace(old_config, new_config, 1)

# Relay transport bypass in sendTo, before DataChannel selection.
needle = '''        auto& dc = (channel == ChannelType::Reliable) ? peer.reliable : peer.unreliable;

        if (dc && dc->isOpen()) {
'''
replacement = '''        if (peer.httpRelay) {
            sendHttpRelayPacket(playerId, data, channel);
            return;
        }

        auto& dc = (channel == ChannelType::Reliable) ? peer.reliable : peer.unreliable;

        if (dc && dc->isOpen()) {
'''
if needle not in cpp:
    raise SystemExit('sendTo insertion point missing')
cpp = cpp.replace(needle, replacement, 1)

# Start relay polling for host after signaling polling.
needle = '''                    startSignalPolling(roomCode, "host", 0);
'''
replacement = '''                    startSignalPolling(roomCode, "host", 0);
                    startHttpRelayPolling(roomCode);
'''
if needle not in cpp:
    raise SystemExit('host polling insertion point missing')
cpp = cpp.replace(needle, replacement, 1)

# Start relay polling and fallback timer for client.
needle = '''                    startSignalPolling(roomCode, "client", m_localPlayerId);

                } else if (res.code() == 404) {
'''
replacement = '''                    startSignalPolling(roomCode, "client", m_localPlayerId);
                    startHttpRelayPolling(roomCode);
                    scheduleHttpRelayFallback(0);

                } else if (res.code() == 404) {
'''
if needle not in cpp:
    raise SystemExit('client polling insertion point missing')
cpp = cpp.replace(needle, replacement, 1)

# Ignore WebRTC failure once HTTP relay owns the peer.
old = '''                            if (!currentPeer) return; // stale Closed/Failed callback

                            auto network = net::NetworkConfig::load();
'''
new = '''                            if (!currentPeer) return; // stale Closed/Failed callback
                            {
                                std::lock_guard lock(m_peersMutex);
                                auto it = m_peers.find(0);
                                if (it != m_peers.end() && it->second.httpRelay) {
                                    log::debug("P2PManager: ignoring WebRTC state change after HTTP relay takeover");
                                    return;
                                }
                            }

                            auto network = net::NetworkConfig::load();
'''
if old not in cpp:
    raise SystemExit('client failure guard insertion point missing')
cpp = cpp.replace(old, new, 1)

# Host WebRTC callback must not remove an HTTP-relayed peer.
old = '''                queueInMainThread([this, clientPlayerId]() {
                    onPeerDisconnected(clientPlayerId, true);
                });
'''
new = '''                queueInMainThread([this, clientPlayerId]() {
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
'''
if old not in cpp:
    raise SystemExit('host failure guard insertion point missing')
cpp = cpp.replace(old, new, 1)

# checkPeerReady understands relay peers.
old = '''            bool reliableOpen = peer.reliable && peer.reliable->isOpen();
            bool unreliableOpen = peer.unreliable && peer.unreliable->isOpen();

            if (reliableOpen && unreliableOpen && !peer.ready) {
'''
new = '''            bool reliableOpen = peer.reliable && peer.reliable->isOpen();
            bool unreliableOpen = peer.unreliable && peer.unreliable->isOpen();
            bool transportOpen = peer.httpRelay || (reliableOpen && unreliableOpen);

            if (transportOpen && !peer.ready) {
'''
if old not in cpp:
    raise SystemExit('checkPeerReady block missing')
cpp = cpp.replace(old, new, 1)

# Stop relay polling on leave. Locate stopSignalPolling inside leaveSession.
needle = '''        stopSignalPolling();
        m_signalingListener.cancel();
'''
replacement = '''        stopSignalPolling();
        stopHttpRelayPolling();
        m_signalingListener.cancel();
'''
if needle not in cpp:
    raise SystemExit('leaveSession stop insertion point missing')
cpp = cpp.replace(needle, replacement, 1)

# Insert HTTP relay implementation before requestHostMigration.
marker = '''    void P2PManager::requestHostMigration() {
'''
relay_impl = r'''    void P2PManager::startHttpRelayPolling(std::string const& code) {
        m_httpRelayPollingActive.store(true);
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
        req.timeout(std::chrono::seconds(30));
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
                } else {
                    log::warn("P2PManager: HTTP relay poll returned {}", res.code());
                }

                if (m_httpRelayPollingActive.load()) pollHttpRelayOnce(code);
            }
        );
    }

    void P2PManager::sendHttpRelayPacket(int playerId, std::vector<uint8_t> const& data, ChannelType channel) {
        if (data.empty() || m_signalingToken.empty()) return;
        constexpr size_t kMaxRelayPacketBytes = 48 * 1024;
        if (data.size() > kMaxRelayPacketBytes) {
            log::warn("P2PManager: HTTP relay packet too large ({} bytes)", data.size());
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
        async::spawn(req.post(url));
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
                    it->second.ready = true;
                    newlyRelayed = true;
                }
            }
            if (newlyRelayed) {
                log::warn("P2PManager: peer {} switched to HTTP relay transport", fromId);
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
            it->second.ready = true;
            activate = true;
        }
        if (!activate) return;

        log::warn("P2PManager: WebRTC not ready; activating HTTP relay transport for player {}", playerId);
        auto hello = proto::serializeProtocolHello(net::kCurrentProtocol, net::kLocalCapabilities);
        sendTo(playerId, hello, ChannelType::Reliable);
    }

    void P2PManager::scheduleHttpRelayFallback(int playerId) {
        std::thread([this, playerId]() {
            std::this_thread::sleep_for(std::chrono::seconds(8));
            queueInMainThread([this, playerId]() {
                if (m_state.load() == State::Disconnected || m_state.load() == State::Error) return;
                activateHttpRelayForPeer(playerId);
            });
        }).detach();
    }

'''
if marker not in cpp:
    raise SystemExit('HTTP relay implementation marker missing')
cpp = cpp.replace(marker, relay_impl + marker, 1)

# ---- Header --------------------------------------------------------------
old = '''            bool connectionAnnounced = false;
            std::vector<PendingCandidate> pendingCandidates;
'''
new = '''            bool connectionAnnounced = false;
            bool httpRelay = false;
            std::vector<PendingCandidate> pendingCandidates;
'''
if old not in hpp:
    raise SystemExit('PeerInfo header insertion point missing')
hpp = hpp.replace(old, new, 1)

old = '''        void stopSignalPolling();
        void sendSignalingMessage(std::string const& roomCode, matjson::Value const& msg);
        void handleSignalingMessages(matjson::Value const& messages);
'''
new = '''        void stopSignalPolling();
        void sendSignalingMessage(std::string const& roomCode, matjson::Value const& msg);
        void handleSignalingMessages(matjson::Value const& messages);
        void startHttpRelayPolling(std::string const& code);
        void pollHttpRelayOnce(std::string const& code);
        void stopHttpRelayPolling();
        void sendHttpRelayPacket(int playerId, std::vector<uint8_t> const& data, ChannelType channel);
        void handleHttpRelayMessages(matjson::Value const& messages);
        void activateHttpRelayForPeer(int playerId);
        void scheduleHttpRelayFallback(int playerId);
'''
if old not in hpp:
    raise SystemExit('header method insertion point missing')
hpp = hpp.replace(old, new, 1)

old = '''        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalPollListener; // long-poll loop
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_migrationListener;
        std::atomic<bool> m_signalingActive{false};
'''
new = '''        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalPollListener; // signaling long-poll loop
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_httpRelayPollListener;
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_migrationListener;
        std::atomic<bool> m_signalingActive{false};
        std::atomic<bool> m_httpRelayPollingActive{false};
'''
if old not in hpp:
    raise SystemExit('header listener insertion point missing')
hpp = hpp.replace(old, new, 1)

# ---- Deno server ---------------------------------------------------------
server = server.replace('''type SignalMessage = Record<string, unknown>;\n\n''', '''type SignalMessage = Record<string, unknown>;\n\ntype RelayMessage = {\n  fromPlayerId: number;\n  channel: "reliable" | "unreliable";\n  payload: string;\n};\n\n''', 1)
server = server.replace('''  queue: SignalMessage[];\n};''', '''  queue: SignalMessage[];\n  relayQueue: RelayMessage[];\n};''', 1)
server = server.replace('''const MAX_QUEUE_MESSAGES = 128;''', '''const MAX_QUEUE_MESSAGES = 128;\nconst MAX_RELAY_QUEUE_MESSAGES = 512;\nconst MAX_RELAY_PAYLOAD_HEX = 96 * 1024;''', 1)

# Every Participant initializer gets relayQueue.
server = server.replace('''      queue: [],\n      lastSeenAt: now(),''', '''      queue: [],\n      relayQueue: [],\n      lastSeenAt: now(),''', 1)
server = server.replace('''      queue: [],\n    };\n    const room: Room''', '''      queue: [],\n      relayQueue: [],\n    };\n    const room: Room''', 1)
server = server.replace('''        queue: [],\n      };\n      room.clients.set''', '''        queue: [],\n        relayQueue: [],\n      };\n      room.clients.set''', 1)

# Migration retained clients and promoted host relay queues.
server = server.replace('''    client.queue = [];\n  }''', '''    client.queue = [];\n    client.relayQueue = [];\n  }''', 1)

# Relay queue helper and long poll.
marker = '''function removeExpiredRooms(): void {'''
insert = '''function enqueueRelay(participant: Participant, message: RelayMessage): void {\n  participant.relayQueue.push(message);\n  if (participant.relayQueue.length > MAX_RELAY_QUEUE_MESSAGES) {\n    participant.relayQueue.splice(0, participant.relayQueue.length - MAX_RELAY_QUEUE_MESSAGES);\n  }\n}\n\nasync function longPollRelay(participant: Participant): Promise<Response> {\n  const deadline = now() + LONG_POLL_MS;\n  while (participant.relayQueue.length === 0 && now() < deadline) {\n    await new Promise((resolve) => setTimeout(resolve, 100));\n  }\n  const messages = participant.relayQueue.splice(0, participant.relayQueue.length);\n  return json(messages);\n}\n\n'''
if marker not in server:
    raise SystemExit('server helper marker missing')
server = server.replace(marker, insert + marker, 1)

# Advertise transport.
server = server.replace('''      rooms: rooms.size,\n    });''', '''      rooms: rooms.size,\n      transports: ["webrtc", "http-relay-v1"],\n    });''', 1)
server = server.replace('''      signalingApi: 2,\n    }, 201);''', '''      signalingApi: 2,\n      relayApi: 1,\n    }, 201);''', 1)
server = server.replace('''        signalingApi: 2,\n      });''', '''        signalingApi: 2,\n        relayApi: 1,\n      });''', 1)

# Insert /relay before /signal GET route.
marker = '''    if (req.method === "GET" && parts.length === 3 && parts[2] === "signal") {'''
relay_server = '''    if (req.method === "GET" && parts.length === 3 && parts[2] === "relay") {\n      const token = bearerToken(req);\n      const participant = findParticipant(room, token);\n      if (!participant) return json({ error: "unauthorized" }, 401);\n      touch(room, participant);\n      return await longPollRelay(participant);\n    }\n\n    if (req.method === "POST" && parts.length === 3 && parts[2] === "relay") {\n      const token = bearerToken(req);\n      const sender = findParticipant(room, token);\n      if (!sender) return json({ error: "unauthorized" }, 401);\n\n      const body = await readJson(req);\n      if (!body) return json({ error: "invalid request body" }, 400);\n      const payload = typeof body.payload === "string" ? body.payload : "";\n      const channel = body.channel === "unreliable" ? "unreliable" : "reliable";\n      if (!payload || payload.length > MAX_RELAY_PAYLOAD_HEX || (payload.length % 2) !== 0 || !/^[0-9a-fA-F]+$/.test(payload)) {\n        return json({ error: "invalid relay payload" }, 400);\n      }\n\n      const isHost = sender.token === room.host.token;\n      if (isHost) {\n        const targetId = Number(body.targetPlayerId ?? -1);\n        const target = room.clients.get(targetId);\n        if (!target) return json({ error: "target client not found" }, 404);\n        enqueueRelay(target, { fromPlayerId: 0, channel, payload });\n      } else {\n        enqueueRelay(room.host, { fromPlayerId: sender.playerId, channel, payload });\n      }\n\n      touch(room, sender);\n      return json({ ok: true });\n    }\n\n'''
if marker not in server:
    raise SystemExit('server relay route marker missing')
server = server.replace(marker, relay_server + marker, 1)

cpp_path.write_text(cpp, encoding='utf-8')
hpp_path.write_text(hpp, encoding='utf-8')
server_path.write_text(server, encoding='utf-8')
print('HTTP relay fallback patch applied')
