#include "ActionSerializer.hpp"
#include <Geode/Geode.hpp>
#include <sstream>
#include <unordered_map>

using namespace geode::prelude;

namespace mpedit::ActionSerializer {

    // ============================================================
    // GameObject Helpers
    // ============================================================

    ObjectData extractObjectData(GameObject* obj, std::string const& uuid) {
        ObjectData data;
        data.uuid = uuid;

        if (!obj) return data;

        data.objectID = obj->m_objectID;
        data.x = obj->getPositionX();
        data.y = obj->getPositionY();
        data.rotation = obj->getRotation();
        data.scaleX = obj->getScaleX();
        data.scaleY = obj->getScaleY();
        data.flipX = obj->isFlipX();
        data.flipY = obj->isFlipY();
        data.zOrder = obj->getZOrder();
        data.editorLayer = obj->m_editorLayer;
        data.editorLayer2 = obj->m_editorLayer2;
        data.saveString = "";
        if (auto* editor = LevelEditorLayer::get()) {
            std::string s = obj->getSaveString(editor);
            size_t pos = s.find(';');
            if (pos != std::string::npos) {
                s = s.substr(0, pos);
            }
            data.saveString = s;
        }

        // Extract up to 10 groups
        if (obj->m_groups && obj->m_groupCount > 0) {
            int count = std::min(static_cast<int>(obj->m_groupCount), 10);
            for (int i = 0; i < count; i++) {
                data.groups.push_back((*obj->m_groups)[i]);
            }
        }

        return data;
    }

    std::unordered_map<std::string, std::string> parseSaveString(std::string const& str) {
        std::unordered_map<std::string, std::string> out;
        
        std::string s = str;
        size_t pos = s.find(';');
        if (pos != std::string::npos) {
            s = s.substr(0, pos);
        }

        std::stringstream ss(s);
        std::string key, val;
        while (std::getline(ss, key, ',') && std::getline(ss, val, ',')) {
            out[key] = val;
        }
        return out;
    }

    std::string buildSaveString(std::unordered_map<std::string, std::string> const& map) {
        std::string result = "";
        for (auto const& [k, v] : map) {
            result += k + "," + v + ",";
        }
        return result;
    }

    std::vector<std::pair<std::string, std::string>> parseSaveStringOrdered(std::string const& str) {
        std::vector<std::pair<std::string, std::string>> out;
        std::string s = str;
        size_t pos = s.find(';');
        if (pos != std::string::npos) s = s.substr(0, pos);
        std::stringstream ss(s);
        std::string key, val;
        while (std::getline(ss, key, ',') && std::getline(ss, val, ',')) {
            out.push_back({key, val});
        }
        return out;
    }

    std::string buildSaveStringOrdered(std::vector<std::pair<std::string, std::string>> const& vec) {
        std::string result = "";
        for (auto const& p : vec) {
            result += p.first + "," + p.second + ",";
        }
        return result;
    }

    void injectLocalStartPosState(ObjectData& remoteData, GameObject* localObj) {
        // v0.5.2: StartPos configuration is authoritative shared editor state.
        // Older builds preserved several StartPos keys from the receiving client,
        // which could silently overwrite the sender's configuration after sync.
        // Keep this compatibility helper as a no-op so existing call sites remain
        // valid while the complete remote saveString is applied unchanged.
        (void)remoteData;
        (void)localObj;
    }

    bool hasDeepPropertyChanges(GameObject* obj, std::string const& oldSave, std::string const& newSave) {
        if (oldSave == newSave) return false;
        
        auto oldMap = parseSaveString(oldSave);
        auto newMap = parseSaveString(newSave);

        // Keys to ignore for purely positional/transform reconciles:
        // 2: X, 3: Y, 4: FlipX, 5: FlipY, 11: Rot, 32: Scale, 128: ScaleX, 129: ScaleY
        for (auto const& k : {"2", "3", "4", "5", "11", "32", "128", "129"}) {
            oldMap.erase(k);
            newMap.erase(k);
        }

        if (oldMap.size() != newMap.size()) return true;
        for (auto const& [k, v] : oldMap) {
            auto it = newMap.find(k);
            if (it == newMap.end() || it->second != v) return true;
        }
        return false;
    }

} // namespace mpedit::ActionSerializer
