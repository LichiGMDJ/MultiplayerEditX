from pathlib import Path

path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")
start = text.index("    void P2PManager::createHostPeer(int clientPlayerId, std::string const& clientName) {")
end = text.index("    void P2PManager::finalizePeerHandshake(int playerId) {", start)

replacement = r'''    void P2PManager::createHostPeer(int clientPlayerId, std::string const& clientName) {
        auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig());
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

        pc->onStateChange([this, clientPlayerId](rtc::PeerConnection::State state) {
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



'''

path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print("Reordered host WebRTC negotiation callbacks before data-channel creation")
