from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.3 editor layers: {label}: anchor not found")
    return text.replace(old, new, 1)


# Protocol v7: layer metadata is added to full-sync / RAW-paste UUID sidecars.
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = once(p2p, "constexpr uint32_t kProtocolVersion = 6;", "constexpr uint32_t kProtocolVersion = 7;", "protocol")
p2p_path.write_text(p2p, encoding="utf-8")


hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

hooks = once(
    hooks,
    '''    std::unordered_map<GameObject*, std::string> s_startPosSaveStrings;\n}''',
    '''    std::unordered_map<GameObject*, std::string> s_startPosSaveStrings;\n\n    constexpr char kEditorLayerTag[] = "#EL#";\n\n    std::string encodeLayerTaggedUuid(std::string const& uuid, int layer1, int layer2) {\n        return uuid + kEditorLayerTag + std::to_string(layer1)\n            + kEditorLayerTag + std::to_string(layer2);\n    }\n\n    std::string objectLayerSyncState(GameObject* obj, LevelEditorLayer* editor) {\n        if (!obj || !editor) return {};\n        auto state = std::string(obj->getSaveString(editor));\n        state += "|mpedit-editor-layers:" + std::to_string(obj->m_editorLayer)\n            + ":" + std::to_string(obj->m_editorLayer2);\n        return state;\n    }\n}''',
    "sender helpers",
)

hooks = once(
    hooks,
    '''                allUuids.push_back(uuid);\n                fullObjectsString += std::string(obj->getSaveString(editor)) + ";";''',
    '''                allUuids.push_back(encodeLayerTaggedUuid(uuid, obj->m_editorLayer, obj->m_editorLayer2));\n                fullObjectsString += std::string(obj->getSaveString(editor)) + ";";''',
    "full sync sidecar",
)

hooks = once(
    hooks,
    '''            uuids.push_back(uuid);\n            MessageBatcher::get().removePending(uuid);''',
    '''            uuids.push_back(encodeLayerTaggedUuid(uuid, obj->m_editorLayer, obj->m_editorLayer2));\n            MessageBatcher::get().removePending(uuid);''',
    "raw paste sidecar",
)

# Include layer-only changes in normal UpdateObjects detection.
hooks = hooks.replace("tracked[obj] = obj->getSaveString(editor);", "tracked[obj] = objectLayerSyncState(obj, editor);")
hooks = hooks.replace("tIt->second = state.obj->getSaveString(editor);", "tIt->second = objectLayerSyncState(state.obj, editor);")
hooks = hooks.replace("saveStringsBefore[obj] = obj->getSaveString(this);", "saveStringsBefore[obj] = objectLayerSyncState(obj, this);")
hooks = hooks.replace("std::string currentSave = obj->getSaveString(this);", "std::string currentSave = objectLayerSyncState(obj, this);")
hooks = hooks.replace("std::string currentSave = obj->getSaveString(editor);", "std::string currentSave = objectLayerSyncState(obj, editor);")

if "objectLayerSyncState(obj, editor)" not in hooks:
    raise SystemExit("v0.5.3 editor layers: layer-aware baselines missing")

hooks_path.write_text(hooks, encoding="utf-8")


remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

remote = once(
    remote,
    '''        std::vector<std::string> splitSerializedObjects(std::string const& objectsString) {''',
    '''        struct LayerTaggedUuid {\n            std::string uuid;\n            int layer1 = 0;\n            int layer2 = 0;\n            bool tagged = false;\n        };\n\n        LayerTaggedUuid decodeLayerTaggedUuid(std::string const& value) {\n            constexpr std::string_view tag = "#EL#";\n            LayerTaggedUuid out;\n            out.uuid = value;\n            auto second = value.rfind(tag);\n            if (second == std::string::npos) return out;\n            auto first = value.rfind(tag, second - 1);\n            if (first == std::string::npos) return out;\n            auto l1 = geode::utils::numFromString<int>(value.substr(first + tag.size(), second - first - tag.size()));\n            auto l2 = geode::utils::numFromString<int>(value.substr(second + tag.size()));\n            if (l1.isErr() || l2.isErr()) return out;\n            out.uuid = value.substr(0, first);\n            out.layer1 = l1.unwrap();\n            out.layer2 = l2.unwrap();\n            out.tagged = true;\n            return out;\n        }\n\n        void applyEditorLayers(GameObject* obj, int layer1, int layer2) {\n            if (!obj) return;\n            obj->m_editorLayer = layer1;\n            obj->m_editorLayer2 = layer2;\n        }\n\n        std::vector<std::string> splitSerializedObjects(std::string const& objectsString) {''',
    "receiver helpers",
)

remote = once(
    remote,
    '''                    applyTransformSafe(obj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                    registerObject(objData.uuid, obj);''',
    '''                    applyTransformSafe(obj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                    applyEditorLayers(obj, objData.editorLayer, objData.editorLayer2);\n                    registerObject(objData.uuid, obj);''',
    "place restore",
)

remote = once(
    remote,
    '''                    tpPortal->setPositionOverride({objData.x, objData.y});\n                    applyTransformSafe(oldObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);''',
    '''                    tpPortal->setPositionOverride({objData.x, objData.y});\n                    applyTransformSafe(oldObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                    applyEditorLayers(oldObj, objData.editorLayer, objData.editorLayer2);''',
    "direct portal restore",
)

remote = once(
    remote,
    '''                applyTransformSafe(newObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                registerObject(objData.uuid, newObj);''',
    '''                applyTransformSafe(newObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                applyEditorLayers(newObj, objData.editorLayer, objData.editorLayer2);\n                registerObject(objData.uuid, newObj);''',
    "update restore",
)

# Companion portal objects use ObjectData too. Preserve their layer fields wherever
# an orange portal is updated from transmitted data.
remote = remote.replace(
    '''                                    registerObject(orangeData.uuid, orange);''',
    '''                                    applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);\n                                    registerObject(orangeData.uuid, orange);''',
)
remote = remote.replace(
    '''                                registerObject(orangeData.uuid, orange);''',
    '''                                applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);\n                                registerObject(orangeData.uuid, orange);''',
)

remote = once(
    remote,
    '''                if (index < uuids.size()) registerObject(uuids[index], obj);\n                else registerObject(RemoteActionHandler::generateUUID(), obj);\n                ++index;''',
    '''                if (index < uuids.size()) {\n                    auto tagged = decodeLayerTaggedUuid(uuids[index]);\n                    if (tagged.tagged) applyEditorLayers(obj, tagged.layer1, tagged.layer2);\n                    registerObject(tagged.uuid, obj);\n                } else {\n                    registerObject(RemoteActionHandler::generateUUID(), obj);\n                }\n                ++index;''',
    "raw paste restore",
)

remote = once(
    remote,
    '''                assigned.insert(match);\n                registerObject(uuids[i], match);\n                ++mapped;''',
    '''                assigned.insert(match);\n                auto tagged = decodeLayerTaggedUuid(uuids[i]);\n                if (tagged.tagged) applyEditorLayers(match, tagged.layer1, tagged.layer2);\n                registerObject(tagged.uuid, match);\n                ++mapped;''',
    "full sync restore",
)

# patch_ack_integrity_reconnect_hardening normalizes StartPos immediately above
# this line. Add the editor layers after that normalization and before hashing.
remote = once(
    remote,
    '''            entries.push_back({uuid, stableIntegrityHash(save)});''',
    '''            save += "|mpedit-editor-layers:" + std::to_string(obj->m_editorLayer)\n                + ":" + std::to_string(obj->m_editorLayer2);\n            entries.push_back({uuid, stableIntegrityHash(save)});''',
    "integrity layer hash",
)

remote_path.write_text(remote, encoding="utf-8")

checks = [
    (p2p_path, "kProtocolVersion = 7"),
    (hooks_path, "encodeLayerTaggedUuid"),
    (hooks_path, "objectLayerSyncState"),
    (remote_path, "decodeLayerTaggedUuid"),
    (remote_path, "applyEditorLayers(obj, objData.editorLayer, objData.editorLayer2)"),
    (remote_path, "applyEditorLayers(newObj, objData.editorLayer, objData.editorLayer2)"),
    (remote_path, "applyEditorLayers(match, tagged.layer1, tagged.layer2)"),
    (remote_path, "|mpedit-editor-layers:"),
]
for path, marker in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.3 editor layers self-check failed: {path}: {marker}")

print("Patched v0.5.3 / protocol v7 editor-layer synchronization")
