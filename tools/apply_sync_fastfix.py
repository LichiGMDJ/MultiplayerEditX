from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_start = text.find(end_marker, start)
    if end_start < 0:
        raise RuntimeError(f"{label}: end marker not found")
    end = end_start + len(end_marker)
    if end < len(text) and text[end] == "\n":
        end += 1
    return text[:start] + replacement + text[end:]


# 1) WebRTC reliable FIFO: the old cap of three packets per 50 ms network tick
# throttled authoritative snapshots even when SCTP had plenty of capacity.
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(
    p2p,
    "        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;",
    "        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 8;",
    "WebRTC reliable FIFO cap",
)
p2p_path.write_text(p2p, encoding="utf-8")


# 2) Initial snapshot: queue Start -> all Chunks -> End atomically from the
# editor thread. The previous CCSequence inserted 10 ms gaps between chunks,
# allowing live Move/Update traffic to enter the reliable FIFO in the middle of
# the snapshot and then be overwritten when SyncLevelEnd applied old state.
editor_path = Path("src/EditorHooks.cpp")
editor = editor_path.read_text(encoding="utf-8")
start_marker = "        auto* seqArr = cocos2d::CCArray::create();"
end_marker = "        editor->runAction(cocos2d::CCSequence::create(seqArr));"
replacement = '''        // Queue the complete authoritative snapshot in one main-thread pass.
        // P2PManager owns transport pacing; delaying here creates an ordering hole
        // where live edits can be inserted between SyncLevel chunks.
        for (uint32_t i = 0; i < totalChunks; ++i) {
            auto chunkMsg = proto::serializeSyncLevelChunk(
                i,
                reinterpret_cast<const uint8_t*>(chunks[i].objectsString.data()),
                chunks[i].objectsString.size(),
                chunks[i].uuids
            );
            P2PManager::get().sendTo(targetPlayerId, chunkMsg, ChannelType::Reliable);
        }

        // Gather locks after serialization, but before SyncLevelEnd enters the
        // same FIFO, so the receiver observes one contiguous snapshot transaction.
        std::vector<ActionSerializer::LockData> locks;
        for (auto const& [uuid, lockInfo] : handler.getObjectLocks()) {
            locks.push_back({uuid, lockInfo.playerId, lockInfo.timeLeft});
        }

        auto endMsg = proto::serializeSyncLevelEnd(locks);
        P2PManager::get().sendTo(targetPlayerId, endMsg, ChannelType::Reliable);

        log::info(
            "EditorHooks: queued authoritative snapshot for player {}: {} objects, {} chunks",
            targetPlayerId, totalObjects, totalChunks
        );
'''
editor = replace_between(editor, start_marker, end_marker, replacement, "contiguous initial snapshot")
editor_path.write_text(editor, encoding="utf-8")


# 3) Remote object creation and snapshot UUID mapping.
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

func_start = "        std::vector<GameObject*> createObjectsFromSaveStringRobust(LevelEditorLayer* editor, std::string const& saveStr) {"
func_end = "        std::string stableIntegrityHash(std::string const& value) {"
new_func = '''        std::vector<GameObject*> createObjectsFromSaveStringRobust(LevelEditorLayer* editor, std::string const& saveStr) {
            std::vector<GameObject*> newObjects;
            if (!editor || saveStr.empty()) return newObjects;

            // Geometry Dash appends objects created by createObjectsFromString to
            // m_objects. Recording the old count avoids building a set of every
            // object and then scanning the entire level again for each remote
            // placement. That old O(level-size) work dominated large sessions.
            size_t beforeCount = editor->m_objects ? editor->m_objects->count() : 0;
            editor->createObjectsFromString(saveStr, true, true);
            if (!editor->m_objects) return newObjects;

            size_t afterCount = editor->m_objects->count();
            if (afterCount <= beforeCount) return newObjects;
            newObjects.reserve(afterCount - beforeCount);

            size_t index = 0;
            for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
                if (obj && index >= beforeCount) {
                    newObjects.push_back(obj);
                }
                ++index;
            }
            return newObjects;
        }

'''
remote = replace_between(remote, func_start, func_end, new_func, "fast created-object capture")

remote = replace_once(
    remote,
    "                    if (!obj) obj = newObjs.front();\n                    \n                    if (obj->m_objectID == 31) {",
    "                    if (!obj) obj = newObjs.front();\n\n                    // The sender coordinates are authoritative. Explicitly apply\n                    // them even when GD normalizes the save string during object\n                    // creation, preventing remote placements from drifting.\n                    obj->setPosition({objData.x, objData.y});\n                    \n                    if (obj->m_objectID == 31) {",
    "authoritative PlaceObjects position",
)

mapping_start = "            // Match each authoritative serialized record to a newly-created object"
mapping_end = "            size_t fallbackIndex = uuids.size();"
new_mapping = '''            // Match each authoritative serialized record to the recreated object
            // with the same object ID AND nearest serialized position. Matching by
            // object ID alone is ambiguous on real levels where hundreds of objects
            // share the same ID and can bind UUIDs to the wrong instance.
            std::unordered_set<GameObject*> assigned;
            size_t mapped = 0;
            for (size_t i = 0; i < serializedObjects.size(); ++i) {
                int expectedId = serializedObjectId(serializedObjects[i]);
                auto fields = ActionSerializer::parseSaveString(serializedObjects[i]);
                float expectedX = 0.f;
                float expectedY = 0.f;
                if (auto it = fields.find("2"); it != fields.end()) {
                    expectedX = geode::utils::numFromString<float>(it->second).unwrapOr(0.f);
                }
                if (auto it = fields.find("3"); it != fields.end()) {
                    expectedY = geode::utils::numFromString<float>(it->second).unwrapOr(0.f);
                }

                GameObject* match = nullptr;
                float bestDistanceSq = 1.0e30f;
                for (auto* candidate : newObjs) {
                    if (!candidate || assigned.contains(candidate) || candidate->m_objectID != expectedId) continue;
                    float dx = candidate->getPositionX() - expectedX;
                    float dy = candidate->getPositionY() - expectedY;
                    float distanceSq = dx * dx + dy * dy;
                    if (distanceSq < bestDistanceSq) {
                        bestDistanceSq = distanceSq;
                        match = candidate;
                        if (distanceSq <= 0.0001f) break;
                    }
                }
                if (!match) {
                    log::error(
                        "RemoteActionHandler: no recreated object matched snapshot record {} (objectID={}, x={}, y={})",
                        i, expectedId, expectedX, expectedY
                    );
                    continue;
                }

                // Reassert the serialized position after matching. This also
                // neutralizes small receiver-side normalization differences.
                match->setPosition({expectedX, expectedY});
                assigned.insert(match);
                auto tagged = decodeLayerTaggedUuid(uuids[i]);
                if (tagged.tagged) applyEditorLayers(match, tagged.layer1, tagged.layer2);
                registerObject(tagged.uuid, match);
                ++mapped;

                if (match->m_objectID == 31) {
                    if (auto* startPos = typeinfo_cast<StartPosObject*>(match)) {
                        startPos->loadSettingsFromString(serializedObjects[i]);
                    }
                    updateStartPosCache(match);
                }
            }

            size_t fallbackIndex = uuids.size();'''
remote = replace_between(remote, mapping_start, mapping_end, new_mapping, "position-aware snapshot UUID mapping")
remote_path.write_text(remote, encoding="utf-8")

print("sync fastfix applied")
