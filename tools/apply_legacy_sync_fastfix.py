from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def replace_before(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start] + replacement + text[end:]


# P2P throughput: 3 packets / 50 ms was an artificial ~60 packets/s cap.
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(
    p2p,
    "        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;",
    "        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 8;",
    "reliable FIFO throughput",
)
p2p_path.write_text(p2p, encoding="utf-8")


# Initial snapshot: enqueue Start -> Chunks -> End without Cocos delays so live
# edits cannot interleave inside a snapshot transaction.
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
snapshot_start = "        auto* seqArr = cocos2d::CCArray::create();"
snapshot_end = "    }\n\n    // Registers UUIDs onto the editor's currently-spawned objects"
new_snapshot_tail = '''        // Queue the complete authoritative snapshot in one main-thread pass.
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

        // Keep SyncLevelEnd directly behind the chunk stream in the same FIFO.
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
hooks = replace_before(hooks, snapshot_start, snapshot_end, new_snapshot_tail, "contiguous snapshot")
hooks_path.write_text(hooks, encoding="utf-8")


remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

# Avoid two full-level scans for every remotely created object batch.
helper_start = "        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {"
helper_end = "        std::string stableIntegrityHash(std::string const& value) {"
new_helper = '''        std::vector<GameObject*> createObjectsFromSaveStringRobust(LevelEditorLayer* editor, std::string const& saveStr) {
            std::vector<GameObject*> newObjects;
            if (!editor || saveStr.empty()) return newObjects;

            // Geometry Dash appends createObjectsFromString results to m_objects.
            // Capture only the appended range instead of scanning the full level
            // before and after every remote placement.
            size_t beforeCount = editor->m_objects ? editor->m_objects->count() : 0;
            editor->createObjectsFromString(saveStr, true, true);
            if (!editor->m_objects) return newObjects;

            size_t afterCount = editor->m_objects->count();
            if (afterCount <= beforeCount) return newObjects;
            newObjects.reserve(afterCount - beforeCount);

            size_t index = 0;
            for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
                if (obj && index >= beforeCount) newObjects.push_back(obj);
                ++index;
            }
            return newObjects;
        }

'''
remote = replace_before(remote, helper_start, helper_end, new_helper, "fast remote creation")

# Reassert sender coordinates after save-string reconstruction.
place_old = '''                    if (!obj) obj = newObjs.front();
                    
                    if (obj->m_objectID == 31) {'''
place_new = '''                    if (!obj) obj = newObjs.front();

                    // Sender coordinates are authoritative even if GD/mod hooks
                    // normalize the save string on the receiving machine.
                    obj->setPosition({objData.x, objData.y});
                    
                    if (obj->m_objectID == 31) {'''
remote = replace_once(remote, place_old, place_new, "authoritative PlaceObjects position")

# Full snapshot mapping: ID-only matching binds UUIDs to the wrong instance when
# many objects share the same object ID. Index by ID + quantized position first.
mapping_start = "            // Match each authoritative serialized record to a newly-created object"
mapping_end = "            size_t fallbackIndex = uuids.size();"
new_mapping = '''            // Index recreated objects by authoritative ID + quantized position.
            // Exact lookup is O(N); nearest-by-ID is only a defensive fallback for
            // the rare receiver-side normalization case.
            auto positionKey = [](int objectID, float x, float y) {
                auto qx = static_cast<long long>(std::llround(static_cast<double>(x) * 1000.0));
                auto qy = static_cast<long long>(std::llround(static_cast<double>(y) * 1000.0));
                return std::to_string(objectID) + ":" + std::to_string(qx) + ":" + std::to_string(qy);
            };

            std::unordered_map<std::string, std::vector<GameObject*>> candidatesByPosition;
            std::unordered_map<int, std::vector<GameObject*>> candidatesById;
            candidatesByPosition.reserve(newObjs.size());
            candidatesById.reserve(newObjs.size());
            for (auto* candidate : newObjs) {
                if (!candidate) continue;
                candidatesByPosition[positionKey(
                    candidate->m_objectID,
                    candidate->getPositionX(),
                    candidate->getPositionY()
                )].push_back(candidate);
                candidatesById[candidate->m_objectID].push_back(candidate);
            }

            std::unordered_set<GameObject*> assigned;
            assigned.reserve(newObjs.size());
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
                auto exactIt = candidatesByPosition.find(positionKey(expectedId, expectedX, expectedY));
                if (exactIt != candidatesByPosition.end()) {
                    auto& exact = exactIt->second;
                    while (!exact.empty() && assigned.contains(exact.back())) exact.pop_back();
                    if (!exact.empty()) {
                        match = exact.back();
                        exact.pop_back();
                    }
                }

                if (!match) {
                    auto idIt = candidatesById.find(expectedId);
                    if (idIt != candidatesById.end()) {
                        float bestDistanceSq = 1.0e30f;
                        for (auto* candidate : idIt->second) {
                            if (!candidate || assigned.contains(candidate)) continue;
                            float dx = candidate->getPositionX() - expectedX;
                            float dy = candidate->getPositionY() - expectedY;
                            float distanceSq = dx * dx + dy * dy;
                            if (distanceSq < bestDistanceSq) {
                                bestDistanceSq = distanceSq;
                                match = candidate;
                            }
                        }
                    }
                }

                if (!match) {
                    log::error(
                        "RemoteActionHandler: no recreated object matched snapshot record {} (objectID={}, x={}, y={})",
                        i, expectedId, expectedX, expectedY
                    );
                    continue;
                }

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

'''
remote = replace_before(remote, mapping_start, mapping_end, new_mapping, "position-aware UUID mapping")
remote_path.write_text(remote, encoding="utf-8")

# Final guards: UI files are intentionally untouched.
checks = {
    "src/P2PManager.cpp": ["kMaxBulkPacketsPerPeerPerTick = 8"],
    "src/EditorHooks.cpp": ["queued authoritative snapshot for player"],
    "src/RemoteActionHandler.cpp": [
        "obj->setPosition({objData.x, objData.y});",
        "candidatesByPosition.reserve(newObjs.size())",
        "match->setPosition({expectedX, expectedY});",
        "std::string stableIntegrityHash(std::string const& value)",
    ],
}
for path, tokens in checks.items():
    text = Path(path).read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise RuntimeError(f"{path}: missing expected token {token!r}")

print("legacy UI sync fastfix applied")
