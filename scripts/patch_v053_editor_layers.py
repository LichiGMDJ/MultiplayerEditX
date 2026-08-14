from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.3 editor layers: {label}: expected source block not found")
    return text.replace(old, new, 1)


# =============================================================================
# Protocol v7 / v0.5.3: preserve Geometry Dash Editor Layer 1 + Layer 2.
#
# ObjectData already transports both layer fields for normal Place/Update frames,
# but the native save-string recreation path can place reconstructed objects onto
# the receiver's current editor layer. Full SyncLevel and RAW/Object Workshop paste
# also carried only save strings + UUIDs, so their layer assignment could collapse.
#
# For snapshot / RAW bulk streams we keep the existing wire structs intact and
# attach a small layer sidecar to the UUID string. ProtocolHello is bumped to v7,
# so a v6 peer can never silently interpret these tagged UUIDs as real mappings.
# =============================================================================

p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(
    p2p,
    "constexpr uint32_t kProtocolVersion = 6;",
    "constexpr uint32_t kProtocolVersion = 7;",
    "protocol version bump",
)
p2p_path.write_text(p2p, encoding="utf-8")


# =============================================================================
# Sender: layer-aware baselines + layer sidecars for full sync and RAW paste.
# =============================================================================
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")

hooks = replace_once(
    hooks,
    '''    std::unordered_map<GameObject*, std::string> s_startPosSaveStrings;\n}''',
    '''    std::unordered_map<GameObject*, std::string> s_startPosSaveStrings;\n\n    constexpr char kEditorLayerTag[] = "#EL#";\n\n    std::string encodeLayerTaggedUuid(std::string const& uuid, int editorLayer, int editorLayer2) {\n        return uuid + kEditorLayerTag + std::to_string(editorLayer)\n            + kEditorLayerTag + std::to_string(editorLayer2);\n    }\n\n    std::string objectLayerSyncState(GameObject* obj, LevelEditorLayer* editor) {\n        if (!obj || !editor) return {};\n        std::string state = obj->getSaveString(editor);\n        // Explicitly include both editor layers even if GD changes save-string\n        // behavior. This makes a layer-only edit produce UpdateObjects.\n        state += "|mpedit-editor-layers:" + std::to_string(obj->m_editorLayer)\n            + ":" + std::to_string(obj->m_editorLayer2);\n        return state;\n    }\n}''',
    "sender layer helpers",
)

# Full authoritative SyncLevel: UUID sidecar carries layer metadata alongside the
# exact native object save string.
hooks = replace_once(
    hooks,
    '''                allUuids.push_back(uuid);\n                fullObjectsString += std::string(obj->getSaveString(editor)) + ";";''',
    '''                allUuids.push_back(encodeLayerTaggedUuid(\n                    uuid, obj->m_editorLayer, obj->m_editorLayer2\n                ));\n                fullObjectsString += std::string(obj->getSaveString(editor)) + ";";''',
    "full-sync layer sidecar",
)

# RAW/Object Workshop paste: preserve the layers after the sender's native paste.
hooks = replace_once(
    hooks,
    '''            uuids.push_back(uuid);\n            MessageBatcher::get().removePending(uuid);''',
    '''            uuids.push_back(encodeLayerTaggedUuid(\n                uuid, obj->m_editorLayer, obj->m_editorLayer2\n            ));\n            MessageBatcher::get().removePending(uuid);''',
    "RAW paste layer sidecar",
)

# Layer-only edits must not be hidden by a save-string baseline. Replace the
# relevant selection/undo baselines and comparisons with explicit layer state.
hooks = hooks.replace(
    "tracked[obj] = obj->getSaveString(editor);",
    "tracked[obj] = objectLayerSyncState(obj, editor);",
)
hooks = hooks.replace(
    "tIt->second = state.obj->getSaveString(editor);",
    "tIt->second = objectLayerSyncState(state.obj, editor);",
)
hooks = hooks.replace(
    "saveStringsBefore[obj] = obj->getSaveString(this);",
    "saveStringsBefore[obj] = objectLayerSyncState(obj, this);",
)
hooks = hooks.replace(
    "std::string currentSave = obj->getSaveString(this);",
    "std::string currentSave = objectLayerSyncState(obj, this);",
)
hooks = hooks.replace(
    "std::string currentSave = obj->getSaveString(editor);",
    "std::string currentSave = objectLayerSyncState(obj, editor);",
)

if "objectLayerSyncState(obj, editor)" not in hooks:
    raise SystemExit("v0.5.3 editor layers: layer-aware selection baselines were not installed")

hooks_path.write_text(hooks, encoding="utf-8")


# =============================================================================
# Receiver: decode sidecars and explicitly restore layers after native recreation.
# =============================================================================
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")

remote = replace_once(
    remote,
    '''        std::vector<std::string> splitSerializedObjects(std::string const& objectsString) {''',
    '''        struct LayerTaggedUuid {\n            std::string uuid;\n            int editorLayer = 0;\n            int editorLayer2 = 0;\n            bool hasLayers = false;\n        };\n\n        LayerTaggedUuid decodeLayerTaggedUuid(std::string const& tagged) {\n            constexpr std::string_view tag = "#EL#";\n            LayerTaggedUuid out;\n            out.uuid = tagged;\n\n            auto second = tagged.rfind(tag);\n            if (second == std::string::npos) return out;\n            auto first = tagged.rfind(tag, second - 1);\n            if (first == std::string::npos) return out;\n\n            auto layer1 = geode::utils::numFromString<int>(\n                tagged.substr(first + tag.size(), second - (first + tag.size()))\n            );\n            auto layer2 = geode::utils::numFromString<int>(\n                tagged.substr(second + tag.size())\n            );\n            if (layer1.isErr() || layer2.isErr()) return out;\n\n            out.uuid = tagged.substr(0, first);\n            out.editorLayer = layer1.unwrap();\n            out.editorLayer2 = layer2.unwrap();\n            out.hasLayers = true;\n            return out;\n        }\n\n        void applyEditorLayers(GameObject* obj, int editorLayer, int editorLayer2) {\n            if (!obj) return;\n            obj->m_editorLayer = editorLayer;\n            obj->m_editorLayer2 = editorLayer2;\n        }\n\n        std::vector<std::string> splitSerializedObjects(std::string const& objectsString) {''',
    "receiver layer helpers",
)

# Normal PlaceObjects save-string path. Fallback createObject already assigns both.
remote = replace_once(
    remote,
    '''                    applyTransformSafe(obj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                    registerObject(objData.uuid, obj);''',
    '''                    applyTransformSafe(obj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                    applyEditorLayers(obj, objData.editorLayer, objData.editorLayer2);\n                    registerObject(objData.uuid, obj);''',
    "PlaceObjects save-string layer restore",
)

# Direct companion/portal updates also need their own layer values.
remote = replace_once(
    remote,
    '''                    tpPortal->setPositionOverride({objData.x, objData.y});\n                    applyTransformSafe(oldObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);''',
    '''                    tpPortal->setPositionOverride({objData.x, objData.y});\n                    applyTransformSafe(oldObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                    applyEditorLayers(oldObj, objData.editorLayer, objData.editorLayer2);''',
    "direct portal layer restore",
)

# Normal UpdateObjects save-string recreation path.
remote = replace_once(
    remote,
    '''                applyTransformSafe(newObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                registerObject(objData.uuid, newObj);''',
    '''                applyTransformSafe(newObj, objData.rotation, objData.scaleX, objData.scaleY, objData.flipX, objData.flipY);\n                applyEditorLayers(newObj, objData.editorLayer, objData.editorLayer2);\n                registerObject(objData.uuid, newObj);''',
    "UpdateObjects save-string layer restore",
)

# Teleport companion data appears in both placement and update paths. Add the
# explicit layer assignment next to every orangeData transform before mapping.
remote = remote.replace(
    '''                                    applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,\n                                                       orangeData.scaleY, orangeData.flipX, orangeData.flipY);\n                                    registerObject(orangeData.uuid, orange);''',
    '''                                    applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,\n                                                       orangeData.scaleY, orangeData.flipX, orangeData.flipY);\n                                    applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);\n                                    registerObject(orangeData.uuid, orange);''',
)
remote = remote.replace(
    '''                                applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,\n                                                   orangeData.scaleY, orangeData.flipX, orangeData.flipY);\n                                registerObject(orangeData.uuid, orange);''',
    '''                                applyTransformSafe(orange, orangeData.rotation, orangeData.scaleX,\n                                                   orangeData.scaleY, orangeData.flipX, orangeData.flipY);\n                                applyEditorLayers(orange, orangeData.editorLayer, orangeData.editorLayer2);\n                                registerObject(orangeData.uuid, orange);''',
)
remote = remote.replace(
    '''                            applyTransformSafe(orange, oldOrangeData.rotation, oldOrangeData.scaleX,\n                                               oldOrangeData.scaleY, oldOrangeData.flipX, oldOrangeData.flipY);''',
    '''                            applyTransformSafe(orange, oldOrangeData.rotation, oldOrangeData.scaleX,\n                                               oldOrangeData.scaleY, oldOrangeData.flipX, oldOrangeData.flipY);\n                            applyEditorLayers(orange, oldOrangeData.editorLayer, oldOrangeData.editorLayer2);''',
)

# RAW/Object Workshop receiver: decode the UUID sidecar and restore both layers
# after native paste (which may otherwise use the receiver's current edit layer).
remote = replace_once(
    remote,
    '''                if (index < uuids.size()) registerObject(uuids[index], obj);\n                else registerObject(RemoteActionHandler::generateUUID(), obj);\n                ++index;''',
    '''                if (index < uuids.size()) {\n                    auto tagged = decodeLayerTaggedUuid(uuids[index]);\n                    if (tagged.hasLayers) {\n                        applyEditorLayers(obj, tagged.editorLayer, tagged.editorLayer2);\n                    }\n                    registerObject(tagged.uuid, obj);\n                } else {\n                    registerObject(RemoteActionHandler::generateUUID(), obj);\n                }\n                ++index;''',
    "RAW paste receiver layer restore",
)

# Full SyncLevel hardening maps authoritative records to recreated objects by
# object ID. Decode the same sidecar at the exact mapping point.
remote = replace_once(
    remote,
    '''                assigned.insert(match);\n                registerObject(uuids[i], match);\n                ++mapped;''',
    '''                assigned.insert(match);\n                auto tagged = decodeLayerTaggedUuid(uuids[i]);\n                if (tagged.hasLayers) {\n                    applyEditorLayers(match, tagged.editorLayer, tagged.editorLayer2);\n                }\n                registerObject(tagged.uuid, match);\n                ++mapped;''',
    "full-sync receiver layer restore",
)

# Snapshot validation must compare record count to sidecar count (unchanged), but
# integrity hashing must include both editor-layer fields explicitly so Auto Repair
# notices layer-only drift even if GD's save string does not.
remote = replace_once(
    remote,
    '''            std::string save = obj->getSaveString(editor);\n            entries.push_back({uuid, stableIntegrityHash(save)});''',
    '''            std::string save = obj->getSaveString(editor);\n            save += "|mpedit-editor-layers:" + std::to_string(obj->m_editorLayer)\n                + ":" + std::to_string(obj->m_editorLayer2);\n            entries.push_back({uuid, stableIntegrityHash(save)});''',
    "integrity layer hash",
)

remote_path.write_text(remote, encoding="utf-8")


# =============================================================================
# Self-checks.
# =============================================================================
checks = [
    (p2p_path, "kProtocolVersion = 7", "Protocol v7 missing"),
    (hooks_path, "encodeLayerTaggedUuid", "full/bulk layer sidecar encoder missing"),
    (hooks_path, "objectLayerSyncState", "layer-aware local change detection missing"),
    (remote_path, "decodeLayerTaggedUuid", "layer sidecar decoder missing"),
    (remote_path, "applyEditorLayers(obj, objData.editorLayer, objData.editorLayer2)", "PlaceObjects layer restore missing"),
    (remote_path, "applyEditorLayers(newObj, objData.editorLayer, objData.editorLayer2)", "UpdateObjects layer restore missing"),
    (remote_path, "applyEditorLayers(match, tagged.editorLayer, tagged.editorLayer2)", "full-sync layer restore missing"),
    (remote_path, "applyEditorLayers(obj, tagged.editorLayer, tagged.editorLayer2)", "RAW paste layer restore missing"),
    (remote_path, "|mpedit-editor-layers:", "integrity layer hashing missing"),
]
for path, marker, error in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.3 editor layers self-check failed: {error} ({path}: {marker})")

print("Patched v0.5.3 / protocol v7: Editor Layer 1/2 preserved across place, update, full sync, RAW paste and integrity repair")
