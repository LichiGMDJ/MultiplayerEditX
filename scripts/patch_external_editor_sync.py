from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


path = Path("src/EditorHooks.cpp")
text = path.read_text(encoding="utf-8")

# Keep a lightweight snapshot of UUIDs that were actually alive in m_objects.
# This lets us detect editor mods that manipulate the object array without going
# through MultiplayerEdit's normal createObject/removeObject hooks.
text = replace_once(
    text,
    '''        bool m_wasPlaytesting = false;\n\n        ~Fields() {''',
    '''        bool m_wasPlaytesting = false;\n        float m_externalCompatScanTimer = 0.f;\n        std::unordered_set<std::string> m_externalCompatLiveUuids;\n\n        ~Fields() {''',
    "external compatibility fields",
)

# Seed the snapshot after initial UUID registration/sync setup. Objects already
# tracked by MultiplayerEdit are baseline state, not external additions.
text = replace_once(
    text,
    '''            handler.setInitialSyncCompleted(true);\n\n            if (session.getRole() == SessionManager::Role::Host) {''',
    '''            handler.setInitialSyncCompleted(true);\n\n            m_fields->m_externalCompatLiveUuids.clear();\n            if (this->m_objects) {\n                for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {\n                    if (!obj) continue;\n                    auto uuid = handler.getUUIDForObject(obj);\n                    if (!uuid.empty()) {\n                        m_fields->m_externalCompatLiveUuids.insert(uuid);\n                    }\n                }\n            }\n\n            if (session.getRole() == SessionManager::Role::Host) {''',
    "external compatibility baseline",
)

# Periodically reconcile only structural operations that bypassed our hooks:
#  - a live object with no UUID => external placement
#  - a UUID that vanished from m_objects but is still mapped => external delete
# Normal MultiplayerEdit operations already create/remove mappings, so this
# fallback does not resend them.
text = replace_once(
    text,
    '''        // Flush any batched placements (copy/paste/duplicate) as a single message.\n        handler.flushPendingPlacements();\n\n        // Send cursor position periodically''',
    '''        // Flush any batched placements (copy/paste/duplicate) as a single message.\n        handler.flushPendingPlacements();\n\n        // Compatibility fallback for third-party editor mods (Layout Generator,\n        // Object Workshop-style bulk tools, etc.) that may bypass create/remove hooks.\n        m_fields->m_externalCompatScanTimer += dt;\n        if (\n            m_fields->m_externalCompatScanTimer >= 0.25f &&\n            !isPlaytesting &&\n            handler.isInitialSyncCompleted() &&\n            !handler.isProcessingRemote()\n        ) {\n            m_fields->m_externalCompatScanTimer = 0.f;\n\n            std::unordered_set<std::string> currentUuids;\n            std::vector<ActionSerializer::ObjectData> externalPlacements;\n            std::vector<std::string> externalDeletes;\n\n            if (this->m_objects) {\n                currentUuids.reserve(this->m_objects->count());\n                for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {\n                    if (!obj) continue;\n\n                    auto uuid = handler.getUUIDForObject(obj);\n                    if (uuid.empty()) {\n                        uuid = RemoteActionHandler::generateUUID();\n                        handler.registerObject(uuid, obj);\n                        externalPlacements.push_back(ActionSerializer::extractObjectData(obj, uuid));\n                    }\n\n                    currentUuids.insert(uuid);\n                }\n            }\n\n            for (auto const& uuid : m_fields->m_externalCompatLiveUuids) {\n                if (currentUuids.contains(uuid)) continue;\n\n                // If the mapping is already gone, our normal remove hook handled it.\n                // If it still exists, a third-party mod removed the object behind us.\n                if (handler.getObjectByUUID(uuid) != nullptr) {\n                    externalDeletes.push_back(uuid);\n                    handler.unregisterObject(uuid);\n                }\n            }\n\n            if (!externalPlacements.empty()) {\n                auto data = proto::serializePlaceObjects(externalPlacements);\n                P2PManager::get().send(std::move(data), ChannelType::Reliable);\n                log::info(\n                    "EditorHooks: compatibility scan synced {} externally-created objects",\n                    externalPlacements.size()\n                );\n            }\n\n            if (!externalDeletes.empty()) {\n                auto data = proto::serializeDeleteObjects(externalDeletes);\n                P2PManager::get().send(std::move(data), ChannelType::Reliable);\n                log::info(\n                    "EditorHooks: compatibility scan synced {} externally-deleted objects",\n                    externalDeletes.size()\n                );\n            }\n\n            m_fields->m_externalCompatLiveUuids = std::move(currentUuids);\n        }\n\n        // Send cursor position periodically''',
    "external editor compatibility scan",
)

path.write_text(text, encoding="utf-8")
print("Patched EditorHooks.cpp with external editor-mod structural reconciliation")
