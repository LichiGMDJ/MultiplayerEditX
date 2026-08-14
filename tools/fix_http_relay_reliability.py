from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f'[{label}] expected block not found')
    return text.replace(old, new, 1)

hpp_path = Path('src/P2PManager.hpp')
hpp = hpp_path.read_text(encoding='utf-8')
hpp = replace_once(
    hpp,
    '''            bool connectionAnnounced = false;\n            bool httpRelay = false;\n            std::vector<PendingCandidate> pendingCandidates;''',
    '''            bool connectionAnnounced = false;\n            bool httpRelay = false;\n            bool httpRelayPostInFlight = false;\n            std::vector<PendingCandidate> pendingCandidates;''',
    'PeerInfo HTTP post state',
)
hpp = replace_once(
    hpp,
    '''        void sendHttpRelayPacket(int playerId, std::vector<uint8_t> const& data, ChannelType channel);''',
    '''        void sendHttpRelayPacket(\n            int playerId,\n            std::vector<uint8_t> const& data,\n            ChannelType channel,\n            uint32_t trackedSequence = 0\n        );''',
    'relay sender signature',
)
hpp_path.write_text(hpp, encoding='utf-8')

cpp_path = Path('src/P2PManager.cpp')
cpp = cpp_path.read_text(encoding='utf-8')
cpp = replace_once(
    cpp,
    '''        bool isGlobalEditOpcode(uint8_t raw) {\n            auto opcode = static_cast<proto::Opcode>(raw);\n            return\n                opcode == proto::Opcode::PlaceObjects ||\n                opcode == proto::Opcode::DeleteObjects ||\n                opcode == proto::Opcode::MoveObjects ||\n                opcode == proto::Opcode::TransformObjects ||\n                opcode == proto::Opcode::ReconcileObjects ||\n                opcode == proto::Opcode::UpdateObjects ||\n                opcode == proto::Opcode::UpdateSettings ||\n                opcode == proto::Opcode::BulkPasteEnd;\n        }\n''',
    '''        bool isGlobalEditOpcode(uint8_t raw) {\n            auto opcode = static_cast<proto::Opcode>(raw);\n            return\n                opcode == proto::Opcode::PlaceObjects ||\n                opcode == proto::Opcode::DeleteObjects ||\n                opcode == proto::Opcode::MoveObjects ||\n                opcode == proto::Opcode::TransformObjects ||\n                opcode == proto::Opcode::ReconcileObjects ||\n                opcode == proto::Opcode::UpdateObjects ||\n                opcode == proto::Opcode::UpdateSettings ||\n                opcode == proto::Opcode::BulkPasteEnd;\n        }\n\n        bool isOrderedReliableOpcode(uint8_t raw) {\n            auto opcode = static_cast<proto::Opcode>(raw);\n            return\n                opcode == proto::Opcode::PlaceObjects ||\n                opcode == proto::Opcode::DeleteObjects ||\n                opcode == proto::Opcode::MoveObjects ||\n                opcode == proto::Opcode::MoveBatch ||\n                opcode == proto::Opcode::TransformObjects ||\n                opcode == proto::Opcode::ReconcileObjects ||\n                opcode == proto::Opcode::UpdateObjects ||\n                opcode == proto::Opcode::LockObjects ||\n                opcode == proto::Opcode::UpdateSettings ||\n                opcode == proto::Opcode::SyncLevelStart ||\n                opcode == proto::Opcode::SyncLevelChunk ||\n                opcode == proto::Opcode::SyncLevelEnd ||\n                opcode == proto::Opcode::LevelDigest ||\n                opcode == proto::Opcode::LevelManifest ||\n                opcode == proto::Opcode::LevelRepairRequest ||\n                opcode == proto::Opcode::FullResyncRequest ||\n                opcode == proto::Opcode::BulkPasteStart ||\n                opcode == proto::Opcode::BulkPasteChunk ||\n                opcode == proto::Opcode::BulkPasteEnd ||\n                opcode == proto::Opcode::GlobalRevision ||\n                opcode == proto::Opcode::SharedDigest ||\n                opcode == proto::Opcode::GlobalSnapshotRequest ||\n                opcode == proto::Opcode::KickPlayer ||\n                opcode == proto::Opcode::MusicChanged ||\n                opcode == proto::Opcode::RoomSettingsChanged;\n        }\n''',
    'ordered reliable helper',
)
start = cpp.index('    void P2PManager::sendTo(int playerId, std::vector<uint8_t> const& data, ChannelType channel) {')
end = cpp.index('\n    void P2PManager::broadcast(', start)
new_send_to = r'''    void P2PManager::sendTo(int playerId, std::vector<uint8_t> const& data, ChannelType channel) {
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
'''
cpp = cpp[:start] + new_send_to + cpp[end:]

start = cpp.index('    void P2PManager::flushBulkReliableQueues() {')
end = cpp.index('\n    void P2PManager::onPeerMessage(', start)
new_flush = r'''    void P2PManager::flushBulkReliableQueues() {
        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;
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
'''
cpp = cpp[:start] + new_flush + cpp[end:]

old_sender_start = cpp.index('    void P2PManager::sendHttpRelayPacket(')
old_sender_end = cpp.index('\n    void P2PManager::handleHttpRelayMessages(', old_sender_start)
new_sender = r'''    void P2PManager::sendHttpRelayPacket(
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
'''
cpp = cpp[:old_sender_start] + new_sender + cpp[old_sender_end:]
cpp_path.write_text(cpp, encoding='utf-8')

verify_path = Path('tools/verify_upstream050_integration.py')
verify = verify_path.read_text(encoding='utf-8')
anchor = "assert 'checkPeerReady(playerId);' in p2p\n"
addition = """assert 'httpRelayPostInFlight' in p2p\nassert 'isOrderedReliableOpcode' in p2p\nassert 'HTTP relay accepted reliable sequence' in p2p\nassert 'Preserve HTTP application ordering' in p2p\n"""
if addition.strip() not in verify:
    verify = replace_once(verify, anchor, anchor + addition, 'verifier relay reliability')
verify_path.write_text(verify, encoding='utf-8')

print('HTTP relay ordered reliability fix applied')
