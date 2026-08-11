from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.2 stability: {label}: expected source block not found")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# EditorHooks: integrity scans are diagnostics/targeted repair, not a constant
# full-level rewrite. Also apply a deferred full sync only after playtest ended.
# -----------------------------------------------------------------------------
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

hooks = replace_once(
    hooks,
    "(m_fields->m_forceIntegrityCheck || m_fields->m_integrityCheckTimer >= 3.0f)",
    "(m_fields->m_forceIntegrityCheck || m_fields->m_integrityCheckTimer >= 20.0f)",
    "integrity interval",
)

integrity_anchor = '''        // Periodic integrity verification. The host is authoritative; clients
        // send a stable UUID/saveString digest and receive targeted repair only
        // when the state differs. Reconnect forces an immediate digest.'''

deferred_apply = '''        // v0.5.2 safety: a full snapshot received while playtesting is kept
        // pending. Applying it while PlayerObject is traversing collision objects
        // can invalidate CCNodes and crash inside collidedWithObjectInternal.
        if (
            this->m_playbackMode == PlaybackMode::Not &&
            handler.hasPendingSync() &&
            handler.isInitialSyncCompleted() &&
            !handler.isProcessingRemote()
        ) {
            log::info("EditorHooks: applying deferred SyncLevel after playtest ended");
            handler.applyPendingSync();
        }

'''
hooks = replace_once(hooks, integrity_anchor, deferred_apply + integrity_anchor, "deferred SyncLevel apply")
hooks_path.write_text(hooks, encoding="utf-8")


# -----------------------------------------------------------------------------
# RemoteActionHandler: never perform an automatic destructive full snapshot
# because a periodic digest found a large difference. Continue with the existing
# manifest/targeted repair path instead. Full SyncLevel remains for explicit
# initial bootstrap and explicit requests only.
# -----------------------------------------------------------------------------
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

old_large_diff = '''            if (diffCount > 256 || diffCount > relativeLimit) {
                log::warn(
                    "RemoteActionHandler: integrity diff too large ({} objects); requesting full SyncLevel",
                    diffCount
                );
                auto request = proto::serializeFullResyncRequest();
                P2PManager::get().sendTo(0, request, ChannelType::Reliable);
                m_repairManifest = {};
                return;
            }'''

new_large_diff = '''            if (diffCount > 256 || diffCount > relativeLimit) {
                // v0.5.2: do NOT turn an integrity mismatch into an automatic
                // destructive full-level replacement. Large snapshots were able
                // to reset object-specific state and invalidate collision nodes.
                // Keep using the manifest/targeted repair path below.
                log::warn(
                    "RemoteActionHandler: integrity diff is large ({} objects); using targeted repair instead of automatic SyncLevel",
                    diffCount
                );
            }'''
remote = replace_once(remote, old_large_diff, new_large_diff, "large-diff full resync removal")

old_sync_apply = '''            log::info("RemoteActionHandler: SyncLevelEnd received, processing full sync");
            handleRemoteSyncLevel(playerId, objectsString, uuids, m_chunkedSync.settings, msg.locks);'''

new_sync_apply = '''            auto* editor = getEditorLayer();
            if (editor && editor->m_playbackMode != PlaybackMode::Not) {
                // Never destroy/recreate editor objects while gameplay collision
                // code is walking them. Keep the newest authoritative snapshot
                // and apply it once playback returns to Not.
                m_pendingSync = PendingSync{
                    playerId,
                    objectsString,
                    uuids,
                    m_chunkedSync.settings,
                    msg.locks
                };
                log::warn("RemoteActionHandler: SyncLevel deferred until playtest ends");
            } else {
                log::info("RemoteActionHandler: SyncLevelEnd received, processing full sync");
                handleRemoteSyncLevel(playerId, objectsString, uuids, m_chunkedSync.settings, msg.locks);
            }'''
remote = replace_once(remote, old_sync_apply, new_sync_apply, "playtest-safe full sync")
remote_path.write_text(remote, encoding="utf-8")


# -----------------------------------------------------------------------------
# Cursor music: send the display title from the machine that actually owns the
# current editor state. The receiver still has an ID-based fallback for older
# status strings, but no longer needs to guess metadata from its own song cache.
# -----------------------------------------------------------------------------
turn_patch_path = Path("scripts/patch_turn_udp.py")
turn_patch = turn_patch_path.read_text(encoding="utf-8")

# This patch operates on the generated EditorHooks/CursorNode sources rather
# than modifying patch_turn_udp.py itself. The markers below are created by it.
hooks = hooks_path.read_text(encoding="utf-8")
old_sender = '''                statusStr += ":music:" + std::to_string(currentSongId) + ":" + std::to_string(currentAudioTrack);

                auto data = proto::serializeCursorUpdate(levelPos.x, levelPos.y, statusStr);'''
new_sender = '''                std::string currentMusicTitle;
                if (currentSongId > 0) {
                    if (auto* song = LevelTools::getSongObject(currentSongId)) {
                        std::string songName = song->m_songName.c_str();
                        std::string artistName = song->m_artistName.c_str();
                        if (!songName.empty()) {
                            currentMusicTitle = artistName.empty() ? songName : artistName + " - " + songName;
                        }
                    }
                    if (currentMusicTitle.empty()) currentMusicTitle = "Song ID " + std::to_string(currentSongId);
                } else {
                    currentMusicTitle = LevelTools::getAudioTitle(currentAudioTrack);
                    if (currentMusicTitle.empty()) currentMusicTitle = "Official song " + std::to_string(currentAudioTrack);
                }
                for (char& ch : currentMusicTitle) {
                    if (ch == '\\n' || ch == '\\r') ch = ' ';
                }
                statusStr += ":music:" + std::to_string(currentSongId) + ":" +
                    std::to_string(currentAudioTrack) + ":" + currentMusicTitle;

                auto data = proto::serializeCursorUpdate(levelPos.x, levelPos.y, statusStr);'''
hooks = replace_once(hooks, old_sender, new_sender, "cursor music sender title")
hooks_path.write_text(hooks, encoding="utf-8")

cursor_path = Path("src/ui/CursorNode.cpp")
cursor = cursor_path.read_text(encoding="utf-8")
old_receiver = '''                auto sep = musicData.find(':');
                if (sep != std::string::npos) {
                    int songId = geode::utils::numFromString<int>(musicData.substr(0, sep)).unwrapOr(0);
                    int audioTrack = geode::utils::numFromString<int>(musicData.substr(sep + 1)).unwrapOr(0);
                    if (songId > 0) {
                        std::string songText;
                        if (auto* song = LevelTools::getSongObject(songId)) {
                            std::string songName = song->m_songName;
                            std::string artistName = song->m_artistName;
                            if (!songName.empty()) {
                                songText = artistName.empty() ? songName : artistName + " - " + songName;
                            }
                        }
                        if (songText.empty()) songText = "ID " + std::to_string(songId);
                        if (songText.size() > 42) songText = songText.substr(0, 39) + "...";
                        playerLabel += "  [♪ " + songText + "]";
                    } else if (audioTrack > 0) {
                        std::string title = LevelTools::getAudioTitle(audioTrack);
                        if (title.empty()) title = "GD " + std::to_string(audioTrack);
                        playerLabel += "  [♪ " + title + "]";
                    }
                }'''
new_receiver = '''                auto sep = musicData.find(':');
                if (sep != std::string::npos) {
                    auto secondSep = musicData.find(':', sep + 1);
                    std::string audioPart = secondSep == std::string::npos
                        ? musicData.substr(sep + 1)
                        : musicData.substr(sep + 1, secondSep - sep - 1);
                    int songId = geode::utils::numFromString<int>(musicData.substr(0, sep)).unwrapOr(0);
                    int audioTrack = geode::utils::numFromString<int>(audioPart).unwrapOr(0);
                    std::string transmittedTitle = secondSep == std::string::npos
                        ? std::string()
                        : musicData.substr(secondSep + 1);

                    std::string songText = transmittedTitle;
                    if (songText.empty() && songId > 0) {
                        if (auto* song = LevelTools::getSongObject(songId)) {
                            std::string songName = song->m_songName.c_str();
                            std::string artistName = song->m_artistName.c_str();
                            if (!songName.empty()) songText = artistName.empty() ? songName : artistName + " - " + songName;
                        }
                        if (songText.empty()) songText = "ID " + std::to_string(songId);
                    } else if (songText.empty() && audioTrack >= 0) {
                        songText = LevelTools::getAudioTitle(audioTrack);
                        if (songText.empty()) songText = "GD " + std::to_string(audioTrack);
                    }

                    if (!songText.empty()) {
                        if (songText.size() > 42) songText = songText.substr(0, 39) + "...";
                        playerLabel += "  [♪ " + songText + "]";
                    }
                }'''
cursor = replace_once(cursor, old_receiver, new_receiver, "cursor music receiver title")
cursor_path.write_text(cursor, encoding="utf-8")


# Final local self-checks for the stabilization patch.
checks = [
    (hooks_path, "m_integrityCheckTimer >= 20.0f"),
    (hooks_path, "applying deferred SyncLevel after playtest ended"),
    (hooks_path, "currentMusicTitle"),
    (remote_path, "using targeted repair instead of automatic SyncLevel"),
    (remote_path, "SyncLevel deferred until playtest ends"),
    (cursor_path, "transmittedTitle"),
]
for path, marker in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.2 stability self-check failed: {path}: {marker}")

print("Patched v0.5.2 stability: safer sync, 20s integrity checks, playtest deferral, transmitted music titles")
