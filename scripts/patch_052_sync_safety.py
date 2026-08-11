from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)

# 0.5.2 sync-safety hotfix:
# - make periodic integrity checks less aggressive
# - never auto-promote a large digest mismatch into a destructive full SyncLevel
# - never apply a full snapshot while the local editor is playtesting/colliding

hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
hooks = replace_once(
    hooks,
    "(m_fields->m_forceIntegrityCheck || m_fields->m_integrityCheckTimer >= 3.0f)",
    "(m_fields->m_forceIntegrityCheck || m_fields->m_integrityCheckTimer >= 15.0f)",
    "0.5.2 integrity interval",
)
hooks_path.write_text(hooks, encoding="utf-8")

remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

remote = replace_once(
    remote,
    '''            if (diffCount > 256 || diffCount > relativeLimit) {
                log::warn(
                    "RemoteActionHandler: integrity diff too large ({} objects); requesting full SyncLevel",
                    diffCount
                );
                auto request = proto::serializeFullResyncRequest();
                P2PManager::get().sendTo(0, request, ChannelType::Reliable);
                m_repairManifest = {};
                return;
            }''',
    '''            if (diffCount > 256 || diffCount > relativeLimit) {
                // 0.5.2 safety policy: a periodic integrity mismatch must never
                // destructively replace the whole live editor. Full SyncLevel is
                // reserved for explicit first-join bootstrap. Large drift is
                // reported and left untouched instead of deleting/recreating
                // objects under the editor/playtest collision loop.
                log::warn(
                    "RemoteActionHandler: integrity diff too large ({} objects); automatic full SyncLevel suppressed",
                    diffCount
                );
                m_repairManifest = {};
                return;
            }''',
    "0.5.2 suppress automatic full resync",
)

remote = replace_once(
    remote,
    '''            log::info("RemoteActionHandler: SyncLevelEnd received, processing full sync");
            handleRemoteSyncLevel(playerId, objectsString, uuids, m_chunkedSync.settings, msg.locks);

            m_chunkedSync.active = false;''',
    '''            auto* syncEditor = getEditorLayer();
            if (
                m_initialSyncCompleted &&
                syncEditor &&
                syncEditor->m_playbackMode != PlaybackMode::Not
            ) {
                // Never delete/recreate editor objects while PlayerObject is
                // iterating collision targets. A reconnect/full snapshot racing
                // with playtest can otherwise invalidate a CCNode/GameObject
                // still referenced by the collision loop.
                log::warn(
                    "RemoteActionHandler: full SyncLevel ignored during playtest for collision safety"
                );
            } else {
                log::info("RemoteActionHandler: SyncLevelEnd received, processing full sync");
                handleRemoteSyncLevel(playerId, objectsString, uuids, m_chunkedSync.settings, msg.locks);
            }

            m_chunkedSync.active = false;''',
    "0.5.2 playtest full-sync guard",
)

remote_path.write_text(remote, encoding="utf-8")
print("Applied 0.5.2 sync safety: 15s integrity cadence, no automatic full resync, no full sync during playtest")
