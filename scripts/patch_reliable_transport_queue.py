from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# P2PManager: route every reliable application packet through the paced FIFO.
# The previous transport patch only queued split oversized PlaceObjects chunks;
# small reliable packets (single triggers, deletes, updates, settings, etc.) were
# still sent immediately and could be lost from our application flow if send()
# threw while the libdatachannel buffer was under pressure.
# -----------------------------------------------------------------------------
cpp_path = Path("src/P2PManager.cpp")
cpp = cpp_path.read_text(encoding="utf-8")

cpp = replace_once(
    cpp,
    '''            if (data.size() <= kSafeMessageBytes) {
                sendRaw(data);
                return;
            }''',
    '''            if (data.size() <= kSafeMessageBytes) {
                if (channel == ChannelType::Reliable) {
                    // Keep all editor/control traffic ordered in one per-peer FIFO.
                    // The queue is drained by flushBulkReliableQueues(), which
                    // retains the front packet when DataChannel::send throws and
                    // retries it on a later network tick.
                    peer.bulkReliableQueue.push_back(data);
                } else {
                    // Cursor/playtest state is intentionally best-effort.
                    sendRaw(data);
                }
                return;
            }''',
    "queue all small reliable packets",
)

# Make the queue log reflect that it now carries all reliable traffic, not only
# split bulk placements. The function name stays unchanged to minimize patch
# surface for this release candidate.
cpp = cpp.replace(
    'P2PManager: bulk send deferred for player {} ({} bytes): {}',
    'P2PManager: reliable send deferred for player {} ({} bytes): {}',
)
cpp = cpp.replace(
    'P2PManager: bulk send deferred for player {} ({} bytes): unknown exception',
    'P2PManager: reliable send deferred for player {} ({} bytes): unknown exception',
)

cpp_path.write_text(cpp, encoding="utf-8")


# -----------------------------------------------------------------------------
# EditorHooks: keep full-level sync chunks comfortably below the 24 KiB SCTP
# application limit. The previous 30,000-byte compressed chunk plus up to 500
# UUID strings could exceed the new safe transport size and be dropped as an
# unsupported oversized SyncLevelChunk.
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

print("Patched all reliable editor traffic through paced FIFO and reduced level-sync chunk sizes")
