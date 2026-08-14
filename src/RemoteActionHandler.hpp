#pragma once

#include "ActionSerializer.hpp"
#include <string>
#include <unordered_map>
#include <Geode/binding/MusicDownloadDelegate.hpp>

#include <optional>
#include <vector>
#include <utility>

class GameObject;
class LevelEditorLayer;

namespace mpedit {
    void updateStartPosCache(GameObject* obj);

    struct LockInfo {
        int playerId;
        float timeLeft;
    };

    /**
     * Handles incoming remote actions and applies them to the local editor.
     * Maintains a UUID-to-GameObject mapping for tracking remote objects.
     */
    class RemoteActionHandler : public MusicDownloadDelegate {
    public:
        static RemoteActionHandler& get();

        // Register network handlers for remote actions
        void setupHandlers();
        void clearHandlers();

        // Apply remote actions to the local editor
        void handleRemotePlaceObjects(int playerId, std::vector<ActionSerializer::ObjectData> const& objects);
        void handleRemoteDeleteObjects(int playerId, std::vector<std::string> const& uuids);
        void handleRemoteMoveObjects(int playerId, std::vector<ActionSerializer::MoveData> const& moves);
        void handleRemoteTransformObjects(int playerId, std::vector<ActionSerializer::TransformData> const& transforms);
        void handleRemoteReconcileObjects(int playerId, std::vector<ActionSerializer::ReconcileData> const& reconciles);
        void handleRemoteUpdateObjects(int playerId, std::vector<ActionSerializer::ObjectData> const& objects);
        void handleRemoteLockObjects(int playerId, std::vector<std::string> const& uuids, bool locked);
        void handleRemoteSyncLevel(int playerId, std::string const& objectsString, std::vector<std::string> const& uuids, ActionSerializer::LevelSettingsData const& settings, std::vector<ActionSerializer::LockData> const& locks, bool isPendingSync = false);
        void handleRemoteUpdateSettings(int playerId, ActionSerializer::LevelSettingsData const& settings);

        std::unordered_map<std::string, LockInfo> const& getObjectLocks() const { return m_objectLocks; }
        
        // Call this every frame to decay lock timers
        void updateLocks(float dt);

        // History pruning helper
        void pruneObjectFromHistory(LevelEditorLayer* editor, GameObject* obj);

        // UUID management
        void registerObject(std::string const& uuid, GameObject* obj);
        void unregisterObject(std::string const& uuid);
        GameObject* getObjectByUUID(std::string const& uuid) const;
        std::string getUUIDForObject(GameObject* obj) const;
        std::string getOrCreateUUID(GameObject* obj);

        // Generate a new UUID
        static std::string generateUUID();

        // Clear all mappings (called when leaving editor)
        void clearMappings();

        // --- Batched placement sync ---
        // Copy/paste/duplicate can spawn dozens of objects in a single frame.
        // Instead of sending one place_objects message per object (one WS send
        // + one getSaveString each), queue them here and flush as a single
        // message via flushPendingPlacements() on the next network tick.
        void queueObjectForPlacement(std::string const& uuid, GameObject* obj);
        void flushPendingPlacements();
        bool isObjectPendingPlacement(GameObject* obj) const;

        // --- Playtest Queueing ---
        void flushPlaytestQueue();

        // Flag to suppress outgoing messages when processing remote actions
        bool isProcessingRemote() const { return m_processingRemote; }

        bool isInitialSyncCompleted() const;
        void setInitialSyncCompleted(bool completed) { m_initialSyncCompleted = completed; }

        void applyPendingSync();
        bool hasPendingSync() const { return m_pendingSync.has_value(); }

        // Bridges applyPendingSync to handleRemoteSyncLevel during init.
        void setEditorForInit(LevelEditorLayer* editor) { m_editorForInit = editor; }
        LevelEditorLayer* getEditorForInit() const { return m_editorForInit; }

        std::vector<std::string> const& getExpectedUuids() const { return m_expectedUuids; }
        void setExpectedUuids(std::vector<std::string> const& uuids) { m_expectedUuids = uuids; }
        void clearExpectedUuids() { m_expectedUuids.clear(); }

        void downloadSongFinished(int id) override;
        void downloadSongFailed(int id, GJSongError error) override;
        void downloadSongStarted(int id) override {}
        void loadSongInfoFinished(SongInfoObject* object) override {}
        void loadSongInfoFailed(int id, GJSongError errorType) override {}

        std::unordered_map<GameObject*, std::string>& getTrackedSelections() { return m_preSelectSaveStrings; }

        struct IntegrityEntry {
            std::string uuid;
            std::string hash;
        };
        std::pair<uint32_t, std::string> computeLevelDigest() const;
        std::vector<IntegrityEntry> buildLevelManifest() const;
        std::vector<ActionSerializer::ObjectData> getObjectDataForUuids(
            std::vector<std::string> const& uuids) const;
        void sendLevelDigestTo(int playerId);
        void sendLevelManifestTo(int playerId);

    private:
        RemoteActionHandler() = default;
        ~RemoteActionHandler() = default;

        RemoteActionHandler(RemoteActionHandler const&) = delete;
        RemoteActionHandler& operator=(RemoteActionHandler const&) = delete;

        LevelEditorLayer* getEditorLayer() const;

        void applyLevelSettings(LevelEditorLayer* editor, ActionSerializer::LevelSettingsData const& settings);

        std::unordered_map<std::string, GameObject*> m_uuidToObject;
        std::unordered_map<GameObject*, std::string> m_objectToUuid;

        std::unordered_map<std::string, LockInfo> m_objectLocks;
        std::unordered_map<GameObject*, std::string> m_preSelectSaveStrings;

        bool m_processingRemote = false;
        bool m_initialSyncCompleted = false;

        LevelEditorLayer* m_editorForInit = nullptr;

        struct PendingSync {
            int playerId;
            std::string objectsString;
            std::vector<std::string> uuids;
            ActionSerializer::LevelSettingsData settings;
            std::vector<ActionSerializer::LockData> locks;
        };
        std::optional<PendingSync> m_pendingSync;
        std::vector<std::string> m_expectedUuids;

        struct ChunkedSyncState {
            int hostPlayerId = -1;
            uint32_t totalChunks = 0;
            uint32_t totalObjects = 0;
            ActionSerializer::LevelSettingsData settings;
            std::vector<std::string> chunks;
            std::vector<std::vector<std::string>> uuidChunks;
            bool active = false;
        };
        ChunkedSyncState m_chunkedSync;

        struct PendingPlacement {
            std::string uuid;
            geode::Ref<GameObject> obj;
        };
        std::vector<PendingPlacement> m_pendingPlacements;

        struct RepairManifestState {
            bool active = false;
            int hostPlayerId = -1;
            uint32_t scanId = 0;
            uint32_t totalChunks = 0;
            std::vector<bool> received;
            std::vector<IntegrityEntry> entries;
        };
        RepairManifestState m_repairManifest;

        struct QueuedAction {
            enum class Type { Place, Delete, Move, Transform, Reconcile, Update };
            Type type;
            int playerId;
            
            std::vector<ActionSerializer::ObjectData> placeObjects;
            std::vector<std::string> deleteUuids;
            std::vector<ActionSerializer::MoveData> moveData;
            std::vector<ActionSerializer::TransformData> transformData;
            std::vector<ActionSerializer::ReconcileData> reconcileData;
            std::vector<ActionSerializer::ObjectData> updateObjects;
        };
        std::vector<QueuedAction> m_playtestQueue;

        static inline int s_uuidCounter = 0;
    };

} // namespace mpedit
