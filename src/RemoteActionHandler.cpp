#include "RemoteActionHandler.hpp"
#include "P2PManager.hpp"
#include "BinaryProtocol.hpp"
#include "SessionManager.hpp"
#include "MessageBatcher.hpp"
#include "ui/MultiplayerPopup.hpp"
#include <Geode/Geode.hpp>
#include <Geode/utils/file.hpp>
#include <random>
#include <sstream>
#include <iomanip>
#include <set>
#include <cmath>
#include <algorithm>
#include <unordered_set>

using namespace geode::prelude;

namespace mpedit {

    void sendFullLevelSyncTo(int targetPlayerId);

    namespace {
        struct ProcessingRemoteGuard {
            bool& flag;

            explicit ProcessingRemoteGuard(bool& value) : flag(value) {
                flag = true;
            }

            ProcessingRemoteGuard(ProcessingRemoteGuard const&) = delete;
            ProcessingRemoteGuard& operator=(ProcessingRemoteGuard const&) = delete;

            ~ProcessingRemoteGuard() {
                flag = false;
            }
        };
    }

    namespace {
        struct RawBulkPasteRx {
            bool active = false;
            uint32_t pasteId = 0;
            uint32_t totalChunks = 0;
            uint32_t totalObjects = 0;
            bool withColor = false;
            bool noUndo = false;
            float anchorX = 0.f;
            float anchorY = 0.f;
            std::vector<std::string> dataChunks;
            std::vector<std::vector<std::string>> uuidChunks;
            std::vector<bool> received;
        };
        std::unordered_map<int, RawBulkPasteRx> s_rawBulkPasteRx;
        uint32_t s_lastGlobalRecoveryRevision = 0;

        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {
            std::set<GameObject*> existing;
            if (editor && editor->m_objects) {
                for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
                    if (obj) existing.insert(obj);
                }
            }
            return existing;
        }

        std::vector<GameObject*> createObjectsFromSaveStringRobust(LevelEditorLayer* editor, std::string const& saveStr) {
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

        std::string stableIntegrityHash(std::string const& value) {
            uint64_t hash = 1469598103934665603ull;
            for (unsigned char c : value) {
                hash ^= static_cast<uint64_t>(c);
                hash *= 1099511628211ull;
            }
            std::ostringstream out;
            out << std::hex << std::setw(16) << std::setfill('0') << hash;
            return out.str();
        }

        void applyTransformSafe(GameObject* obj, float rotation, float scaleX, float scaleY, bool flipX, bool flipY) {
            if (!obj) return;
            obj->setRotation(rotation);
            obj->setFlipX(flipX);
            obj->setFlipY(flipY);
            obj->setScaleX(scaleX);
            obj->setScaleY(scaleY);
        }

        struct LayerTaggedUuid {
            std::string uuid;
            int layer1 = 0;
            int layer2 = 0;
            bool tagged = false;
        };

        LayerTaggedUuid decodeLayerTaggedUuid(std::string const& value) {
            constexpr std::string_view tag = "#EL#";
            LayerTaggedUuid out;
            out.uuid = value;
            auto second = value.rfind(tag);
            if (second == std::string::npos) return out;
            auto first = value.rfind(tag, second - 1);
            if (first == std::string::npos) return out;
            auto l1 = geode::utils::numFromString<int>(value.substr(first + tag.size(), second - first - tag.size()));
            auto l2 = geode::utils::numFromString<int>(value.substr(second + tag.size()));
            if (l1.isErr() || l2.isErr()) return out;
            out.uuid = value.substr(0, first);
            out.layer1 = l1.unwrap();
            out.layer2 = l2.unwrap();
            out.tagged = true;
            return out;
        }

        void applyEditorLayers(GameObject* obj, int layer1, int layer2) {
            if (!obj) return;
            obj->m_editorLayer = layer1;
            obj->m_editorLayer2 = layer2;
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
    }

    RemoteActionHandler& RemoteActionHandler::get() {
        static RemoteActionHandler instance;
        return instance;
    }

    void RemoteActionHandler::setupHandlers() {
        MusicDownloadManager::sharedState()->addMusicDownloadDelegate(this);

        auto& net = P2PManager::get();

        net.on(proto::Opcode::PlaceObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializePlaceObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing PlaceObjects");
                return;
            }
            handleRemotePlaceObjects(playerId, msg.objects);
        });

        net.on(proto::Opcode::DeleteObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeDeleteObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing DeleteObjects");
                return;
            }
            handleRemoteDeleteObjects(playerId, msg.uuids);
        });

        net.on(proto::Opcode::MoveObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeMoveObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing MoveObjects");
                return;
            }
            handleRemoteMoveObjects(playerId, msg.moves);
        });

        net.on(proto::Opcode::MoveBatch, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeMoveBatch(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing MoveBatch");
                return;
            }
            handleRemoteMoveObjects(playerId, msg.moves);
        });

        net.on(proto::Opcode::TransformObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeTransformObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing TransformObjects");
                return;
            }
            handleRemoteTransformObjects(playerId, msg.transforms);
        });

        net.on(proto::Opcode::ReconcileObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeReconcileObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing ReconcileObjects");
                return;
            }
            handleRemoteReconcileObjects(playerId, msg.reconciles);
        });

        net.on(proto::Opcode::UpdateObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeUpdateObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing UpdateObjects");
                return;
            }
            handleRemoteUpdateObjects(playerId, msg.objects);
        });

        net.on(proto::Opcode::LockObjects, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeLockObjects(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing LockObjects");
                return;
            }
            handleRemoteLockObjects(playerId, msg.uuids, msg.locked);
        });

        net.on(proto::Opcode::UpdateSettings, [this](int playerId, proto::Reader& reader) {
            if (playerId == P2PManager::get().getLocalPlayerId()) return;
            auto msg = proto::deserializeUpdateSettings(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing UpdateSettings");
                return;
            }
            handleRemoteUpdateSettings(playerId, msg.settings);
        });

        net.on(proto::Opcode::SharedDigest, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeSharedDigest(reader);
            if (reader.hasError()) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;

            auto& p2p = P2PManager::get();
            uint32_t revision = p2p.getGlobalRevision();
            if (msg.revision != revision) {
                log::debug(
                    "RemoteActionHandler: ignoring stale shared digest player={} remoteRev={} globalRev={}",
                    playerId, msg.revision, revision
                );
                return;
            }

            auto [localCount, localHash] = computeLevelDigest();
            if (localCount == msg.objectCount && localHash == msg.hash) {
                log::debug(
                    "RemoteActionHandler: GLOBAL HASH match rev={} player={} objects={} hash={}",
                    revision, playerId, localCount, localHash
                );
                return;
            }

            log::warn(
                "RemoteActionHandler: GLOBAL HASH mismatch rev={} player={} host={}/{} remote={}/{} author={}",
                revision, playerId, localCount, localHash, msg.objectCount, msg.hash,
                p2p.getLastGlobalAuthor()
            );

            if (!p2p.getRoomSettings().autoRepair) {
                log::warn("RemoteActionHandler: AUTO REPAIR disabled; leaving rev={} mismatch untouched", revision);
                return;
            }

            if (revision != 0 && s_lastGlobalRecoveryRevision == revision) {
                log::warn(
                    "RemoteActionHandler: divergence persists after recovery for global revision {}; waiting for next edit",
                    revision
                );
                return;
            }
            s_lastGlobalRecoveryRevision = revision;

            int author = p2p.getLastGlobalAuthor();
            if (author <= 0) {
                // Host authored the latest shared edit. Broadcast the host snapshot
                // to every guest so convergence is global, not peer-specific.
                for (auto const& participant : SessionManager::get().getPlayers()) {
                    if (participant.id == SessionManager::get().getLocalPlayerId()) continue;
                    sendFullLevelSyncTo(participant.id);
                }
                log::warn(
                    "RemoteActionHandler: GLOBAL RECOVERY rev={} source=host -> all participants",
                    revision
                );
            } else {
                // A guest authored the latest edit. Ask that author for a snapshot;
                // its SyncLevel stream reaches host and is relayed to every other guest.
                auto request = proto::serializeGlobalSnapshotRequest(revision);
                P2PManager::get().sendTo(author, request, ChannelType::Reliable);
                log::warn(
                    "RemoteActionHandler: GLOBAL RECOVERY rev={} requested snapshot from last author {}",
                    revision, author
                );
            }
        });

        net.on(proto::Opcode::LevelManifest, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeLevelManifest(reader);
            if (reader.hasError() || msg.totalChunks == 0 || msg.chunkIndex >= msg.totalChunks) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Client || playerId != 0) return;

            if (!m_repairManifest.active || m_repairManifest.scanId != msg.scanId) {
                m_repairManifest = {};
                m_repairManifest.active = true;
                m_repairManifest.hostPlayerId = playerId;
                m_repairManifest.scanId = msg.scanId;
                m_repairManifest.totalChunks = msg.totalChunks;
                m_repairManifest.received.assign(msg.totalChunks, false);
            }
            if (m_repairManifest.totalChunks != msg.totalChunks) return;
            if (!m_repairManifest.received[msg.chunkIndex]) {
                m_repairManifest.received[msg.chunkIndex] = true;
                for (auto const& entry : msg.entries) {
                    m_repairManifest.entries.push_back({entry.uuid, entry.hash});
                }
            }

            bool complete = std::all_of(
                m_repairManifest.received.begin(),
                m_repairManifest.received.end(),
                [](bool v) { return v; }
            );
            if (!complete) return;

            auto localEntries = buildLevelManifest();
            std::unordered_map<std::string, std::string> localMap;
            std::unordered_map<std::string, std::string> hostMap;
            for (auto const& entry : localEntries) localMap[entry.uuid] = entry.hash;
            for (auto const& entry : m_repairManifest.entries) hostMap[entry.uuid] = entry.hash;

            std::vector<std::string> missing;
            std::vector<std::string> changed;
            std::vector<std::string> extra;

            for (auto const& [uuid, hostHash] : hostMap) {
                auto it = localMap.find(uuid);
                if (it == localMap.end()) missing.push_back(uuid);
                else if (it->second != hostHash) changed.push_back(uuid);
            }
            for (auto const& [uuid, _] : localMap) {
                if (!hostMap.contains(uuid)) extra.push_back(uuid);
            }

            size_t diffCount = missing.size() + changed.size() + extra.size();
            size_t relativeLimit = std::max<size_t>(64, hostMap.size() / 5);
            if (diffCount > 256 || diffCount > relativeLimit) {
                // v0.5.2: do NOT turn an integrity mismatch into an automatic
                // destructive full-level replacement. Large snapshots were able
                // to reset object-specific state and invalidate collision nodes.
                // Keep using the manifest/targeted repair path below.
                log::warn(
                    "RemoteActionHandler: integrity diff is large ({} objects); using targeted repair instead of automatic SyncLevel",
                    diffCount
                );
            }

            if (!extra.empty()) {
                handleRemoteDeleteObjects(playerId, extra);
            }

            constexpr size_t kRepairRequestBatch = 80;
            size_t missingOffset = 0;
            size_t changedOffset = 0;
            while (missingOffset < missing.size() || changedOffset < changed.size()) {
                std::vector<std::string> missingBatch;
                std::vector<std::string> changedBatch;
                for (size_t i = 0; i < kRepairRequestBatch && missingOffset < missing.size(); ++i) {
                    missingBatch.push_back(missing[missingOffset++]);
                }
                for (size_t i = 0; i < kRepairRequestBatch && changedOffset < changed.size(); ++i) {
                    changedBatch.push_back(changed[changedOffset++]);
                }
                auto request = proto::serializeLevelRepairRequest(
                    msg.scanId, missingBatch, changedBatch
                );
                P2PManager::get().sendTo(0, request, ChannelType::Reliable);
            }

            log::info(
                "RemoteActionHandler: targeted repair requested missing={} changed={} deleted-extra={}",
                missing.size(), changed.size(), extra.size()
            );
            m_repairManifest = {};
        });

        net.on(proto::Opcode::LevelRepairRequest, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeLevelRepairRequest(reader);
            if (reader.hasError()) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;

            auto missingData = getObjectDataForUuids(msg.missing);
            if (!missingData.empty()) {
                auto packet = proto::serializePlaceObjects(missingData);
                P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);
            }

            if (!msg.changed.empty()) {
                auto deletePacket = proto::serializeDeleteObjects(msg.changed);
                P2PManager::get().sendTo(playerId, deletePacket, ChannelType::Reliable);
                auto changedData = getObjectDataForUuids(msg.changed);
                if (!changedData.empty()) {
                    auto placePacket = proto::serializePlaceObjects(changedData);
                    P2PManager::get().sendTo(playerId, placePacket, ChannelType::Reliable);
                }
            }

            log::info(
                "RemoteActionHandler: repair response to player {} missing={} changed={}",
                playerId, msg.missing.size(), msg.changed.size()
            );
        });

        net.on(proto::Opcode::FullResyncRequest, [this](int playerId, proto::Reader& reader) {
            (void)proto::deserializeFullResyncRequest(reader);
            if (reader.hasError()) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;
            log::warn("RemoteActionHandler: full SyncLevel requested by player {}", playerId);
            sendFullLevelSyncTo(playerId);
        });

        net.on(proto::Opcode::InitialSyncRequest, [this](int playerId, proto::Reader&) {
            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;
            log::info("RemoteActionHandler: InitialSyncRequest from player {}", playerId);
            sendFullLevelSyncTo(playerId);
        });

        net.on(proto::Opcode::BulkPasteStart, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeBulkPasteStart(reader);
            if (reader.hasError() || msg.totalChunks == 0 || msg.totalChunks > 4096) return;

            auto& state = s_rawBulkPasteRx[playerId];
            state = {};
            state.active = true;
            state.pasteId = msg.pasteId;
            state.totalChunks = msg.totalChunks;
            state.totalObjects = msg.totalObjects;
            state.withColor = msg.withColor;
            state.noUndo = msg.noUndo;
            state.anchorX = msg.anchorX;
            state.anchorY = msg.anchorY;
            state.dataChunks.resize(msg.totalChunks);
            state.uuidChunks.resize(msg.totalChunks);
            state.received.assign(msg.totalChunks, false);
            log::info("RemoteActionHandler: RAW BulkPasteStart #{} chunks={} objects={}",
                msg.pasteId, msg.totalChunks, msg.totalObjects);
        });

        net.on(proto::Opcode::BulkPasteChunk, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeBulkPasteChunk(reader);
            if (reader.hasError()) return;
            auto it = s_rawBulkPasteRx.find(playerId);
            if (it == s_rawBulkPasteRx.end()) return;
            auto& state = it->second;
            if (!state.active || state.pasteId != msg.pasteId || msg.chunkIndex >= state.totalChunks) return;
            state.dataChunks[msg.chunkIndex] = std::move(msg.data);
            state.uuidChunks[msg.chunkIndex] = std::move(msg.uuids);
            state.received[msg.chunkIndex] = true;
        });

        net.on(proto::Opcode::BulkPasteEnd, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeBulkPasteEnd(reader);
            if (reader.hasError()) return;
            auto it = s_rawBulkPasteRx.find(playerId);
            if (it == s_rawBulkPasteRx.end()) return;
            auto state = std::move(it->second);
            s_rawBulkPasteRx.erase(it);
            if (!state.active || state.pasteId != msg.pasteId) return;
            if (!std::all_of(state.received.begin(), state.received.end(), [](bool v) { return v; })) {
                log::warn("RemoteActionHandler: RAW bulk paste #{} ended with missing chunks", msg.pasteId);
                return;
            }

            std::string raw;
            std::vector<std::string> uuids;
            for (uint32_t i = 0; i < state.totalChunks; ++i) {
                raw += state.dataChunks[i];
                uuids.insert(uuids.end(), state.uuidChunks[i].begin(), state.uuidChunks[i].end());
            }

            auto* editor = getEditorLayer();
            if (!editor || !editor->m_editorUI) {
                log::warn("RemoteActionHandler: RAW bulk paste #{} dropped because editor is unavailable", msg.pasteId);
                return;
            }

            m_processingRemote = true;
            auto* pasted = editor->m_editorUI->pasteObjects(gd::string(raw), state.withColor, state.noUndo);
            m_processingRemote = false;

            if (!pasted) {
                log::warn("RemoteActionHandler: RAW bulk paste #{} returned null", msg.pasteId);
                return;
            }

            GameObject* localAnchor = nullptr;
            for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
                if (obj) { localAnchor = obj; break; }
            }
            float dx = localAnchor ? state.anchorX - localAnchor->getPositionX() : 0.f;
            float dy = localAnchor ? state.anchorY - localAnchor->getPositionY() : 0.f;
            if (localAnchor && (std::abs(dx) > 0.001f || std::abs(dy) > 0.001f)) {
                for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
                    if (!obj) continue;
                    obj->setPosition({obj->getPositionX() + dx, obj->getPositionY() + dy});
                }
                log::info("RemoteActionHandler: RAW bulk paste #{} anchor corrected by ({}, {})", msg.pasteId, dx, dy);
            }

            size_t index = 0;
            for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
                if (!obj) continue;
                if (index < uuids.size()) {
                    auto tagged = decodeLayerTaggedUuid(uuids[index]);
                    if (tagged.tagged) applyEditorLayers(obj, tagged.layer1, tagged.layer2);
                    registerObject(tagged.uuid, obj);
                } else {
                    registerObject(RemoteActionHandler::generateUUID(), obj);
                }
                ++index;
            }

            if (index != uuids.size() || index != state.totalObjects) {
                log::warn(
                    "RemoteActionHandler: RAW bulk paste #{} object count differs: pasted={} uuids={} sender={}",
                    msg.pasteId, index, uuids.size(), state.totalObjects
                );
            } else {
                log::info("RemoteActionHandler: RAW bulk paste #{} reproduced {} objects exactly",
                    msg.pasteId, index);
            }
        });

        net.on(proto::Opcode::GlobalSnapshotRequest, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeGlobalSnapshotRequest(reader);
            if (reader.hasError()) return;
            if (SessionManager::get().getRole() != SessionManager::Role::Client || playerId != 0) return;
            if (msg.revision != P2PManager::get().getGlobalRevision()) {
                log::debug(
                    "RemoteActionHandler: ignored stale GlobalSnapshotRequest rev={} localRev={}",
                    msg.revision, P2PManager::get().getGlobalRevision()
                );
                return;
            }
            sendFullLevelSyncTo(0);
            log::warn(
                "RemoteActionHandler: sent GLOBAL SNAPSHOT rev={} to host for room-wide convergence",
                msg.revision
            );
        });

        net.on(proto::Opcode::MusicChanged, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeMusicChanged(reader);
            if (reader.hasError() || playerId != 0) return;
            auto* editor = getEditorLayer();
            if (!editor || !editor->m_level) return;
            ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);
            editor->m_level->m_songID = msg.songID;
            editor->m_level->m_audioTrack = msg.audioTrack;
            editor->levelSettingsUpdated();
            Notification::create("Host changed music: " + msg.title, NotificationIcon::Info)->show();
            log::info("RemoteActionHandler: host music applied: {}", msg.title);
        });

        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeSyncLevelStart(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing SyncLevelStart");
                return;
            }
            constexpr uint32_t kMaxSyncChunks = 4096;
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
            m_chunkedSync.chunks.resize(msg.totalChunks);
            m_chunkedSync.uuidChunks.clear();
            m_chunkedSync.uuidChunks.resize(msg.totalChunks);
            m_chunkedSync.active = true;
            log::info("RemoteActionHandler: SyncLevelStart received ({} chunks, {} objects)",
                msg.totalChunks, msg.totalObjects);
        });

        net.on(proto::Opcode::SyncLevelChunk, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeSyncLevelChunk(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing SyncLevelChunk");
                return;
            }
            if (!m_chunkedSync.active || playerId != m_chunkedSync.hostPlayerId) return;
            if (msg.chunkIndex < m_chunkedSync.totalChunks) {
                m_chunkedSync.chunks[msg.chunkIndex] = std::string(msg.data.begin(), msg.data.end());
                m_chunkedSync.uuidChunks[msg.chunkIndex] = msg.uuids;
                log::info("RemoteActionHandler: SyncLevelChunk received: {}/{}",
                    msg.chunkIndex + 1, m_chunkedSync.totalChunks);
            }
        });

        net.on(proto::Opcode::SyncLevelEnd, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeSyncLevelEnd(reader);
            if (reader.hasError()) {
                log::error("RemoteActionHandler: Error deserializing SyncLevelEnd");
                return;
            }
            if (!m_chunkedSync.active || playerId != m_chunkedSync.hostPlayerId) return;

            // Reconstruct objectsString with a hard compressed-size ceiling.
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
            
            std::string objectsString = "";
            if (!compressedString.empty()) {
                geode::ByteVector bytes(compressedString.begin(), compressedString.end());
                if (auto unzip = geode::utils::file::Unzip::create(bytes)) {
                    if (auto extracted = unzip.unwrap().extract("level.txt")) {
                        objectsString = std::string(extracted.unwrap().begin(), extracted.unwrap().end());
                    } else {
                        log::error("RemoteActionHandler: Failed to extract level.txt from sync payload");
                    }
                } else {
                    log::error("RemoteActionHandler: Failed to create unzipper for sync payload");
                }
            }
            
            // Reconstruct uuids
            std::vector<std::string> uuids;
            uuids.reserve(m_chunkedSync.totalObjects);
            for (auto const& uuidChunk : m_chunkedSync.uuidChunks) {
                uuids.insert(uuids.end(), uuidChunk.begin(), uuidChunk.end());
            }

            auto* editor = getEditorLayer();
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
            }

            m_chunkedSync.active = false;
            m_chunkedSync.chunks.clear();
            m_chunkedSync.uuidChunks.clear();
        });
    }

    std::vector<RemoteActionHandler::IntegrityEntry> RemoteActionHandler::buildLevelManifest() const {
        std::vector<IntegrityEntry> entries;
        auto* editor = getEditorLayer();
        if (!editor || !editor->m_objects) return entries;

        entries.reserve(editor->m_objects->count());
        for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
            if (!obj) continue;
            auto uuid = getUUIDForObject(obj);
            if (uuid.empty()) continue;
            std::string save = obj->getSaveString(editor);
            if (obj->m_objectID == 31) {
                auto ordered = ActionSerializer::parseSaveStringOrdered(save);
                std::vector<std::pair<std::string, std::string>> normalized;
                normalized.reserve(ordered.size());
                for (auto const& pair : ordered) {
                    if (pair.first == "kA21" || pair.first == "kA9" || pair.first == "93") continue;
                    normalized.push_back(pair);
                }
                save = ActionSerializer::buildSaveStringOrdered(normalized);
            }
            save += "|mpedit-editor-layers:" + std::to_string(obj->m_editorLayer)
                + ":" + std::to_string(obj->m_editorLayer2);
            entries.push_back({uuid, stableIntegrityHash(save)});
        }
        std::sort(entries.begin(), entries.end(), [](auto const& a, auto const& b) {
            return a.uuid < b.uuid;
        });
        return entries;
    }

    std::pair<uint32_t, std::string> RemoteActionHandler::computeLevelDigest() const {
        auto entries = buildLevelManifest();
        std::string material;
        material.reserve(entries.size() * 48);
        for (auto const& entry : entries) {
            material += entry.uuid;
            material.push_back('=');
            material += entry.hash;
            material.push_back(';');
        }
        return {static_cast<uint32_t>(entries.size()), stableIntegrityHash(material)};
    }

    std::vector<ActionSerializer::ObjectData> RemoteActionHandler::getObjectDataForUuids(
        std::vector<std::string> const& uuids) const
    {
        std::vector<ActionSerializer::ObjectData> result;
        auto* editor = getEditorLayer();
        if (!editor || !editor->m_objects || uuids.empty()) return result;

        std::unordered_set<std::string> wanted(uuids.begin(), uuids.end());
        result.reserve(wanted.size());
        for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
            if (!obj) continue;
            auto uuid = getUUIDForObject(obj);
            if (uuid.empty() || !wanted.contains(uuid)) continue;
            result.push_back(ActionSerializer::extractObjectData(obj, uuid));
        }
        return result;
    }

    void RemoteActionHandler::sendLevelDigestTo(int playerId) {
        auto [count, hash] = computeLevelDigest();
        uint32_t revision = P2PManager::get().getGlobalRevision();
        auto packet = proto::serializeSharedDigest(revision, count, hash);
        P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);
        log::debug(
            "RemoteActionHandler: sent GLOBAL HASH rev={} player={} objects={} hash={}",
            revision, playerId, count, hash
        );
    }

    void RemoteActionHandler::sendLevelManifestTo(int playerId) {
        auto entries = buildLevelManifest();
        static uint32_t s_scanId = 1;
        uint32_t scanId = s_scanId++;
        constexpr size_t kEntriesPerChunk = 100;
        uint32_t totalChunks = static_cast<uint32_t>(
            std::max<size_t>(1, (entries.size() + kEntriesPerChunk - 1) / kEntriesPerChunk)
        );

        for (uint32_t chunk = 0; chunk < totalChunks; ++chunk) {
            size_t begin = static_cast<size_t>(chunk) * kEntriesPerChunk;
            size_t end = std::min(entries.size(), begin + kEntriesPerChunk);
            std::vector<proto::LevelManifestEntry> wireEntries;
            wireEntries.reserve(end - begin);
            for (size_t i = begin; i < end; ++i) {
                wireEntries.push_back({entries[i].uuid, entries[i].hash});
            }
            auto packet = proto::serializeLevelManifest(scanId, chunk, totalChunks, wireEntries);
            P2PManager::get().sendTo(playerId, packet, ChannelType::Reliable);
        }

        log::info(
            "RemoteActionHandler: sent integrity manifest scan={} player={} objects={} chunks={}",
            scanId, playerId, entries.size(), totalChunks
        );
    }

    void RemoteActionHandler::clearHandlers() {
        MusicDownloadManager::sharedState()->removeMusicDownloadDelegate(this);
        clearMappings();
        m_expectedUuids.clear();
        m_objectLocks.clear();
        m_pendingSync.reset();
        m_initialSyncCompleted = false;
        m_chunkedSync.active = false;
        m_chunkedSync.chunks.clear();
        m_chunkedSync.uuidChunks.clear();
        m_repairManifest = {};
        P2PManager::get().clearHandlers();
    }

    static LevelEditorLayer* findEditorLayer(CCNode* parent) {
        if (!parent) return nullptr;
        if (auto* editor = typeinfo_cast<LevelEditorLayer*>(parent)) {
            return editor;
        }
        if (parent->getChildren()) {
            for (auto* child : CCArrayExt<CCNode*>(parent->getChildren())) {
                if (auto* editor = findEditorLayer(child)) {
                    return editor;
                }
            }
        }
        return nullptr;
    }

    bool isEditorReady(LevelEditorLayer* editor) {
        return editor && editor->m_editorUI;
    }

    LevelEditorLayer* RemoteActionHandler::getEditorLayer() const {
        if (m_editorForInit) {
            return m_editorForInit;
        }

        if (auto* editor = LevelEditorLayer::get()) {
            if (isEditorReady(editor)) {
                return editor;
            }
            log::debug("RemoteActionHandler: LevelEditorLayer::get() returned an unready editor, falling through");
        }

        auto* dir = CCDirector::sharedDirector();
        if (auto* scene = dir->getRunningScene()) {
            if (auto* editor = findEditorLayer(scene)) {
                if (isEditorReady(editor)) {
                    return editor;
                }
            }
        }
        if (auto* nextScene = dir->getNextScene()) {
            if (auto* editor = findEditorLayer(nextScene)) {
                log::debug("RemoteActionHandler: editor resolved via getNextScene() (ready={})",
                    isEditorReady(editor));
                return editor;
            }
        }
        return nullptr;
    }

    void RemoteActionHandler::applyPendingSync() {
        if (!m_pendingSync) {
            log::debug("RemoteActionHandler: applyPendingSync called but no pending sync");
            return;
        }
        auto sync = m_pendingSync.value();
        m_pendingSync.reset();
        log::info("RemoteActionHandler: Applying pending sync (objectsStringLen={}, uuids={}, settingsLen={}, locks={})",
            sync.objectsString.size(), sync.uuids.size(), sync.settings.saveString.size(), sync.locks.size());
        LevelEditorLayer* override = m_editorForInit;
        handleRemoteSyncLevel(sync.playerId, sync.objectsString, sync.uuids, sync.settings, sync.locks, true);
        m_editorForInit = nullptr;
        (void)override;
    }

    void RemoteActionHandler::handleRemotePlaceObjects(
        int playerId, 
        std::vector<ActionSerializer::ObjectData> const& objects
    ) {
        auto* editor = getEditorLayer();
        if (!editor) {
            log::warn("RemoteActionHandler: No editor layer found");
            return;
        }

        if (editor->m_playbackMode != PlaybackMode::Not) {
            QueuedAction qa;
            qa.type = QueuedAction::Type::Place;
            qa.playerId = playerId;
            qa.placeObjects = objects;
            m_playtestQueue.push_back(std::move(qa));
            return;
        }

        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        std::unordered_set<std::string> processedUUIDs;

        for (size_t i = 0; i < objects.size(); i++) {
            auto const& objData = objects[i];
            if (processedUUIDs.count(objData.uuid)) continue;
            processedUUIDs.insert(objData.uuid);
            
            if (!objData.saveString.empty()) {
                auto newObjs = createObjectsFromSaveStringRobust(editor, objData.saveString);
                if (!newObjs.empty()) {
                    GameObject* obj = nullptr;
                    for (auto* createdObj : newObjs) {
                        if (createdObj->m_objectID == objData.objectID) {
                            if (objData.objectID == 747) {
                                if (auto* tp = typeinfo_cast<TeleportPortalObject*>(createdObj)) {
                                    if (!tp->m_isYellowPortal) {
                                        obj = createdObj;
                                        break;
                                    }
                                }
                            } else {
                                obj = createdObj;
                                break;
                            }
                        }
                    }
                    if (!obj) obj = newObjs.front();

                    // The sender coordinates are authoritative. Explicitly apply
                    // them even when GD normalizes the save string during object
                    // creation, preventing remote placements from drifting.
                    obj->setPosition({objData.x, objData.y});
                    
                    if (obj->m_objectID == 31) {
                        if (auto* startPos = typeinfo_cast<StartPosObject*>(obj)) {
                            startPos->loadSettingsFromString(objData.saveString);
                        }
                    }

                    applyTransformSafe(obj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);
                    applyEditorLayers(obj, objData.editorLayer, objData.editorLayer2);
                    registerObject(objData.uuid, obj);
                    
                    if (obj->m_objectID == 31) {
                        updateStartPosCache(obj);
                    }

                    log::debug("RemoteActionHandler: Placed object {} via saveString (uuid={})", objData.objectID, objData.uuid);
                    
                    if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
                        if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                            for (size_t j = 0; j < objects.size(); j++) {
                                auto const& orangeData = objects[j];
                                if (orangeData.objectID == 749 && !processedUUIDs.count(orangeData.uuid)) {
                                    auto* orange = tpPortal->m_orangePortal;
                                    orange->setPositionOverride({orangeData.x, orangeData.y});
                                    applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,
                                                       orangeData.scaleY, orangeData.flipX, orangeData.flipY);
                                    applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);
                                    applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);
                                registerObject(orangeData.uuid, orange);
                                    processedUUIDs.insert(orangeData.uuid);
                                    break;
                                }
                            }
                        }
                    }
                    continue;
                }
            }

            auto* obj = editor->createObject(objData.objectID, {objData.x, objData.y}, true);
            if (!obj) {
                log::warn("RemoteActionHandler: Failed to create object ID {}", objData.objectID);
                continue;
            }

            applyTransformSafe(obj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);
            obj->m_editorLayer = objData.editorLayer;
            obj->m_editorLayer2 = objData.editorLayer2;

            registerObject(objData.uuid, obj);
            log::debug("RemoteActionHandler: Placed object {} (uuid={})", objData.objectID, objData.uuid);
            
            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
                if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                    for (size_t j = 0; j < objects.size(); j++) {
                        auto const& orangeData = objects[j];
                        if (orangeData.objectID == 749 && !processedUUIDs.count(orangeData.uuid)) {
                            auto* orange = tpPortal->m_orangePortal;
                            orange->setPositionOverride({orangeData.x, orangeData.y});
                            applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,
                                               orangeData.scaleY, orangeData.flipX, orangeData.flipY);
                            registerObject(orangeData.uuid, orange);
                            processedUUIDs.insert(orangeData.uuid);
                            break;
                        }
                    }
                }
            }
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteDeleteObjects(
        int playerId, 
        std::vector<std::string> const& uuids
    ) {
        auto* editor = getEditorLayer();
        if (!editor) return;

        if (editor->m_playbackMode != PlaybackMode::Not) {
            QueuedAction qa;
            qa.type = QueuedAction::Type::Delete;
            qa.playerId = playerId;
            qa.deleteUuids = uuids;
            m_playtestQueue.push_back(std::move(qa));
            return;
        }

        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        for (auto& uuid : uuids) {
            auto* obj = getObjectByUUID(uuid);
            if (!obj) {
                log::warn("RemoteActionHandler: Object with uuid '{}' not found for deletion", uuid);
                continue;
            }

            if (auto* editorUI = editor->m_editorUI) {
                if (editorUI->m_selectedObject == obj || (editorUI->m_selectedObjects && editorUI->m_selectedObjects->containsObject(obj))) {
                    editorUI->deselectObject(obj);
                    if (editorUI->m_selectedObject == obj) {
                        editorUI->m_selectedObject = nullptr;
                    }
                    if (editorUI->m_selectedObjects && editorUI->m_selectedObjects->containsObject(obj)) {
                        editorUI->m_selectedObjects->removeObject(obj);
                    }
                }
            }

            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
                if (tpPortal->m_isYellowPortal) {
                    continue;
                }
            }

            pruneObjectFromHistory(editor, obj);
            
            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
                if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                    auto orangeUuid = getUUIDForObject(tpPortal->m_orangePortal);
                    auto* orange = tpPortal->m_orangePortal;
                    tpPortal->m_orangePortal = nullptr;
                    editor->removeObject(orange, true);
                    if (!orangeUuid.empty()) unregisterObject(orangeUuid);
                }
            }

            editor->removeObject(obj, true);
            unregisterObject(uuid);
            log::debug("RemoteActionHandler: Deleted object (uuid={})", uuid);
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteMoveObjects(
        int playerId, 
        std::vector<ActionSerializer::MoveData> const& moves
    ) {
        auto* editor = getEditorLayer();
        if (!editor) return;

        if (editor->m_playbackMode != PlaybackMode::Not) {
            QueuedAction qa;
            qa.type = QueuedAction::Type::Move;
            qa.playerId = playerId;
            qa.moveData = moves;
            m_playtestQueue.push_back(std::move(qa));
            return;
        }

        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        for (auto& move : moves) {
            auto* obj = getObjectByUUID(move.uuid);
            if (!obj) {
                log::warn("RemoteActionHandler: Object with uuid '{}' not found for move", move.uuid);
                continue;
            }

            auto pos = obj->getPosition();
            obj->setPosition({pos.x + move.dx, pos.y + move.dy});
            editor->updateObjectSection(obj);
            
            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
                if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                    editor->updateObjectSection(tpPortal->m_orangePortal);
                }
            }

            log::debug("RemoteActionHandler: Moved object (uuid={}) by ({}, {})", move.uuid, move.dx, move.dy);
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteTransformObjects(
        int playerId,
        std::vector<ActionSerializer::TransformData> const& transforms
    ) {
        auto* editor = getEditorLayer();
        if (!editor) return;

        if (editor->m_playbackMode != PlaybackMode::Not) {
            QueuedAction qa;
            qa.type = QueuedAction::Type::Transform;
            qa.playerId = playerId;
            qa.transformData = transforms;
            m_playtestQueue.push_back(std::move(qa));
            return;
        }

        log::debug("RemoteActionHandler: applying remote transform (playerId={}, n={})", playerId, transforms.size());
        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        for (auto& t : transforms) {
            auto* obj = getObjectByUUID(t.uuid);
            if (!obj) {
                log::warn("RemoteActionHandler: Object with uuid '{}' not found for transform", t.uuid);
                continue;
            }

            applyTransformSafe(obj, t.rotation, t.scaleX, t.scaleY, t.flipX, t.flipY);

            log::debug("RemoteActionHandler: transformed object (uuid={}..., rot={:.1f}, flipX={}, flipY={})",
                t.uuid.substr(0, 8), t.rotation, t.flipX, t.flipY);
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteReconcileObjects(
        int playerId,
        std::vector<ActionSerializer::ReconcileData> const& reconciles
    ) {
        auto* editor = getEditorLayer();
        if (!editor) return;

        if (editor->m_playbackMode != PlaybackMode::Not) {
            QueuedAction qa;
            qa.type = QueuedAction::Type::Reconcile;
            qa.playerId = playerId;
            qa.reconcileData = reconciles;
            m_playtestQueue.push_back(std::move(qa));
            return;
        }

        log::debug("RemoteActionHandler: applying remote reconcile (playerId={}, n={})", playerId, reconciles.size());
        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        for (auto& r : reconciles) {
            auto* obj = getObjectByUUID(r.uuid);
            if (!obj) {
                log::warn("RemoteActionHandler: Object with uuid '{}' not found for reconcile", r.uuid);
                continue;
            }

            // Set absolute position
            obj->setPosition(cocos2d::CCPoint{r.x, r.y});
            
            // Set absolute transform
            applyTransformSafe(obj, r.rotation, r.scaleX, r.scaleY, r.flipX, r.flipY);
            editor->updateObjectSection(obj);

            // Reconcile makes any pending transforms/moves in locked state stale
            // (Removed lockedSaveStrings handling)

            log::debug("RemoteActionHandler: reconciled object (uuid={}..., pos=({}, {}), rot={:.1f})",
                r.uuid.substr(0, 8), r.x, r.y, r.rotation);
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteUpdateObjects(
        int playerId, 
        std::vector<ActionSerializer::ObjectData> const& objects
    ) {
        auto* editor = getEditorLayer();
        if (!editor) return;

        if (editor->m_playbackMode != PlaybackMode::Not) {
            QueuedAction qa;
            qa.type = QueuedAction::Type::Update;
            qa.playerId = playerId;
            qa.updateObjects = objects;
            m_playtestQueue.push_back(std::move(qa));
            return;
        }

        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);
        std::unordered_set<std::string> processedUUIDs;

        for (size_t i = 0; i < objects.size(); i++) {
            auto const& objData = objects[i];
            auto* oldObj = getObjectByUUID(objData.uuid);
            if (!oldObj) {
                log::warn("RemoteActionHandler: Object to update not found (uuid={})", objData.uuid);
                continue;
            }

            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(oldObj)) {
                if (tpPortal->m_isYellowPortal) {
                    tpPortal->setPositionOverride({objData.x, objData.y});
                    applyTransformSafe(oldObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);
                    applyEditorLayers(oldObj, objData.editorLayer, objData.editorLayer2);
                    log::debug("RemoteActionHandler: Updated orange portal directly without recreation");
                    continue;
                }
            }

            auto* editorUI = editor->m_editorUI;
            bool wasSelected = false;
            if (editorUI && (editorUI->m_selectedObject == oldObj || (editorUI->m_selectedObjects && editorUI->m_selectedObjects->containsObject(oldObj)))) {
                wasSelected = true;
                editorUI->deselectObject(oldObj);
                if (editorUI->m_selectedObject == oldObj) {
                    editorUI->m_selectedObject = nullptr;
                }
                if (editorUI->m_selectedObjects && editorUI->m_selectedObjects->containsObject(oldObj)) {
                    editorUI->m_selectedObjects->removeObject(oldObj);
                }
            }

            pruneObjectFromHistory(editor, oldObj);
            
            std::string orangeOldUuid;
            ActionSerializer::ObjectData oldOrangeData;
            bool hadOldOrange = false;
            
            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(oldObj)) {
                if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                    orangeOldUuid = getUUIDForObject(tpPortal->m_orangePortal);
                    oldOrangeData = ActionSerializer::extractObjectData(tpPortal->m_orangePortal, orangeOldUuid);
                    hadOldOrange = true;
                    
                    auto* orange = tpPortal->m_orangePortal;
                    tpPortal->m_orangePortal = nullptr;
                    editor->removeObject(orange, true);
                    if (!orangeOldUuid.empty()) unregisterObject(orangeOldUuid);
                }
            }

            auto objDataCopy = objData;
            ActionSerializer::injectLocalStartPosState(objDataCopy, oldObj);

            editor->removeObject(oldObj, true);
            unregisterObject(objDataCopy.uuid);

            auto newObjs = createObjectsFromSaveStringRobust(editor, objDataCopy.saveString);
            if (!newObjs.empty()) {
                GameObject* newObj = nullptr;
                for (auto* createdObj : newObjs) {
                    if (createdObj->m_objectID == objData.objectID) {
                        if (objData.objectID == 747) {
                            if (auto* tp = typeinfo_cast<TeleportPortalObject*>(createdObj)) {
                                if (!tp->m_isYellowPortal) {
                                    newObj = createdObj;
                                    break;
                                }
                            }
                        } else {
                            newObj = createdObj;
                            break;
                        }
                    }
                }
                if (!newObj) newObj = newObjs.front();
                
                if (newObj->m_objectID == 31) {
                    if (auto* startPos = typeinfo_cast<StartPosObject*>(newObj)) {
                        startPos->loadSettingsFromString(objDataCopy.saveString);
                    }
                }

                applyTransformSafe(newObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);
                applyEditorLayers(newObj, objData.editorLayer, objData.editorLayer2);
                registerObject(objData.uuid, newObj);
                
                if (newObj->m_objectID == 31) {
                    updateStartPosCache(newObj);
                }

                log::debug("RemoteActionHandler: Updated object {} via saveString", objData.uuid);
                
                if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(newObj)) {
                    if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                        bool foundInData = false;
                        for (size_t j = 0; j < objects.size(); j++) {
                            auto const& orangeData = objects[j];
                            if (orangeData.objectID == 749 && !processedUUIDs.count(orangeData.uuid)) {
                                auto* orange = tpPortal->m_orangePortal;
                                orange->setPositionOverride({orangeData.x, orangeData.y});
                                applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,
                                                   orangeData.scaleY, orangeData.flipX, orangeData.flipY);
                                applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);
                                registerObject(orangeData.uuid, orange);
                                processedUUIDs.insert(orangeData.uuid);
                                foundInData = true;
                                break;
                            }
                        }
                        if (!foundInData && hadOldOrange) {
                            auto* orange = tpPortal->m_orangePortal;
                            orange->setPositionOverride({oldOrangeData.x, oldOrangeData.y});
                            applyTransformSafe(orange, oldOrangeData.rotation, oldOrangeData.scaleX,
                                               oldOrangeData.scaleY, oldOrangeData.flipX, oldOrangeData.flipY);
                            if (!orangeOldUuid.empty()) {
                                registerObject(orangeOldUuid, orange);
                            }
                        }
                    }
                }

                if (wasSelected && editorUI) {
                    editorUI->selectObject(newObj, true);
                }
            } else {
                auto* fallbackObj = editor->createObject(objData.objectID, {objData.x, objData.y}, true);
                if (fallbackObj) {
                    applyTransformSafe(fallbackObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);
                    fallbackObj->m_editorLayer = objData.editorLayer;
                    fallbackObj->m_editorLayer2 = objData.editorLayer2;
                    registerObject(objData.uuid, fallbackObj);
                    log::warn("RemoteActionHandler: Updated object {} via fallback createObject", objData.uuid);
                    
                    if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(fallbackObj)) {
                        if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                            bool foundInData = false;
                            for (size_t j = 0; j < objects.size(); j++) {
                                auto const& orangeData = objects[j];
                                if (orangeData.objectID == 749 && !processedUUIDs.count(orangeData.uuid)) {
                                    auto* orange = tpPortal->m_orangePortal;
                                    orange->setPositionOverride({orangeData.x, orangeData.y});
                                    applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,
                                                       orangeData.scaleY, orangeData.flipX, orangeData.flipY);
                                    applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);
                                    applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);
                                registerObject(orangeData.uuid, orange);
                                    processedUUIDs.insert(orangeData.uuid);
                                    foundInData = true;
                                    break;
                                }
                            }
                            if (!foundInData && hadOldOrange) {
                                auto* orange = tpPortal->m_orangePortal;
                                orange->setPositionOverride({oldOrangeData.x, oldOrangeData.y});
                                applyTransformSafe(orange, oldOrangeData.rotation, oldOrangeData.scaleX,
                                                   oldOrangeData.scaleY, oldOrangeData.flipX, oldOrangeData.flipY);
                                if (!orangeOldUuid.empty()) {
                                    registerObject(orangeOldUuid, orange);
                                }
                            }
                        }
                    }

                    if (wasSelected && editorUI) {
                        editorUI->selectObject(fallbackObj, true);
                    }
                } else {
                    log::error("RemoteActionHandler: Failed to create updated object from saveString AND fallback");
                }
            }
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteLockObjects(
        int playerId, 
        std::vector<std::string> const& uuids, 
        bool locked
    ) {
        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        if (locked) {
            auto* editor = getEditorLayer();
            auto* editorUI = editor ? editor->m_editorUI : nullptr;
            for (auto& uuid : uuids) {
                // Set lock timeout to 3 seconds. It will be refreshed by cursor_update or explicitly released
                m_objectLocks[uuid] = LockInfo { playerId, 3.0f }; 
                
                if (editorUI) {
                    auto* obj = getObjectByUUID(uuid);
                    if (obj) {
                        if (editorUI->m_selectedObject == obj || (editorUI->m_selectedObjects && editorUI->m_selectedObjects->containsObject(obj))) {
                            editorUI->deselectObject(obj);
                            if (editorUI->m_selectedObject == obj) {
                                editorUI->m_selectedObject = nullptr;
                            }
                            if (editorUI->m_selectedObjects && editorUI->m_selectedObjects->containsObject(obj)) {
                                editorUI->m_selectedObjects->removeObject(obj);
                            }
                        }
                    }
                }
            }
        } else {
            for (auto& uuid : uuids) {
                auto it = m_objectLocks.find(uuid);
                if (it != m_objectLocks.end() && it->second.playerId == playerId) {
                    m_objectLocks.erase(it);
                }
            }
        }

        m_processingRemote = false;
    }

    void RemoteActionHandler::handleRemoteSyncLevel(
        int playerId,
        std::string const& objectsString,
        std::vector<std::string> const& uuids,
        ActionSerializer::LevelSettingsData const& settings,
        std::vector<ActionSerializer::LockData> const& locks,
        bool isPendingSync
    ) {
        log::info("RemoteActionHandler: sync_level received (playerId={}, objectsStringLen={}, uuids={}, settingsLen={}, locks={}, pending={})",
            playerId, objectsString.size(), uuids.size(), settings.saveString.size(), locks.size(), isPendingSync);

        auto* editor = getEditorLayer();
        if (!editor) {
            log::info("RemoteActionHandler: Editor not ready yet, opening editor with settings-only level string");

            std::string levelString = settings.saveString;
            m_expectedUuids = uuids;

            m_pendingSync = PendingSync {
                playerId,
                objectsString,
                uuids,
                settings,
                locks
            };

            auto* level = GJGameLevel::create();
            level->m_levelName = "Multiplayer Session";
            level->m_levelType = GJLevelType::Editor;
            level->m_levelString = levelString;
            level->m_audioTrack = settings.audioTrack;
            level->m_songID = settings.songID;
            level->m_levelLength = settings.levelLength;

            auto* scene = LevelEditorLayer::scene(level, false);
            if (!scene) {
                log::error("RemoteActionHandler: LevelEditorLayer::scene returned null — cannot open editor for sync!");
                m_pendingSync.reset();
                return;
            }
            cocos2d::CCDirector::sharedDirector()->pushScene(scene);

            if (MultiplayerPopup::s_instance) {
                MultiplayerPopup::s_instance->forceClose();
            }

            log::info("RemoteActionHandler: Pushed editor scene; pending sync will apply in init() (hasPending={})",
                m_pendingSync.has_value());
            return;
        }

        if (!editor->m_editorUI || !editor->m_objectLayer) {
            log::warn("RemoteActionHandler: Editor found but not fully initialized (editorUI={} objectLayer={}) — deferring as pending sync",
                static_cast<void*>(editor->m_editorUI), static_cast<void*>(editor->m_objectLayer));
            m_pendingSync = PendingSync { playerId, objectsString, uuids, settings, locks };
            return;
        }

        log::info("RemoteActionHandler: Editor ready (m_objects count before sync = {})",
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
        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        if (auto* editorUI = editor->m_editorUI) {
            editorUI->deselectAll();
        }

        if (!isPendingSync) {
            if (editor->m_objects) {
                auto copy = cocos2d::CCArray::create();
                copy->addObjectsFromArray(editor->m_objects);
                
                for (auto* obj : CCArrayExt<GameObject*>(copy)) {
                    if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
                        if (!tpPortal->m_isYellowPortal) {
                            tpPortal->m_orangePortal = nullptr;
                        }
                    }
                }

                for (auto* obj : CCArrayExt<GameObject*>(copy)) {
                    if (editor->m_objects->containsObject(obj)) {
                        editor->removeObject(obj, true);
                    }
                }
            }
            if (editor->m_undoObjects) editor->m_undoObjects->removeAllObjects();
            if (editor->m_redoObjects) editor->m_redoObjects->removeAllObjects();
        }
        clearMappings();
        m_expectedUuids.clear();

        log::info("RemoteActionHandler: Syncing level state ({} objects) from player {} (pending={})",
            uuids.size(), playerId, isPendingSync);

        applyLevelSettings(editor, settings);

        if (!objectsString.empty()) {
            auto newObjs = createObjectsFromSaveStringRobust(editor, objectsString);
            log::info("RemoteActionHandler: Spawned {} objects from objectsString (len={})",
                newObjs.size(), objectsString.size());
            // Match each authoritative serialized record to the recreated object
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

            size_t fallbackIndex = uuids.size();            for (auto* obj : newObjs) {
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
            }
        } else if (!uuids.empty()) {
            log::warn("RemoteActionHandler: sync_level had {} uuids but empty objectsString — "
                      "objects cannot be spawned (host sent no object data)", uuids.size());
        }

        m_objectLocks.clear();
        for (auto const& lock : locks) {
            m_objectLocks[lock.uuid] = LockInfo { lock.playerId, lock.timeLeft };
        }

        editor->levelSettingsUpdated();

        geode::Notification::create("Level Synced!", geode::NotificationIcon::Success)->show();

        m_initialSyncCompleted = true;
        m_processingRemote = false;
        log::info("RemoteActionHandler: sync_level complete (final m_objects count = {})",
            editor->m_objects ? editor->m_objects->count() : 0);
    }

    void RemoteActionHandler::updateLocks(float dt) {
        for (auto it = m_objectLocks.begin(); it != m_objectLocks.end(); ) {
            it->second.timeLeft -= dt;
            if (it->second.timeLeft <= 0.f) {
                it = m_objectLocks.erase(it);
            } else {
                ++it;
            }
        }
    }

    void RemoteActionHandler::registerObject(std::string const& uuid, GameObject* obj) {
        // Clean up any existing mapping for this object (prevent orphaned UUID→object entries)
        auto existingUuidIt = m_objectToUuid.find(obj);
        if (existingUuidIt != m_objectToUuid.end()) {
            m_uuidToObject.erase(existingUuidIt->second);
        }
        // Clean up any existing mapping for this UUID (prevent orphaned object→UUID entries)
        auto existingObjIt = m_uuidToObject.find(uuid);
        if (existingObjIt != m_uuidToObject.end()) {
            m_objectToUuid.erase(existingObjIt->second);
        }
        m_uuidToObject[uuid] = obj;
        m_objectToUuid[obj] = uuid;
    }

    void RemoteActionHandler::unregisterObject(std::string const& uuid) {
        auto it = m_uuidToObject.find(uuid);
        if (it != m_uuidToObject.end()) {
            GameObject* obj = it->second;
            m_objectToUuid.erase(obj);
            m_uuidToObject.erase(it);
        }
    }

    void RemoteActionHandler::pruneObjectFromHistory(LevelEditorLayer* editor, GameObject* obj) {
        if (!editor || !obj) return;

        auto pruneList = [](cocos2d::CCArray* list, GameObject* target) {
            if (!list) return;
            std::vector<cocos2d::CCObject*> toRemove;
            for (auto* itemObj : geode::cocos::CCArrayExt<cocos2d::CCObject*>(list)) {
                if (!itemObj) continue;
                auto* item = static_cast<UndoObject*>(itemObj);
                
                // Check m_objects array
                if (item->m_objects) {
                    if (item->m_objects->containsObject(target)) {
                        item->m_objects->removeObject(target);
                    }
                    if (item->m_objects->count() == 0) {
                        toRemove.push_back(item);
                        continue;
                    }
                }
                
                // Check m_objectCopy safely (m_objectCopy is already GameObjectCopy* in bindings)
                if (item->m_objectCopy && item->m_objectCopy->m_object && item->m_objectCopy->m_object == target) {
                    toRemove.push_back(item);
                }
            }
            for (auto* item : toRemove) {
                list->removeObject(item);
            }
        };

        pruneList(editor->m_undoObjects, obj);
        pruneList(editor->m_redoObjects, obj);
    }

    GameObject* RemoteActionHandler::getObjectByUUID(std::string const& uuid) const {
        auto it = m_uuidToObject.find(uuid);
        if (it != m_uuidToObject.end()) {
            auto* obj = it->second;
            if (auto* editor = LevelEditorLayer::get()) {
                if (editor->m_objects && editor->m_objects->containsObject(obj)) {
                    return obj;
                }
            }
        }
        return nullptr;
    }

    std::string RemoteActionHandler::getUUIDForObject(GameObject* obj) const {
        if (!obj) return "";
        auto it = m_objectToUuid.find(obj);
        return it != m_objectToUuid.end() ? it->second : "";
    }

    std::string RemoteActionHandler::getOrCreateUUID(GameObject* obj) {
        if (!obj) return "";
        auto it = m_objectToUuid.find(obj);
        if (it != m_objectToUuid.end()) {
            return it->second;
        }
        auto uuid = generateUUID();
        registerObject(uuid, obj);
        return uuid;
    }

    std::string RemoteActionHandler::generateUUID() {
        static std::mt19937 rng(std::random_device{}());
        static std::uniform_int_distribution<int> dist(0, 0xFFFF);

        int playerId = SessionManager::get().getLocalPlayerId();
        int counter = s_uuidCounter++;
        int random = dist(rng);

        std::ostringstream ss;
        ss << std::hex << std::setfill('0')
           << std::setw(4) << playerId << "-"
           << std::setw(8) << counter << "-"
           << std::setw(4) << random;

        return ss.str();
    }

    void RemoteActionHandler::clearMappings() {
        m_uuidToObject.clear();
        m_objectToUuid.clear();
        m_objectLocks.clear();
        m_preSelectSaveStrings.clear();
        m_pendingPlacements.clear();
        m_playtestQueue.clear();
        m_initialSyncCompleted = false;
    }

    void RemoteActionHandler::queueObjectForPlacement(std::string const& uuid, GameObject* obj) {
        if (!obj || uuid.empty()) return;
        m_pendingPlacements.push_back(PendingPlacement { uuid, geode::Ref<GameObject>(obj) });
    }

    bool RemoteActionHandler::isObjectPendingPlacement(GameObject* obj) const {
        if (!obj) return false;
        for (auto const& p : m_pendingPlacements) {
            if (p.obj == obj) return true;
        }
        return false;
    }

    void RemoteActionHandler::flushPlaytestQueue() {
        if (m_playtestQueue.empty()) return;
        
        log::info("RemoteActionHandler: Flushing {} queued playtest actions", m_playtestQueue.size());
        
        auto queueCopy = std::move(m_playtestQueue);
        m_playtestQueue.clear();
        
        for (auto& qa : queueCopy) {
            switch (qa.type) {
                case QueuedAction::Type::Place:     handleRemotePlaceObjects(qa.playerId, qa.placeObjects); break;
                case QueuedAction::Type::Delete:    handleRemoteDeleteObjects(qa.playerId, qa.deleteUuids); break;
                case QueuedAction::Type::Move:      handleRemoteMoveObjects(qa.playerId, qa.moveData); break;
                case QueuedAction::Type::Transform: handleRemoteTransformObjects(qa.playerId, qa.transformData); break;
                case QueuedAction::Type::Reconcile: handleRemoteReconcileObjects(qa.playerId, qa.reconcileData); break;
                case QueuedAction::Type::Update:    handleRemoteUpdateObjects(qa.playerId, qa.updateObjects); break;
            }
        }
    }

    void RemoteActionHandler::flushPendingPlacements() {
        if (m_pendingPlacements.empty()) return;

        auto* editor = getEditorLayer();
        if (!editor || !editor->m_objects) {
            m_pendingPlacements.clear();
            return;
        }

        std::vector<ActionSerializer::ObjectData> objects;
        objects.reserve(m_pendingPlacements.size());
        for (auto& p : m_pendingPlacements) {
            if (!p.obj || !editor->m_objects->containsObject(p.obj)) continue;
            objects.push_back(ActionSerializer::extractObjectData(p.obj, p.uuid));
            
            MessageBatcher::get().removePending(p.uuid);
            
            if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(static_cast<GameObject*>(p.obj))) {
                if (!tpPortal->m_isYellowPortal && tpPortal->m_orangePortal) {
                    auto* orange = tpPortal->m_orangePortal;
                    auto orangeUuid = getOrCreateUUID(orange);
                    objects.push_back(ActionSerializer::extractObjectData(orange, orangeUuid));
                    MessageBatcher::get().removePending(orangeUuid);
                }
            }
        }
        m_pendingPlacements.clear();

        if (!objects.empty() && !m_processingRemote) {
            auto data = proto::serializePlaceObjects(objects);
            P2PManager::get().send(data, ChannelType::Reliable);
            log::debug("RemoteActionHandler: Flushed batched placement of {} objects", objects.size());
        }
    }

    bool RemoteActionHandler::isInitialSyncCompleted() const {
        if (SessionManager::get().getRole() == SessionManager::Role::Host) {
            return true;
        }
        return m_initialSyncCompleted;
    }

    void RemoteActionHandler::downloadSongFinished(int id) {
        auto* editor = getEditorLayer();
        if (editor && editor->m_level && editor->m_level->m_songID == id) {
            GameManager::get()->fadeInMusic(editor->m_level->getAudioFileName());
            geode::Notification::create("Song downloaded! Playing now.", geode::NotificationIcon::Success)->show();
        }
    }

    void RemoteActionHandler::downloadSongFailed(int id, GJSongError error) {
        geode::Notification::create("Failed to download custom song", geode::NotificationIcon::Error)->show();
    }

    void RemoteActionHandler::applyLevelSettings(LevelEditorLayer* editor, ActionSerializer::LevelSettingsData const& settings) {
        if (!editor) return;

        if (!settings.saveString.empty() && editor->m_levelSettings) {
            auto* newSettings = LevelSettingsObject::objectFromString(settings.saveString);
            if (newSettings) {
                editor->m_levelSettings->m_startMode = newSettings->m_startMode;
                editor->m_levelSettings->m_startSpeed = newSettings->m_startSpeed;
                editor->m_levelSettings->m_startMini = newSettings->m_startMini;
                editor->m_levelSettings->m_startDual = newSettings->m_startDual;
                editor->m_levelSettings->m_twoPlayerMode = newSettings->m_twoPlayerMode;
                editor->m_levelSettings->m_isFlipped = newSettings->m_isFlipped;
                editor->m_levelSettings->m_songOffset = newSettings->m_songOffset;

                if (auto* newEffectMgr = newSettings->m_effectManager) {
                    if (auto* oldEffectMgr = editor->m_levelSettings->m_effectManager) {
                        if (auto* newDict = newEffectMgr->m_colorActionDict) {
                            if (auto* oldDict = oldEffectMgr->m_colorActionDict) {
                                auto copyColor = [](ColorAction* oldAction, ColorAction* newAction) {
                                    if (oldAction && newAction) {
                                        oldAction->m_color = newAction->m_color;
                                        oldAction->m_fromColor = newAction->m_fromColor;
                                        oldAction->m_toColor = newAction->m_toColor;
                                        oldAction->m_duration = newAction->m_duration;
                                        oldAction->m_blending = newAction->m_blending;
                                        oldAction->m_playerColor = newAction->m_playerColor;
                                        oldAction->m_fromOpacity = newAction->m_fromOpacity;
                                        oldAction->m_toOpacity = newAction->m_toOpacity;
                                        oldAction->m_copyHSV = newAction->m_copyHSV;
                                        oldAction->m_copyID = newAction->m_copyID;
                                        oldAction->m_copyOpacity = newAction->m_copyOpacity;
                                        oldAction->m_copyColorCalculated = newAction->m_copyColorCalculated;
                                        oldAction->m_colorID = newAction->m_colorID;
                                        oldAction->m_copyColorLoop = newAction->m_copyColorLoop;
                                        oldAction->m_legacyHSV = newAction->m_legacyHSV;
                                    }
                                };
                                
                                for (size_t i = 0; i < newEffectMgr->m_colorActionVector.size(); i++) {
                                    if (i < oldEffectMgr->m_colorActionVector.size()) {
                                        auto* newAction = newEffectMgr->m_colorActionVector[i];
                                        auto* oldAction = oldEffectMgr->m_colorActionVector[i];
                                        copyColor(oldAction, newAction);
                                        if (oldAction) {
                                            oldEffectMgr->updateColorAction(oldAction);
                                            oldEffectMgr->colorActionChanged(oldAction);
                                        }
                                    }
                                }

                                auto* keys = newDict->allKeys();
                                if (keys) {
                                    for (int i = 0; i < keys->count(); i++) {
                                        auto* keyObj = keys->objectAtIndex(i);
                                        intptr_t k = 0;
                                        if (auto* strKey = typeinfo_cast<cocos2d::CCString*>(keyObj)) {
                                            k = std::stoi(strKey->getCString());
                                        } else if (auto* intKey = typeinfo_cast<cocos2d::CCInteger*>(keyObj)) {
                                            k = intKey->getValue();
                                        }
                                        
                                        auto* newAction = static_cast<ColorAction*>(newDict->objectForKey(k));
                                        if (!newAction && keyObj) {
                                            if (auto* strKey = typeinfo_cast<cocos2d::CCString*>(keyObj)) {
                                                newAction = static_cast<ColorAction*>(newDict->objectForKey(strKey->getCString()));
                                            }
                                        }
                                        
                                        auto* oldAction = static_cast<ColorAction*>(oldDict->objectForKey(k));
                                        
                                        if (!oldAction) {
                                            oldAction = ColorAction::create();
                                            oldDict->setObject(oldAction, k);
                                        }
                                        if (newAction && oldAction) {
                                            copyColor(oldAction, newAction);
                                            
                                            oldEffectMgr->updateColorAction(oldAction);
                                            oldEffectMgr->colorActionChanged(oldAction);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                editor->m_updateColorSprites = true;
                editor->updateOptions();
            }
        }

        if (editor->m_level) {
            bool songChanged = (editor->m_level->m_songID != settings.songID
                || editor->m_level->m_audioTrack != settings.audioTrack);
            editor->m_level->m_audioTrack = settings.audioTrack;
            editor->m_level->m_songID = settings.songID;
            editor->m_level->m_levelLength = settings.levelLength;

            if (songChanged) {
                if (settings.songID > 0) {
                    if (MusicDownloadManager::sharedState()->isSongDownloaded(settings.songID)) {
                        GameManager::get()->fadeInMusic(editor->m_level->getAudioFileName());
                    } else {
                        geode::Notification::create("Custom song not downloaded locally.", geode::NotificationIcon::Info)->show();
                    }
                } else {
                    GameManager::get()->fadeInMusic(editor->m_level->getAudioFileName());
                }
            }
        }
    }

    void RemoteActionHandler::handleRemoteUpdateSettings(int playerId, ActionSerializer::LevelSettingsData const& settings) {
        auto* editor = getEditorLayer();
        if (!editor) return;

        ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);

        log::info("RemoteActionHandler: Updating level settings from player {}", playerId);

        applyLevelSettings(editor, settings);

        editor->levelSettingsUpdated();

        m_processingRemote = false;
    }

} // namespace mpedit


