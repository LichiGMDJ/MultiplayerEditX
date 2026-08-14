from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing block: {label}")
    return text.replace(old, new, 1)

# ---- P2PManager.hpp -------------------------------------------------------
hpp = Path("src/P2PManager.hpp")
text = hpp.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        rtc::Configuration makeRtcConfig();\n",
    "        rtc::Configuration makeRtcConfig(bool forceRelay = false);\n",
    "makeRtcConfig declaration",
)
text = replace_once(
    text,
    "        std::atomic<bool> m_reconnectScheduled{false};\n        int m_reconnectAttempts = 0;\n",
    "        std::atomic<bool> m_reconnectScheduled{false};\n        std::atomic<bool> m_forceRelayNextJoin{false};\n        int m_reconnectAttempts = 0;\n",
    "relay fallback member",
)
hpp.write_text(text, encoding="utf-8")

# ---- P2PManager.cpp -------------------------------------------------------
cpp = Path("src/P2PManager.cpp")
text = cpp.read_text(encoding="utf-8")

text = replace_once(
    text,
    "    rtc::Configuration P2PManager::makeRtcConfig() {\n",
    "    rtc::Configuration P2PManager::makeRtcConfig(bool forceRelay) {\n",
    "makeRtcConfig definition",
)
text = replace_once(
    text,
    "            if (network.forceTurnRelay) {\n                config.iceTransportPolicy = rtc::TransportPolicy::Relay;\n                log::warn(\"P2PManager: Force TURN diagnostic mode enabled\");\n            } else {\n                log::info(\"P2PManager: ICE auto mode: direct/STUN preferred, TURN fallback available\");\n            }\n",
    "            if (network.forceTurnRelay || forceRelay) {\n                config.iceTransportPolicy = rtc::TransportPolicy::Relay;\n                if (forceRelay && !network.forceTurnRelay) {\n                    log::warn(\"P2PManager: direct/STUN negotiation failed; retrying with TURN relay only\");\n                } else {\n                    log::warn(\"P2PManager: Force TURN diagnostic mode enabled\");\n                }\n            } else {\n                log::info(\"P2PManager: ICE auto mode: direct/STUN preferred, TURN fallback available\");\n            }\n",
    "relay policy",
)

# Poll auth failures must not spin in a tight loop. 401/403 means the current
# signaling identity is unusable; clients reconnect and hosts surface an error.
old_poll = '''                if (res.ok()) {
                    auto json = res.json().unwrapOr(matjson::Value());
                    handleSignalingMessages(json);
                } else {
                    log::warn("P2PManager: Signal poll returned {}", res.code());
                }

                if (m_signalingActive.load()) {
                    pollSignalOnce(code, role, playerId);
                }
'''
new_poll = '''                if (res.ok()) {
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
'''
text = replace_once(text, old_poll, new_poll, "poll auth handling")

# libdatachannel already creates the answer after applying a remote offer. The
# explicit call caused two onLocalDescription callbacks on Android.
text = replace_once(
    text,
    '''                            it->second.pendingCandidates.clear();

                            it->second.pc->setLocalDescription();
''',
    '''                            it->second.pendingCandidates.clear();

                            // libdatachannel generates the answer after a remote offer.
                            // Do not force a second local description here; Android was
                            // producing duplicate SDP answers from this path.
''',
    "duplicate client answer",
)

# Fresh sessions must never inherit an internal relay retry from an older one.
text = replace_once(
    text,
    '''        m_state.store(State::Connecting);
        m_globalRevision.store(0);
        m_lastGlobalAuthor.store(0);

        signalingJoinRoom(roomCode, playerName);
''',
    '''        m_state.store(State::Connecting);
        m_globalRevision.store(0);
        m_lastGlobalAuthor.store(0);
        m_forceRelayNextJoin.store(false);

        signalingJoinRoom(roomCode, playerName);
''',
    "fresh join relay reset",
)

# Consume relay-only retry only after /join actually succeeds.
text = replace_once(
    text,
    '''                    log::info("P2PManager: Joined room {} as player {}", roomCode, m_localPlayerId);

                    auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig());
''',
    '''                    log::info("P2PManager: Joined room {} as player {}", roomCode, m_localPlayerId);

                    bool relayRetry = m_forceRelayNextJoin.exchange(false);
                    auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig(relayRetry));
''',
    "client relay retry config",
)

# Initial ICE failure is not a host-loss event. First retry the same room using
# TURN relay-only when TURN is configured. Also bind the callback to the exact
# PeerConnection so stale Closed events from an old attempt cannot kill a new one.
old_client_state = '''                    pc->onStateChange([this](rtc::PeerConnection::State state) {
                        log::info("P2PManager: client PeerConnection state={}", static_cast<int>(state));
                        if (state == rtc::PeerConnection::State::Disconnected ||
                            state == rtc::PeerConnection::State::Failed ||
                            state == rtc::PeerConnection::State::Closed) {
                            queueInMainThread([this]() {
                                onPeerDisconnected(0, true);
                            });
                        }
                    });
'''
new_client_state = '''                    pc->onStateChange([this, pc, relayRetry](rtc::PeerConnection::State state) {
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

                            auto network = net::NetworkConfig::load();
                            if (!transportReady && !relayRetry && !network.forceTurnRelay && network.hasTurn()) {
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
'''
text = replace_once(text, old_client_state, new_client_state, "client ICE recovery")

# Duplicate Failed -> Closed callbacks currently invoke disconnect handling twice.
old_disconnect = '''    void P2PManager::onPeerDisconnected(int playerId, bool unexpected) {
        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it != m_peers.end()) {
                if (unexpected && m_role == Role::Host && !it->second.playerName.empty()) {
                    m_recentDisconnectedNames[it->second.playerName] = reliabilityNowMs();
                }
                if (it->second.pc) it->second.pc->close();
                m_peers.erase(it);
            }
        }

        log::info("P2PManager: Player {} disconnected (unexpected={})", playerId, unexpected);
'''
new_disconnect = '''    void P2PManager::onPeerDisconnected(int playerId, bool unexpected) {
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
'''
text = replace_once(text, old_disconnect, new_disconnect, "duplicate disconnect guard")

# Host-side stale PeerConnection callbacks should likewise be ignored by the
# disconnect guard; capture pc so future diagnostics identify the exact attempt.
text = replace_once(
    text,
    '''        pc->onStateChange([this, clientPlayerId](rtc::PeerConnection::State state) {
''',
    '''        pc->onStateChange([this, pc, clientPlayerId](rtc::PeerConnection::State state) {
''',
    "host state capture",
)

# Explicit normal-mode argument for clarity after signature change.
text = text.replace(
    "auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig());",
    "auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig(false));",
)

cpp.write_text(text, encoding="utf-8")

# ---- signaling server -----------------------------------------------------
server = Path("server/signaling/server.ts")
text = server.read_text(encoding="utf-8")
old_role = '''      const requestedRole = url.searchParams.get("role") ?? "";
      if (requestedRole === "host" && participant.token !== room.host.token) {
        return json({ error: "host token required" }, 403);
      }
      if (requestedRole === "client" && participant.token === room.host.token) {
        return json({ error: "client token required" }, 403);
      }

      touch(room, participant);
'''
new_role = '''      // The bearer token is the authoritative signaling identity. Do not reject
      // an authenticated long-poll solely because the client's cached role is
      // stale during host migration or reconnect; that created false 403 loops.
      // Routing still uses the participant queue bound to this token.
      touch(room, participant);
'''
text = replace_once(text, old_role, new_role, "role-based signal 403")
server.write_text(text, encoding="utf-8")
