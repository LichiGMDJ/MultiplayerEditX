from pathlib import Path


# Repair/verify the sync fastfix after the first source rewrite. This script is
# intentionally idempotent so rerunning the workflow cannot duplicate changes.
p2p_path = Path("src/P2PManager.cpp")
editor_path = Path("src/EditorHooks.cpp")
remote_path = Path("src/RemoteActionHandler.cpp")

p2p = p2p_path.read_text(encoding="utf-8")
editor = editor_path.read_text(encoding="utf-8")
remote = remote_path.read_text(encoding="utf-8")

# The first patch pass replaced through the stableIntegrityHash start marker and
# accidentally removed its declaration. Restore it exactly once when needed.
broken_hash = '''            return newObjects;
        }

            uint64_t hash = 1469598103934665603ull;'''
fixed_hash = '''            return newObjects;
        }

        std::string stableIntegrityHash(std::string const& value) {
            uint64_t hash = 1469598103934665603ull;'''

if broken_hash in remote:
    remote = remote.replace(broken_hash, fixed_hash, 1)
elif "        std::string stableIntegrityHash(std::string const& value) {" not in remote:
    raise RuntimeError("stableIntegrityHash declaration is missing in an unexpected form")

# Verify every intended fastfix is present before committing anything.
checks = [
    ("WebRTC FIFO cap", "kMaxBulkPacketsPerPeerPerTick = 8", p2p),
    ("contiguous snapshot", "queued authoritative snapshot for player", editor),
    ("fast object capture", "That old O(level-size) work dominated large sessions.", remote),
    ("authoritative placement coordinates", "obj->setPosition({objData.x, objData.y});", remote),
    ("position-aware UUID mapping", "same object ID AND nearest serialized position", remote),
    ("stable integrity hash", "std::string stableIntegrityHash(std::string const& value)", remote),
]
for label, needle, text in checks:
    if needle not in text:
        raise RuntimeError(f"missing expected sync fastfix: {label}")

remote_path.write_text(remote, encoding="utf-8")
print("sync fastfix verified and repaired")
