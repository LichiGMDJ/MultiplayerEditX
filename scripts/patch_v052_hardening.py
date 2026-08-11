from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.2 hardening: {label}: expected source block not found")
    return text.replace(old, new, 1)


# =============================================================================
# ActionSerializer: StartPos state is shared session state, not client-local.
# Preserve the complete saveString so mode/speed/gravity/mini/dual/etc. changes
# are detected and propagated like every other deep object property.
# =============================================================================
action_path = Path("src/ActionSerializer.cpp")
action = action_path.read_text(encoding="utf-8")

old_inject = '''    void injectLocalStartPosState(ObjectData& remoteData, GameObject* localObj) {
        if (!localObj || remoteData.objectID != 31 || remoteData.saveString.empty()) return;
        
        if (auto* editor = LevelEditorLayer::get()) {
            auto localMap = parseSaveString(localObj->getSaveString(editor));
            auto remoteVec = parseSaveStringOrdered(remoteData.saveString);
            
            std::vector<std::pair<std::string, std::string>> newRemoteVec;
            for (auto const& p : remoteVec) {
                if (p.first == "kA21" || p.first == "kA9" || p.first == "93") continue;
                newRemoteVec.push_back(p);
            }
            
            if (localMap.count("kA21")) newRemoteVec.push_back({"kA21", localMap.at("kA21")});
            if (localMap.count("kA9")) newRemoteVec.push_back({"kA9", localMap.at("kA9")});
            if (localMap.count("93")) newRemoteVec.push_back({"93", localMap.at("93")});
            
            remoteData.saveString = buildSaveStringOrdered(newRemoteVec);
        }
    }'''

new_inject = '''    void injectLocalStartPosState(ObjectData& remoteData, GameObject* localObj) {
        // v0.5.2: StartPos configuration is authoritative shared editor state.
        // Older builds preserved several StartPos keys from the receiving client,
        // which could silently overwrite the sender's configuration after sync.
        // Keep this compatibility helper as a no-op so existing call sites remain
        // valid while the complete remote saveString is applied unchanged.
        (void)remoteData;
        (void)localObj;
    }'''
action = replace_once(action, old_inject, new_inject, "StartPos local-state override removal")

old_ignore = '''        // Ignore Disable Start Pos changes (kA21, kA9, and 93) so they remain local
        if (obj && obj->m_objectID == 31) {
            oldMap.erase("kA21");
            newMap.erase("kA21");
            oldMap.erase("kA9");
            newMap.erase("kA9");
            oldMap.erase("93");
            newMap.erase("93");
        }

'''
action = replace_once(action, old_ignore, "", "StartPos deep-change exclusions removal")
action_path.write_text(action, encoding="utf-8")


# =============================================================================
# EditorHooks: every StartPos encountered after init must enter the cache.
# =============================================================================
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

old_cache = '''    void updateStartPosCache(GameObject* obj) {
        if (obj && obj->m_objectID == 31 && s_startPosObjects.count(obj)) {
            if (auto* editor = LevelEditorLayer::get()) {
                s_startPosSaveStrings[obj] = obj->getSaveString(editor);
            }
        }
    }'''
new_cache = '''    void updateStartPosCache(GameObject* obj) {
        if (!obj || obj->m_objectID != 31) return;
        // A StartPos may be created by a remote placement, targeted repair or
        // initial snapshot after LevelEditorLayer::init() seeded the cache.
        // Always register it before storing its full serialized state.
        s_startPosObjects.insert(obj);
        if (auto* editor = LevelEditorLayer::get()) {
            s_startPosSaveStrings[obj] = obj->getSaveString(editor);
        }
    }'''
hooks = replace_once(hooks, old_cache, new_cache, "StartPos cache registration")
hooks_path.write_text(hooks, encoding="utf-8")


# =============================================================================
# RemoteActionHandler: validate snapshot bounds before allocation/decompression,
# and rebuild UUID mappings from the exact serialized object list instead of
# blindly trusting the order of every object auto-created by GD.
# =============================================================================
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

# Add small parsing helpers next to the existing safe transform helper.
old_helper = '''        void applyTransformSafe(GameObject* obj, float rotation, float scaleX, float scaleY, bool flipX, bool flipY) {
            if (!obj) return;
            obj->setRotation(rotation);
            obj->setFlipX(flipX);
            obj->setFlipY(flipY);
            obj->setScaleX(scaleX);
            obj->setScaleY(scaleY);
        }
    }'''
new_helper = '''        void applyTransformSafe(GameObject* obj, float rotation, float scaleX, float scaleY, bool flipX, bool flipY) {
            if (!obj) return;
            obj->setRotation(rotation);
            obj->setFlipX(flipX);
            obj->setFlipY(flipY);
            obj->setScaleX(scaleX);
            obj->setScaleY(scaleY);
        }

        std::vector<std::string> splitSerializedObjects(std::string const& objectsString) {
            std::vector<std::string> out;
            size_t start = 0;
            while (start < objectsString.size()) {
                size_t end = objectsString.find(';', start);
                if (end == std::string::npos) end = objectsString.size();
                if (end > start) out.push_back(objectsString.substr(start, end - start));
                if (end == objectsString.size()) break;
                start = end + 1;
            }
            return out;
        }

        int serializedObjectId(std::string const& saveString) {
            auto fields = ActionSerializer::parseSaveString(saveString);
            auto it = fields.find("1");
            if (it == fields.end()) return 0;
            return geode::utils::numFromString<int>(it->second).unwrapOr(0);
        }
    }'''
remote = replace_once(remote, old_helper, new_helper, "snapshot parsing helpers")

# Bound SyncLevelStart before resize() can allocate based on a malformed peer packet.
old_start = '''            m_chunkedSync.hostPlayerId = playerId;
            m_chunkedSync.totalChunks = msg.totalChunks;
            m_chunkedSync.totalObjects = msg.totalObjects;
            m_chunkedSync.settings = msg.settings;
            m_chunkedSync.chunks.clear();
            m_chunkedSync.chunks.resize(msg.totalChunks);'''
new_start = '''            constexpr uint32_t kMaxSyncChunks = 4096;
            constexpr uint32_t kMaxSyncObjects = 500000;
            if (msg.totalChunks == 0 || msg.totalChunks > kMaxSyncChunks || msg.totalObjects > kMaxSyncObjects) {
                log::error(
                    "RemoteActionHandler: rejected SyncLevelStart with unsafe bounds (chunks={}, objects={})",
                    msg.totalChunks,
                    msg.totalObjects
                );
                m_chunkedSync.active = false;
                m_chunkedSync.chunks.clear();
                m_chunkedSync.uuidChunks.clear();
                return;
            }
            m_chunkedSync.hostPlayerId = playerId;
            m_chunkedSync.totalChunks = msg.totalChunks;
            m_chunkedSync.totalObjects = msg.totalObjects;
            m_chunkedSync.settings = msg.settings;
            m_chunkedSync.chunks.clear();
            m_chunkedSync.chunks.resize(msg.totalChunks);'''
remote = replace_once(remote, old_start, new_start, "SyncLevelStart bounds")

# Cap the compressed snapshot before constructing a potentially huge buffer.
old_reconstruct = '''            // Reconstruct objectsString
            std::string compressedString = "";
            for (auto const& chunk : m_chunkedSync.chunks) {
                compressedString += chunk;
            }
            
            std::string objectsString = "";'''
new_reconstruct = '''            // Reconstruct objectsString with a hard compressed-size ceiling.
            constexpr size_t kMaxCompressedSyncBytes = 64 * 1024 * 1024;
            size_t compressedSize = 0;
            for (auto const& chunk : m_chunkedSync.chunks) {
                if (chunk.size() > kMaxCompressedSyncBytes - std::min(compressedSize, kMaxCompressedSyncBytes)) {
                    compressedSize = kMaxCompressedSyncBytes + 1;
                    break;
                }
                compressedSize += chunk.size();
            }
            if (compressedSize > kMaxCompressedSyncBytes) {
                log::error("RemoteActionHandler: rejected oversized SyncLevel payload");
                m_chunkedSync.active = false;
                m_chunkedSync.chunks.clear();
                m_chunkedSync.uuidChunks.clear();
                return;
            }

            std::string compressedString;
            compressedString.reserve(compressedSize);
            for (auto const& chunk : m_chunkedSync.chunks) {
                compressedString += chunk;
            }
            
            std::string objectsString = "";'''
remote = replace_once(remote, old_reconstruct, new_reconstruct, "compressed snapshot size cap")

# Validate exact object-record count before any existing editor object is deleted.
old_ready = '''        log::info("RemoteActionHandler: Editor ready (m_objects count before sync = {})",
            editor->m_objects ? editor->m_objects->count() : 0);

        m_pendingSync.reset();
        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);'''
new_ready = '''        log::info("RemoteActionHandler: Editor ready (m_objects count before sync = {})",
            editor->m_objects ? editor->m_objects->count() : 0);

        auto serializedObjects = splitSerializedObjects(objectsString);
        if (serializedObjects.size() != uuids.size()) {
            log::error(
                "RemoteActionHandler: refusing destructive SyncLevel because serialized object count ({}) != UUID count ({})",
                serializedObjects.size(),
                uuids.size()
            );
            return;
        }

        m_pendingSync.reset();
        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);'''
remote = replace_once(remote, old_ready, new_ready, "pre-destructive snapshot validation")

old_registration = '''            int index = 0;
            for (auto* obj : newObjs) {
                if (index < static_cast<int>(uuids.size())) {
                    registerObject(uuids[index], obj);
                    index++;
                } else {
                    registerObject("lvl_obj_" + std::to_string(index), obj);
                    index++;
                }
                
                if (obj->m_objectID == 31) {
                    updateStartPosCache(obj);
                }
            }
            if (index != static_cast<int>(uuids.size())) {
                log::warn("RemoteActionHandler: object/uuid count mismatch on sync "
                          "(spawned={}, uuids={})", index, uuids.size());
            }'''

new_registration = '''            // Match each authoritative serialized record to a newly-created object
            // with the same object ID. GD may auto-create companion objects (for
            // example teleport portal parts), so blindly zipping newObjs with UUIDs
            // can shift every later UUID and make future deletes hit the wrong object.
            std::unordered_set<GameObject*> assigned;
            size_t mapped = 0;
            for (size_t i = 0; i < serializedObjects.size(); ++i) {
                int expectedId = serializedObjectId(serializedObjects[i]);
                GameObject* match = nullptr;
                for (auto* candidate : newObjs) {
                    if (!candidate || assigned.contains(candidate)) continue;
                    if (candidate->m_objectID == expectedId) {
                        match = candidate;
                        break;
                    }
                }
                if (!match) {
                    log::error(
                        "RemoteActionHandler: no recreated object matched snapshot record {} (objectID={})",
                        i,
                        expectedId
                    );
                    continue;
                }

                assigned.insert(match);
                registerObject(uuids[i], match);
                ++mapped;

                if (match->m_objectID == 31) {
                    if (auto* startPos = typeinfo_cast<StartPosObject*>(match)) {
                        // createObjectsFromString normally restores this already,
                        // but StartPos has additional runtime settings/cache state.
                        startPos->loadSettingsFromString(serializedObjects[i]);
                    }
                    updateStartPosCache(match);
                }
            }

            size_t fallbackIndex = uuids.size();
            for (auto* obj : newObjs) {
                if (!obj || assigned.contains(obj)) continue;
                if (getUUIDForObject(obj).empty()) {
                    registerObject("sync_extra_" + std::to_string(fallbackIndex++), obj);
                }
                if (obj->m_objectID == 31) updateStartPosCache(obj);
            }

            if (mapped != uuids.size()) {
                log::error(
                    "RemoteActionHandler: snapshot mapping incomplete (mapped={}, uuids={}, spawned={})",
                    mapped,
                    uuids.size(),
                    newObjs.size()
                );
            }'''
remote = replace_once(remote, old_registration, new_registration, "robust full-sync UUID mapping")

remote_path.write_text(remote, encoding="utf-8")


# =============================================================================
# Self-checks: these markers are also asserted by the release workflow/finalizer.
# =============================================================================
checks = [
    (action_path, "StartPos configuration is authoritative shared editor state"),
    (hooks_path, "Always register it before storing its full serialized state"),
    (remote_path, "rejected SyncLevelStart with unsafe bounds"),
    (remote_path, "refusing destructive SyncLevel because serialized object count"),
    (remote_path, "snapshot mapping incomplete"),
    (remote_path, "loadSettingsFromString(serializedObjects[i])"),
]
for path, marker in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.2 hardening self-check failed: {path}: {marker}")

print("Patched v0.5.2 hardening: authoritative StartPos state, bounded snapshots, validated full sync, robust UUID mapping")
