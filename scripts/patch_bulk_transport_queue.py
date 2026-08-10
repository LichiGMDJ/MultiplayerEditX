from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# P2PManager.hpp: per-peer paced reliable queue for bulk editor traffic.
# -----------------------------------------------------------------------------
hpp_path = Path("src/P2PManager.hpp")
hpp = hpp_path.read_text(encoding="utf-8")

hpp = replace_once(
    hpp,
    '''            std::vector<std::vector<uint8_t>> preHandshakeMessages;\n            std::vector<PendingMessage> pendingMessages;''',
    '''            std::vector<std::vector<uint8_t>> preHandshakeMessages;\n            std::vector<PendingMessage> pendingMessages;\n            std::vector<std::vector<uint8_t>> bulkReliableQueue;''',
    "bulk reliable queue field",
)

hpp = replace_once(
    hpp,
    '''        void relayMessage(int fromPlayerId, const uint8_t* data, size_t len, ChannelType channel);\n        void checkPeerReady(int playerId);''',
    '''        void relayMessage(int fromPlayerId, const uint8_t* data, size_t len, ChannelType channel);\n        void flushBulkReliableQueues();\n        void checkPeerReady(int playerId);''',
    "bulk queue flush declaration",
)

hpp_path.write_text(hpp, encoding="utf-8")


# -----------------------------------------------------------------------------
# P2PManager.cpp: queue split PlaceObjects chunks instead of blasting them all
# into libdatachannel in one call stack. Drain a few chunks every network tick
# and retain failed sends for retry on the next tick.
# -----------------------------------------------------------------------------
cpp_path = Path("src/P2PManager.cpp")
cpp = cpp_path.read_text(encoding="utf-8")

# Use a smaller sub-message target to leave SCTP/DataChannel headroom.
cpp = replace_once(
    cpp,
    '''            constexpr size_t kSafeMessageBytes = 48 * 1024;''',
    '''            constexpr size_t kSafeMessageBytes = 24 * 1024;''',
    "safe bulk packet size",
)

# Replace the large PlaceObjects sending path so each finalized sub-batch is
# queued for paced delivery. Single small messages remain immediate.
old_flush = '''                auto flushBatch = [&]() -> bool {
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
                };'''

new_flush = '''                auto flushBatch = [&]() -> bool {
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

                    peer.bulkReliableQueue.push_back(std::move(payload));
                    sentObjects += batch.size();
                    batch.clear();
                    return true;
                };'''

cpp = replace_once(cpp, old_flush, new_flush, "queue split PlaceObjects batches")

cpp = replace_once(
    cpp,
    '''                log::info(
                    "P2PManager: split oversized PlaceObjects payload: {} objects -> safe SCTP messages",
                    sentObjects
                );
                return;''',
    '''                log::info(
                    "P2PManager: queued oversized PlaceObjects payload: {} objects in {} paced SCTP messages",
                    sentObjects,
                    peer.bulkReliableQueue.size()
                );
                return;''',
    "bulk queue log",
)

# Drain queues before dispatching inbound handlers. A low per-tick budget avoids
# filling the libdatachannel buffered send queue during large editor operations.
cpp = replace_once(
    cpp,
    '''    void P2PManager::dispatchMessages() {
        if (m_dispatching) return;
        m_dispatching = true;''',
    '''    void P2PManager::dispatchMessages() {
        flushBulkReliableQueues();

        if (m_dispatching) return;
        m_dispatching = true;''',
    "bulk queue tick",
)

# Insert implementation before onPeerMessage.
anchor = '''    void P2PManager::onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len) {'''
impl = '''    void P2PManager::flushBulkReliableQueues() {
        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;

        std::lock_guard lock(m_peersMutex);
        for (auto& [playerId, peer] : m_peers) {
            if (!peer.ready || !peer.reliable || !peer.reliable->isOpen()) continue;

            size_t sentThisTick = 0;
            while (!peer.bulkReliableQueue.empty() && sentThisTick < kMaxBulkPacketsPerPeerPerTick) {
                auto const& payload = peer.bulkReliableQueue.front();
                try {
                    peer.reliable->send(
                        reinterpret_cast<const std::byte*>(payload.data()),
                        payload.size()
                    );
                    peer.bulkReliableQueue.erase(peer.bulkReliableQueue.begin());
                    ++sentThisTick;
                } catch (std::exception const& e) {
                    // Keep the packet at the front and retry on a later network tick.
                    log::warn(
                        "P2PManager: bulk send deferred for player {} ({} bytes): {}",
                        playerId,
                        payload.size(),
                        e.what()
                    );
                    break;
                } catch (...) {
                    log::warn(
                        "P2PManager: bulk send deferred for player {} ({} bytes): unknown exception",
                        playerId,
                        payload.size()
                    );
                    break;
                }
            }
        }
    }

    void P2PManager::onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len) {'''

cpp = replace_once(cpp, anchor, impl, "bulk queue implementation")
cpp_path.write_text(cpp, encoding="utf-8")

print("Patched P2PManager with paced reliable bulk queue and retry-on-send-failure")
