from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

# Small reliable editor messages used to be attempted once. If libdatachannel
# rejected that immediate send (closed/congested/error path), sendRaw() logged
# the error but the application packet was then forgotten. Bulk PlaceObjects
# already use bulkReliableQueue; extend the same retry queue to idempotent
# reliable editor messages. Delta movement packets are intentionally excluded
# because replaying a delta after ambiguous delivery could move an object twice.
old = '''            if (data.size() <= kSafeMessageBytes) {
                sendRaw(data);
                return;
            }'''

new = '''            if (data.size() <= kSafeMessageBytes) {
                bool sent = sendRaw(data);

                if (!sent && channel == ChannelType::Reliable && !data.empty()) {
                    auto opcode = static_cast<proto::Opcode>(data[0]);
                    bool retrySafe =
                        opcode == proto::Opcode::PlaceObjects ||
                        opcode == proto::Opcode::DeleteObjects ||
                        opcode == proto::Opcode::TransformObjects ||
                        opcode == proto::Opcode::ReconcileObjects ||
                        opcode == proto::Opcode::UpdateObjects ||
                        opcode == proto::Opcode::LockObjects ||
                        opcode == proto::Opcode::UpdateSettings ||
                        opcode == proto::Opcode::SyncLevelStart ||
                        opcode == proto::Opcode::SyncLevelChunk ||
                        opcode == proto::Opcode::SyncLevelEnd ||
                        opcode == proto::Opcode::PlayerJoined ||
                        opcode == proto::Opcode::PlayerLeft;

                    if (retrySafe) {
                        constexpr size_t kMaxReliableRetryQueue = 2048;
                        if (peer.bulkReliableQueue.size() < kMaxReliableRetryQueue) {
                            peer.bulkReliableQueue.push_back(data);
                            log::warn(
                                "P2PManager: queued failed reliable opcode {} for retry to player {} (queue={})",
                                static_cast<int>(data[0]),
                                playerId,
                                peer.bulkReliableQueue.size()
                            );
                        } else {
                            log::error(
                                "P2PManager: reliable retry queue full for player {}; opcode {} could not be retained",
                                playerId,
                                static_cast<int>(data[0])
                            );
                        }
                    }
                }
                return;
            }'''

text = replace_once(text, old, new, "small reliable retry path")
path.write_text(text, encoding="utf-8")
print("Patched P2PManager with retry for failed idempotent reliable editor messages")
