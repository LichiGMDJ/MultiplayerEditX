from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# P2PManager: route all level-mutating reliable application packets through one
# ordered per-peer FIFO. ProtocolHello/control packets stay immediate because
# the FIFO is drained from the active editor network tick and must not gate the
# connection handshake before the editor exists.
# -----------------------------------------------------------------------------
cpp_path = Path("src/P2PManager.cpp")
cpp = cpp_path.read_text(encoding="utf-8")

# This is the block produced by patch_reliable_editor_retry.py, which runs just
# before this patch in CI. Replace the send-first/retry-after-failure behavior
# with queue-first delivery for editor state packets. This prevents a later
# packet (for example Pulse Trigger) from overtaking an earlier failed packet
# (for example Move Trigger).
old = '''            if (data.size() <= kSafeMessageBytes) {
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

new = '''            if (data.size() <= kSafeMessageBytes) {
                if (channel == ChannelType::Reliable && !data.empty()) {
                    auto opcode = static_cast<proto::Opcode>(data[0]);
                    bool orderedEditorTraffic =
                        opcode == proto::Opcode::PlaceObjects ||
                        opcode == proto::Opcode::DeleteObjects ||
                        opcode == proto::Opcode::MoveObjects ||
                        opcode == proto::Opcode::MoveBatch ||
                        opcode == proto::Opcode::TransformObjects ||
                        opcode == proto::Opcode::ReconcileObjects ||
                        opcode == proto::Opcode::UpdateObjects ||
                        opcode == proto::Opcode::LockObjects ||
                        opcode == proto::Opcode::UpdateSettings ||
                        opcode == proto::Opcode::SyncLevelStart ||
                        opcode == proto::Opcode::SyncLevelChunk ||
                        opcode == proto::Opcode::SyncLevelEnd;

                    if (orderedEditorTraffic) {
                        constexpr size_t kMaxOrderedReliableQueue = 8192;
                        if (peer.bulkReliableQueue.size() < kMaxOrderedReliableQueue) {
                            peer.bulkReliableQueue.push_back(data);
                            log::debug(
                                "P2PManager: queued reliable editor opcode {} for ordered delivery to player {} (queue={})",
                                static_cast<int>(data[0]),
                                playerId,
                                peer.bulkReliableQueue.size()
                            );
                        } else {
                            log::error(
                                "P2PManager: ordered reliable queue full for player {}; opcode {} could not be retained",
                                playerId,
                                static_cast<int>(data[0])
                            );
                        }
                        return;
                    }
                }

                // Handshake/session-control traffic and unreliable cursor state
                // remain immediate. They are low-volume and must work before an
                // editor network tick exists.
                sendRaw(data);
                return;
            }'''

cpp = replace_once(cpp, old, new, "strict ordered reliable editor queue")

# Rename retry log wording because the same queue now carries all ordered editor
# state, including split bulk placements.
cpp = cpp.replace(
    'P2PManager: bulk send deferred for player {} ({} bytes): {}',
    'P2PManager: reliable FIFO send deferred for player {} ({} bytes): {}',
)
cpp = cpp.replace(
    'P2PManager: bulk send deferred for player {} ({} bytes): unknown exception',
    'P2PManager: reliable FIFO send deferred for player {} ({} bytes): unknown exception',
)

cpp_path.write_text(cpp, encoding="utf-8")


# -----------------------------------------------------------------------------
# EditorHooks: keep full-level sync chunks comfortably below the 24 KiB SCTP
# application target. 30,000 bytes of compressed data plus up to 500 UUIDs can
# exceed that limit even before protocol framing.
# -----------------------------------------------------------------------------
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

hooks = replace_once(
    hooks,
    '''        constexpr size_t MAX_CHUNK_BYTES = 30000;
        constexpr size_t MAX_UUIDS_PER_CHUNK = 500;''',
    '''        // Leave headroom for opcode/index/vector/string framing so every
        // SyncLevelChunk stays below P2PManager's 24 KiB safe message target.
        constexpr size_t MAX_CHUNK_BYTES = 12000;
        constexpr size_t MAX_UUIDS_PER_CHUNK = 250;''',
    "safe full-level sync chunk size",
)

hooks_path.write_text(hooks, encoding="utf-8")

print("Patched level-mutating reliable traffic through strict FIFO and reduced level-sync chunk sizes")
