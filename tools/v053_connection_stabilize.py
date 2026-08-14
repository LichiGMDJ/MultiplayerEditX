from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block not found")
    return text.replace(old, new, 1)


p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")

# Accept valid trickle candidates even when sdpMid is empty. Some WebRTC stacks
# legitimately use an empty MID while the media section is otherwise unambiguous.
p2p = replace_once(
    p2p,
    '''                if (!cand.empty() && !mid.empty() && fromId >= 0) {
                    std::lock_guard lock(m_peersMutex);
                    auto it = m_peers.find(fromId);
                    if (it != m_peers.end() && it->second.pc) {
                        if (it->second.pc->remoteDescription().has_value()) {
                            rtc::Candidate rtcCand(cand, mid);
                            it->second.pc->addRemoteCandidate(rtcCand);
                        } else {
                            log::info("P2PManager: Remote description not set, buffering candidate from {}", fromId);
                            it->second.pendingCandidates.push_back({cand, mid});
                        }
                    }
                }''',
    '''                if (!cand.empty() && fromId >= 0) {
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
                }''',
    "relax remote candidate MID validation",
)

# Client candidate diagnostics.
p2p = replace_once(
    p2p,
    '''                    pc->onLocalCandidate([this, myId, roomCode](rtc::Candidate candidate) {
                        auto body = matjson::Value();
                        body["type"] = "candidate";
                        body["candidate"] = std::string(candidate.candidate());
                        body["mid"] = std::string(candidate.mid());
                        body["playerId"] = myId;
                        queueInMainThread([this, roomCode, body]() {
                            sendSignalingMessage(roomCode, body);
                        });
                    });''',
    '''                    pc->onLocalCandidate([this, myId, roomCode](rtc::Candidate candidate) {
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
                    });''',
    "client ICE diagnostics",
)

# Host candidate diagnostics.
p2p = replace_once(
    p2p,
    '''        pc->onLocalCandidate([this, clientPlayerId, roomCode](rtc::Candidate candidate) {
            auto body = matjson::Value();
            body["type"] = "candidate";
            body["candidate"] = std::string(candidate.candidate());
            body["mid"] = std::string(candidate.mid());
            body["targetPlayerId"] = clientPlayerId;
            queueInMainThread([this, roomCode, body]() {
                sendSignalingMessage(roomCode, body);
            });
        });''',
    '''        pc->onLocalCandidate([this, clientPlayerId, roomCode](rtc::Candidate candidate) {
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
        });''',
    "host ICE diagnostics",
)

# Log every PeerConnection state instead of only terminal states.
p2p = replace_once(
    p2p,
    '''                    pc->onStateChange([this](rtc::PeerConnection::State state) {
                        if (state == rtc::PeerConnection::State::Disconnected ||
                            state == rtc::PeerConnection::State::Failed ||
                            state == rtc::PeerConnection::State::Closed) {
                            queueInMainThread([this]() {
                                onPeerDisconnected(0, true);
                            });
                        }
                    });''',
    '''                    pc->onStateChange([this](rtc::PeerConnection::State state) {
                        log::info("P2PManager: client PeerConnection state={}", static_cast<int>(state));
                        if (state == rtc::PeerConnection::State::Disconnected ||
                            state == rtc::PeerConnection::State::Failed ||
                            state == rtc::PeerConnection::State::Closed) {
                            queueInMainThread([this]() {
                                onPeerDisconnected(0, true);
                            });
                        }
                    });''',
    "client connection state diagnostics",
)

p2p = replace_once(
    p2p,
    '''        pc->onStateChange([this, clientPlayerId](rtc::PeerConnection::State state) {
            if (state == rtc::PeerConnection::State::Disconnected ||
                state == rtc::PeerConnection::State::Failed ||
                state == rtc::PeerConnection::State::Closed) {
                queueInMainThread([this, clientPlayerId]() {
                    onPeerDisconnected(clientPlayerId, true);
                });
            }
        });

        pc->setLocalDescription();''',
    '''        pc->onStateChange([this, clientPlayerId](rtc::PeerConnection::State state) {
            log::info(
                "P2PManager: host PeerConnection state={} player={}",
                static_cast<int>(state),
                clientPlayerId
            );
            if (state == rtc::PeerConnection::State::Disconnected ||
                state == rtc::PeerConnection::State::Failed ||
                state == rtc::PeerConnection::State::Closed) {
                queueInMainThread([this, clientPlayerId]() {
                    onPeerDisconnected(clientPlayerId, true);
                });
            }
        });

        // createDataChannel() may already have triggered offer generation. Calling
        // setLocalDescription() again in HaveLocalOffer produces a libdatachannel
        // warning and can race trickle ICE callbacks. Only start negotiation when
        // the peer is still stable.
        if (pc->signalingState() == rtc::PeerConnection::SignalingState::Stable) {
            pc->setLocalDescription();
        } else {
            log::debug(
                "P2PManager: offer already generated for player {}; skipping duplicate setLocalDescription",
                clientPlayerId
            );
        }''',
    "avoid duplicate host local description",
)

# Buffered candidates must never abort answer/offer processing because one
# malformed candidate slipped through. Apply independently and retain diagnostics.
p2p = p2p.replace(
    '''                            for (auto const& pCand : it->second.pendingCandidates) {
                                it->second.pc->addRemoteCandidate(rtc::Candidate(pCand.candidate, pCand.mid));
                            }
                            it->second.pendingCandidates.clear();''',
    '''                            for (auto const& pCand : it->second.pendingCandidates) {
                                try {
                                    it->second.pc->addRemoteCandidate(rtc::Candidate(pCand.candidate, pCand.mid));
                                } catch (std::exception const& e) {
                                    log::warn("P2PManager: buffered ICE candidate rejected: {}", e.what());
                                }
                            }
                            it->second.pendingCandidates.clear();'''
)

p2p_path.write_text(p2p, encoding="utf-8")


server_path = Path("server/signaling/server.ts")
server = server_path.read_text(encoding="utf-8")

server = replace_once(
    server,
    '''  if (type === "candidate") {
    const candidate = typeof message.candidate === "string" ? message.candidate : "";
    const mid = typeof message.mid === "string" ? message.mid : "";
    if (!candidate || !mid || new TextEncoder().encode(candidate).byteLength > MAX_CANDIDATE_BYTES) {
      return "invalid ICE candidate";
    }
  }''',
    '''  if (type === "candidate") {
    const candidate = typeof message.candidate === "string" ? message.candidate : "";
    const mid = typeof message.mid === "string" ? message.mid : "";
    if (!candidate || new TextEncoder().encode(candidate).byteLength > MAX_CANDIDATE_BYTES) {
      return "invalid ICE candidate";
    }
    // sdpMid can legitimately be empty for some libdatachannel/WebRTC paths.
    // Validate its size when present, but never reject an otherwise valid ICE
    // candidate solely because MID is empty.
    if (new TextEncoder().encode(mid).byteLength > 256) {
      return "invalid ICE candidate mid";
    }
  }''',
    "relax signaling ICE MID validation",
)

# Do not trust a caller-supplied playerId. Existing routing already derives the
# sender from the bearer token; strip target-only fields in the client->host path.
server = replace_once(
    server,
    '''      } else {
        const normalized = { ...message, playerId: sender.playerId, generation: room.generation };
        enqueue(room.host, normalized);
      }

      touch(room, sender);
      return json({ ok: true });''',
    '''      } else {
        const normalized = { ...message, playerId: sender.playerId, generation: room.generation };
        delete normalized.targetPlayerId;
        enqueue(room.host, normalized);
      }

      touch(room, sender);
      return json({ ok: true });''',
    "normalize authenticated client signal",
)

server_path.write_text(server, encoding="utf-8")
print("Applied 0.5.3 connection stabilization: ICE MID compatibility, candidate safety, state diagnostics, duplicate-offer guard")
