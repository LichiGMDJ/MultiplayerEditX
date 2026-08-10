from pathlib import Path

path = Path("src/EditorHooks.cpp")
text = path.read_text(encoding="utf-8")

old = '''            if (session.getRole() == SessionManager::Role::Host && info.id != session.getLocalPlayerId()) {
                if (P2PManager::get().isPeerReconnect(info.id)) {
                    log::info(
                        "EditorHooks: reconnecting player {}; waiting for digest before repair/resync",
                        info.id
                    );
                } else {
                    sendChunkedSync(this, info.id);
                    log::info("EditorHooks: Sent chunked sync_level to new player {}", info.id);
                }
            }'''

new = '''            if (session.getRole() == SessionManager::Role::Host && info.id != session.getLocalPlayerId()) {
                // Always complete an authoritative initial SyncLevel after a
                // successful peer handshake. The synchronizing UI is completed
                // by SyncLevelEnd; digest/repair remains a post-connect drift
                // recovery mechanism, not a substitute for initial sync.
                bool reconnecting = P2PManager::get().isPeerReconnect(info.id);
                sendChunkedSync(this, info.id);
                log::info(
                    "EditorHooks: Sent authoritative initial sync_level to player {} (reconnect={})",
                    info.id,
                    reconnecting
                );
            }'''

if old not in text:
    raise SystemExit("authoritative initial SyncLevel anchor not found; refusing to patch")

text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("Patched reconnect/new peers to always complete authoritative initial SyncLevel")
