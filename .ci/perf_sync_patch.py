from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# Safe to run twice when another workflow wins the race.
p2p_probe = Path("src/P2PManager.cpp").read_text(encoding="utf-8")
remote_probe = Path("src/RemoteActionHandler.cpp").read_text(encoding="utf-8")
if "kMaxBulkPacketsPerPeerPerTick = 8" in p2p_probe and "spawnedById" in remote_probe:
    print("performance patch already applied")
    raise SystemExit(0)

# 1. Remove redundant Cocos per-chunk pacing from initial snapshot.
path = Path("src/EditorHooks.cpp")
text = path.read_text(encoding="utf-8")
start = text.index("        auto* seqArr = cocos2d::CCArray::create();")
end_marker = "        editor->runAction(cocos2d::CCSequence::create(seqArr));\n"
end = text.index(end_marker, start) + len(end_marker)
replacement = '''        // The transport layer already owns ordered reliable pacing. Queue the
        // complete snapshot immediately instead of inserting a Cocos delay before
        // every chunk; the FIFO preserves Start -> Chunk[n] -> End ordering.
        for (uint32_t i = 0; i < totalChunks; ++i) {
            auto chunkMsg = proto::serializeSyncLevelChunk(
                i,
                reinterpret_cast<const uint8_t*>(chunks[i].objectsString.data()),
                chunks[i].objectsString.size(),
                chunks[i].uuids
            );
            P2PManager::get().sendTo(targetPlayerId, chunkMsg, ChannelType::Reliable);
        }

        std::vector<ActionSerializer::LockData> locks;
        for (auto const& [uuid, lockInfo] : handler.getObjectLocks()) {
            locks.push_back({uuid, lockInfo.playerId, lockInfo.timeLeft});
        }

        auto endMsg = proto::serializeSyncLevelEnd(locks);
        P2PManager::get().sendTo(targetPlayerId, endMsg, ChannelType::Reliable);
        log::info(
            "EditorHooks: queued authoritative snapshot immediately: player={} chunks={} objects={} compressedBytes={}",
            targetPlayerId, totalChunks, totalObjects, compressedBytes.size()
        );
'''
text = text[:start] + replacement + text[end:]
path.write_text(text, encoding="utf-8")

# 2. Raise WebRTC reliable burst budget, shorten Auto fallback, and drain
# HTTP relay FIFO immediately after successful POST acceptance.
path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 3;",
    "        constexpr size_t kMaxBulkPacketsPerPeerPerTick = 8;",
    "WebRTC reliable burst budget",
)
text = replace_once(
    text,
    "            std::this_thread::sleep_for(std::chrono::seconds(8));",
    "            std::this_thread::sleep_for(std::chrono::seconds(3));",
    "Auto HTTP relay fallback latency",
)
relay_log = '''                } else if (trackedSequence != 0) {
                    log::debug(
                        "P2PManager: HTTP relay accepted reliable sequence #{} for player {}",
                        trackedSequence, playerId
                    );
                }
'''
relay_log_new = relay_log + '''
                // Continue draining immediately after a successful server accept.
                // Failed POSTs retain the normal retry/backoff path.
                if (res.ok() && trackedSequence != 0) {
                    queueInMainThread([this]() { flushBulkReliableQueues(); });
                }
'''
text = replace_once(text, relay_log, relay_log_new, "HTTP relay eager FIFO drain")
path.write_text(text, encoding="utf-8")

# 3. Replace quadratic snapshot UUID matching with per-object-ID buckets.
path = Path("src/RemoteActionHandler.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "#include <algorithm>\n#include <unordered_set>",
    "#include <algorithm>\n#include <chrono>\n#include <unordered_set>",
    "chrono include",
)
old_id = '''        int serializedObjectId(std::string const& saveString) {
            auto fields = ActionSerializer::parseSaveString(saveString);
            auto it = fields.find("1");
            if (it == fields.end()) return 0;
            return geode::utils::numFromString<int>(it->second).unwrapOr(0);
        }'''
new_id = '''        int serializedObjectId(std::string const& saveString) {
            // Object save strings normally begin with key 1 (object ID). Avoid
            // constructing a full key/value map for every snapshot object.
            auto firstComma = saveString.find(',');
            if (firstComma != std::string::npos && saveString.substr(0, firstComma) == "1") {
                auto secondComma = saveString.find(',', firstComma + 1);
                auto value = saveString.substr(
                    firstComma + 1,
                    secondComma == std::string::npos
                        ? std::string::npos
                        : secondComma - firstComma - 1
                );
                return geode::utils::numFromString<int>(value).unwrapOr(0);
            }

            auto fields = ActionSerializer::parseSaveString(saveString);
            auto it = fields.find("1");
            if (it == fields.end()) return 0;
            return geode::utils::numFromString<int>(it->second).unwrapOr(0);
        }'''
text = replace_once(text, old_id, new_id, "fast object ID parser")
log_line = '''        log::info("RemoteActionHandler: sync_level received (playerId={}, objectsStringLen={}, uuids={}, settingsLen={}, locks={}, pending={})",
            playerId, objectsString.size(), uuids.size(), settings.saveString.size(), locks.size(), isPendingSync);'''
text = replace_once(
    text,
    log_line,
    '''        auto syncApplyStartedAt = std::chrono::steady_clock::now();
        log::info("RemoteActionHandler: sync_level received (playerId={}, objectsStringLen={}, uuids={}, settingsLen={}, locks={}, pending={})",
            playerId, objectsString.size(), uuids.size(), settings.saveString.size(), locks.size(), isPendingSync);''',
    "sync apply timer",
)
map_start = text.index("            std::unordered_set<GameObject*> assigned;")
map_end = text.index("            size_t fallbackIndex = uuids.size();", map_start)
fast_map = '''            // Group spawned objects once. Matching is now O(n) instead of
            // scanning the complete spawned list for every serialized record.
            std::unordered_map<int, std::vector<GameObject*>> spawnedById;
            spawnedById.reserve(newObjs.size());
            for (auto* candidate : newObjs) {
                if (candidate) spawnedById[candidate->m_objectID].push_back(candidate);
            }
            std::unordered_map<int, size_t> nextById;
            nextById.reserve(spawnedById.size());
            std::unordered_set<GameObject*> assigned;
            assigned.reserve(std::min(newObjs.size(), serializedObjects.size()));

            size_t mapped = 0;
            for (size_t i = 0; i < serializedObjects.size(); ++i) {
                int expectedId = serializedObjectId(serializedObjects[i]);
                GameObject* match = nullptr;

                auto bucketIt = spawnedById.find(expectedId);
                if (bucketIt != spawnedById.end()) {
                    auto& cursor = nextById[expectedId];
                    auto& bucket = bucketIt->second;
                    if (cursor < bucket.size()) match = bucket[cursor++];
                }

                if (!match) {
                    log::error(
                        "RemoteActionHandler: no recreated object matched snapshot record {} (objectID={})",
                        i, expectedId
                    );
                    continue;
                }

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
text = text[:map_start] + fast_map + text[map_end:]
old_done = '''        log::info("RemoteActionHandler: sync_level complete (final m_objects count = {})",
            editor->m_objects ? editor->m_objects->count() : 0);'''
new_done = '''        auto syncApplyMs = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - syncApplyStartedAt
        ).count();
        log::info(
            "RemoteActionHandler: sync_level complete (final m_objects count = {}, applyMs={})",
            editor->m_objects ? editor->m_objects->count() : 0,
            syncApplyMs
        );'''
text = replace_once(text, old_done, new_done, "sync apply timing log")
path.write_text(text, encoding="utf-8")

# 4. Public room browser silently refreshes every 4 seconds.
path = Path("src/ui/RoomDiscoveryPopups.hpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    std::size_t m_page = 0;
    geode::async::TaskHolder<geode::utils::web::WebResponse> m_request;

    bool setup();
    void fetchRooms();''',
    '''    std::size_t m_page = 0;
    geode::async::TaskHolder<geode::utils::web::WebResponse> m_request;
    bool m_fetchInFlight = false;
    float m_autoRefreshTimer = 0.f;

    bool setup();
    void update(float dt) override;
    void fetchRooms(bool showLoading = true);''',
    "room browser refresh state",
)
path.write_text(text, encoding="utf-8")

path = Path("src/ui/RoomDiscoveryPopups.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    fetchRooms();
    return true;
}

void RoomBrowserPopup::fetchRooms() {
    if (!m_body) return;
    m_rooms.clear();
    m_page = 0;
    m_body->removeAllChildren();

    auto center = m_mainLayer->getContentSize() / 2.f;
    m_statusLabel = makeLabel("Loading rooms...", 0.45f, center, m_body);''',
    '''    fetchRooms();
    this->scheduleUpdate();
    return true;
}

void RoomBrowserPopup::update(float dt) {
    m_autoRefreshTimer += dt;
    if (m_autoRefreshTimer < 4.f) return;
    m_autoRefreshTimer = 0.f;
    fetchRooms(false);
}

void RoomBrowserPopup::fetchRooms(bool showLoading) {
    if (!m_body || m_fetchInFlight) return;
    m_fetchInFlight = true;
    if (showLoading) {
        m_page = 0;
        m_body->removeAllChildren();
        auto center = m_mainLayer->getContentSize() / 2.f;
        m_statusLabel = makeLabel("Loading rooms...", 0.45f, center, m_body);
    }''',
    "room browser periodic refresh",
)
text = replace_once(
    text,
    '''    m_request.spawn(req.get(url), [this, url](web::WebResponse res) {
        if (!m_body) return;
        if (!res.ok()) {''',
    '''    m_request.spawn(req.get(url), [this, url, showLoading](web::WebResponse res) {
        m_fetchInFlight = false;
        if (!m_body) return;
        if (!res.ok()) {''',
    "room browser callback state",
)
text = replace_once(
    text,
    '''            m_body->removeAllChildren();
            m_statusLabel = makeLabel("Could not load rooms", 0.45f, m_mainLayer->getContentSize() / 2.f, m_body);
            m_statusLabel->setColor({255, 120, 120});
            return;''',
    '''            if (showLoading) {
                m_body->removeAllChildren();
                m_statusLabel = makeLabel("Could not load rooms", 0.45f, m_mainLayer->getContentSize() / 2.f, m_body);
                m_statusLabel->setColor({255, 120, 120});
            }
            return;''',
    "silent refresh error handling",
)
text = replace_once(
    text,
    "        for (std::size_t i = 0; i < json.size(); ++i) {",
    "        std::vector<BrowserRoomInfo> freshRooms;\n        freshRooms.reserve(json.size());\n        for (std::size_t i = 0; i < json.size(); ++i) {",
    "fresh room list",
)
text = replace_once(
    text,
    '''            if (!room.roomCode.empty()) m_rooms.push_back(std::move(room));
        }
        rebuild();''',
    '''            if (!room.roomCode.empty()) freshRooms.push_back(std::move(room));
        }
        m_rooms = std::move(freshRooms);
        rebuild();''',
    "atomic room list replacement",
)
path.write_text(text, encoding="utf-8")

# 5. Faster public-directory stale-host expiry. Graceful DELETE is immediate.
path = Path("server/signaling/server.ts")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "const HOST_DIRECTORY_STALE_MS = 75_000;",
    "const HOST_DIRECTORY_STALE_MS = 45_000;",
    "host directory stale window",
)
path.write_text(text, encoding="utf-8")

print("performance patch applied")
