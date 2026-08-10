from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


path = Path("src/EditorHooks.cpp")
text = path.read_text(encoding="utf-8")

# During EditorUI::pasteObjects, GD may create and initialize a whole structure
# through many addToSection calls. Do not serialize those intermediate objects
# one-by-one; serialize the final returned array once the paste has completed.
text = replace_once(
    text,
    '''    bool s_inTransformSync = false;\n    cocos2d::CCPoint s_lastTouchPos = {0.f, 0.f};''',
    '''    bool s_inTransformSync = false;\n    bool s_inBulkPasteSync = false;\n    cocos2d::CCPoint s_lastTouchPos = {0.f, 0.f};''',
    "bulk paste guard",
)

# Add a dedicated pasteObjects hook to EditorUI. This catches normal GD paste
# and editor mods such as Object Workshop that use the native paste pipeline.
anchor = '''    void onCreateObject(int id) {
        EditorUI::onCreateObject(id);
        s_selectedObjectID = id;
    }
'''
replacement = '''    void onCreateObject(int id) {
        EditorUI::onCreateObject(id);
        s_selectedObjectID = id;
    }

    cocos2d::CCArray* pasteObjects(gd::string str, bool withColor, bool noUndo) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        bool shouldBulkSync = session.isInSession()
            && !handler.isProcessingRemote()
            && handler.isInitialSyncCompleted();

        if (!shouldBulkSync) {
            return EditorUI::pasteObjects(str, withColor, noUndo);
        }

        s_inBulkPasteSync = true;
        auto* pasted = EditorUI::pasteObjects(str, withColor, noUndo);
        s_inBulkPasteSync = false;

        if (!pasted || pasted->count() == 0) {
            return pasted;
        }

        std::vector<ActionSerializer::ObjectData> placed;
        placed.reserve(pasted->count());
        std::unordered_set<GameObject*> seen;

        for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
            if (!obj || seen.contains(obj)) continue;
            seen.insert(obj);

            // Yellow teleport portals are generated companions of the blue
            // portal and are serialized together by the existing portal logic.
            if (auto* tp = typeinfo_cast<TeleportPortalObject*>(obj)) {
                if (tp->m_isYellowPortal) continue;
            }

            auto uuid = handler.getUUIDForObject(obj);
            if (uuid.empty()) {
                uuid = RemoteActionHandler::generateUUID();
                handler.registerObject(uuid, obj);
            }

            placed.push_back(ActionSerializer::extractObjectData(obj, uuid));
            MessageBatcher::get().removePending(uuid);

            if (auto* tp = typeinfo_cast<TeleportPortalObject*>(obj)) {
                if (!tp->m_isYellowPortal && tp->m_orangePortal && !seen.contains(tp->m_orangePortal)) {
                    auto* orange = tp->m_orangePortal;
                    seen.insert(orange);
                    auto orangeUuid = handler.getUUIDForObject(orange);
                    if (orangeUuid.empty()) {
                        orangeUuid = RemoteActionHandler::generateUUID();
                        handler.registerObject(orangeUuid, orange);
                    }
                    placed.push_back(ActionSerializer::extractObjectData(orange, orangeUuid));
                    MessageBatcher::get().removePending(orangeUuid);
                }
            }
        }

        if (!placed.empty()) {
            auto packet = proto::serializePlaceObjects(placed);
            P2PManager::get().send(std::move(packet), ChannelType::Reliable);
            log::info(
                "EditorHooks: bulk paste synced {} finalized objects (source string {} bytes)",
                placed.size(),
                str.size()
            );
        }

        return pasted;
    }
'''
text = replace_once(text, anchor, replacement, "EditorUI pasteObjects hook")

# addToSection is still used for normal single-object creation. During a bulk
# paste, the dedicated hook above owns placement synchronization.
text = replace_once(
    text,
    '''        if (!session.isInSession() || handler.isProcessingRemote() || !obj) {
            return;
        }

        if (!handler.isInitialSyncCompleted()) {''',
    '''        if (!session.isInSession() || handler.isProcessingRemote() || !obj) {
            return;
        }

        if (s_inBulkPasteSync) {
            return;
        }

        if (!handler.isInitialSyncCompleted()) {''',
    "suppress addToSection during bulk paste",
)

path.write_text(text, encoding="utf-8")
print("Patched EditorHooks.cpp with finalized bulk paste synchronization")
