#pragma once

#include <string>
#include <vector>
#include <unordered_map>
#include <utility>

// Forward declarations for GD types
class GameObject;

namespace mpedit {

    /**
     * Data structures for editor actions and state, along with extraction helpers.
     */
    namespace ActionSerializer {

        struct ObjectData {
            std::string uuid;       // Mod-assigned unique identifier
            std::string saveString; // GD native save string (full object state)
            int objectID = 0;       // GD object type ID
            float x = 0.f;
            float y = 0.f;
            float rotation = 0.f;
            float scaleX = 1.f;
            float scaleY = 1.f;
            bool flipX = false;
            bool flipY = false;
            int zOrder = 0;
            int editorLayer = 0;
            int editorLayer2 = 0;
            // Groups
            std::vector<int> groups;
            // Color channels
            int mainColorChannel = -1;
            int secondColorChannel = -1;
        };

        struct LevelSettingsData {
            std::string saveString;
            int audioTrack = 0;
            int songID = 0;
            float levelLength = 0;
        };

        struct MoveData {
            std::string uuid;
            float dx = 0.f;
            float dy = 0.f;
        };

        struct TransformData {
            std::string uuid;
            float rotation = 0.f;
            float scaleX = 1.f;
            float scaleY = 1.f;
            bool flipX = false;
            bool flipY = false;
        };

        struct ReconcileData {
            std::string uuid;
            float x = 0.f;
            float y = 0.f;
            float rotation = 0.f;
            float scaleX = 1.f;
            float scaleY = 1.f;
            bool flipX = false;
            bool flipY = false;
        };

        struct LockData {
            std::string uuid;
            int playerId = 0;
            float timeLeft = 3.0f;
        };

        // === GameObject helpers ===

        ObjectData extractObjectData(GameObject* obj, std::string const& uuid);
        
        std::unordered_map<std::string, std::string> parseSaveString(std::string const& str);
        std::string buildSaveString(std::unordered_map<std::string, std::string> const& map);
        std::vector<std::pair<std::string, std::string>> parseSaveStringOrdered(std::string const& str);
        std::string buildSaveStringOrdered(
            std::vector<std::pair<std::string, std::string>> const& vec);
        void injectLocalStartPosState(ObjectData& remoteData, GameObject* localObj);

        // Returns true if there are changes between two save strings, excluding transform properties
        bool hasDeepPropertyChanges(GameObject* obj, std::string const& oldSave, std::string const& newSave);

    } // namespace ActionSerializer

} // namespace mpedit
