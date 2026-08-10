from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)

# Protocol v5: RAW paste positional anchor + explicit host music notification.
hpp_path = Path("src/BinaryProtocol.hpp")
hpp = hpp_path.read_text(encoding="utf-8")
hpp = replace_once(hpp, "        KickPlayer            = 0x45,\n", "        KickPlayer            = 0x45,\n        MusicChanged          = 0x46,\n", "MusicChanged opcode")
hpp = replace_once(
    hpp,
    "    std::vector<uint8_t> serializeBulkPasteStart(\n        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,\n        bool withColor, bool noUndo);",
    "    std::vector<uint8_t> serializeBulkPasteStart(\n        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,\n        bool withColor, bool noUndo, float anchorX, float anchorY);",
    "bulk paste start anchor declaration",
)
hpp = replace_once(
    hpp,
    "        bool noUndo = false;\n    };\n    BulkPasteStartMsg deserializeBulkPasteStart(Reader& r);",
    "        bool noUndo = false;\n        float anchorX = 0.f;\n        float anchorY = 0.f;\n    };\n    BulkPasteStartMsg deserializeBulkPasteStart(Reader& r);",
    "bulk paste anchor fields",
)
hpp = replace_once(
    hpp,
    "    std::vector<uint8_t> serializeKickPlayer(int targetPlayerId, std::string const& reason);\n\n    std::vector<uint8_t> serializeError",
    "    std::vector<uint8_t> serializeKickPlayer(int targetPlayerId, std::string const& reason);\n    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title);\n\n    std::vector<uint8_t> serializeError",
    "music serializer declaration",
)
hpp = replace_once(
    hpp,
    "    struct ErrorMsg {\n        std::string message;\n    };",
    "    struct MusicChangedMsg {\n        int songID = 0;\n        int audioTrack = 0;\n        std::string title;\n    };\n    MusicChangedMsg deserializeMusicChanged(Reader& r);\n\n    struct ErrorMsg {\n        std::string message;\n    };",
    "music message declaration",
)
hpp_path.write_text(hpp, encoding="utf-8")

cpp_path = Path("src/BinaryProtocol.cpp")
cpp = cpp_path.read_text(encoding="utf-8")
cpp = replace_once(
    cpp,
    "    std::vector<uint8_t> serializeBulkPasteStart(\n        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,\n        bool withColor, bool noUndo)\n    {",
    "    std::vector<uint8_t> serializeBulkPasteStart(\n        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,\n        bool withColor, bool noUndo, float anchorX, float anchorY)\n    {",
    "bulk paste serializer signature",
)
cpp = replace_once(
    cpp,
    "        w.writeBool(withColor);\n        w.writeBool(noUndo);\n        return std::move(w.takeData());",
    "        w.writeBool(withColor);\n        w.writeBool(noUndo);\n        w.writeF32(anchorX);\n        w.writeF32(anchorY);\n        return std::move(w.takeData());",
    "bulk paste serializer anchor data",
)
cpp = replace_once(
    cpp,
    "        msg.withColor = r.readBool();\n        msg.noUndo = r.readBool();\n        return msg;",
    "        msg.withColor = r.readBool();\n        msg.noUndo = r.readBool();\n        msg.anchorX = r.readF32();\n        msg.anchorY = r.readF32();\n        return msg;",
    "bulk paste anchor deserialize",
)
cpp = replace_once(
    cpp,
    "    std::vector<uint8_t> serializeError(std::string const& message) {",
    "    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title) {\n        Writer w;\n        w.writeOpcode(Opcode::MusicChanged);\n        w.writeI32(songID);\n        w.writeI32(audioTrack);\n        w.writeString(title);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {",
    "music serializer",
)
cpp = replace_once(
    cpp,
    "    ErrorMsg deserializeError(Reader& r) {",
    "    MusicChangedMsg deserializeMusicChanged(Reader& r) {\n        MusicChangedMsg msg;\n        msg.songID = r.readI32();\n        msg.audioTrack = r.readI32();\n        msg.title = r.readString();\n        return msg;\n    }\n\n    ErrorMsg deserializeError(Reader& r) {",
    "music deserializer",
)
cpp_path.write_text(cpp, encoding="utf-8")

# Protocol version + reliable classification.
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(p2p, "constexpr uint32_t kProtocolVersion = 4;", "constexpr uint32_t kProtocolVersion = 5;", "protocol v5")
p2p = replace_once(
    p2p,
    "                        opcode == proto::Opcode::KickPlayer;",
    "                        opcode == proto::Opcode::KickPlayer ||\n                        opcode == proto::Opcode::MusicChanged;",
    "MusicChanged ACK FIFO",
)
p2p_path.write_text(p2p, encoding="utf-8")

# RAW paste sender: capture absolute anchor after the local native paste.
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
hooks = replace_once(
    hooks,
    "        std::vector<std::string> uuids;\n        uuids.reserve(pasted->count());\n        for (auto* obj : CCArrayExt<GameObject*>(pasted)) {",
    "        std::vector<std::string> uuids;\n        uuids.reserve(pasted->count());\n        bool haveAnchor = false;\n        float pasteAnchorX = 0.f;\n        float pasteAnchorY = 0.f;\n        for (auto* obj : CCArrayExt<GameObject*>(pasted)) {",
    "bulk paste sender anchor state",
)
hooks = replace_once(
    hooks,
    "            if (!obj) continue;\n            auto uuid = handler.getUUIDForObject(obj);",
    "            if (!obj) continue;\n            if (!haveAnchor) {\n                pasteAnchorX = obj->getPositionX();\n                pasteAnchorY = obj->getPositionY();\n                haveAnchor = true;\n            }\n            auto uuid = handler.getUUIDForObject(obj);",
    "bulk paste sender capture anchor",
)
hooks = replace_once(
    hooks,
    "            pasteId, totalChunks, static_cast<uint32_t>(uuids.size()), withColor, noUndo\n        );",
    "            pasteId, totalChunks, static_cast<uint32_t>(uuids.size()), withColor, noUndo,\n            pasteAnchorX, pasteAnchorY\n        );",
    "bulk paste sender transmit anchor",
)

# Track last accepted host music and enforce host-only local changes.
hooks = replace_once(
    hooks,
    "        bool m_wasPlaytesting = false;",
    "        bool m_wasPlaytesting = false;\n        int m_lastHostSongID = 0;\n        int m_lastHostAudioTrack = 0;\n        bool m_musicBaselineReady = false;",
    "host music fields",
)
hooks = replace_once(
    hooks,
    "    void levelSettingsUpdated() {\n        LevelEditorLayer::levelSettingsUpdated();\n\n        auto& handler = RemoteActionHandler::get();",
    "    void levelSettingsUpdated() {\n        LevelEditorLayer::levelSettingsUpdated();\n\n        auto& session = SessionManager::get();\n        if (session.isInSession() && this->m_level) {\n            int currentSong = this->m_level->m_songID;\n            int currentTrack = this->m_level->m_audioTrack;\n            if (!m_fields->m_musicBaselineReady) {\n                m_fields->m_lastHostSongID = currentSong;\n                m_fields->m_lastHostAudioTrack = currentTrack;\n                m_fields->m_musicBaselineReady = true;\n            } else if (session.getRole() == SessionManager::Role::Client &&\n                       (currentSong != m_fields->m_lastHostSongID || currentTrack != m_fields->m_lastHostAudioTrack)) {\n                this->m_level->m_songID = m_fields->m_lastHostSongID;\n                this->m_level->m_audioTrack = m_fields->m_lastHostAudioTrack;\n                Notification::create(\"Only the host can change music\", NotificationIcon::Warning)->show();\n                return;\n            } else if (session.getRole() == SessionManager::Role::Host &&\n                       (currentSong != m_fields->m_lastHostSongID || currentTrack != m_fields->m_lastHostAudioTrack)) {\n                m_fields->m_lastHostSongID = currentSong;\n                m_fields->m_lastHostAudioTrack = currentTrack;\n                std::string title;\n                if (currentSong > 0) {\n                    if (auto* song = LevelTools::getSongObject(currentSong)) {\n                        title = std::string(song->m_artistName.c_str()) + \" - \" + std::string(song->m_songName.c_str());\n                    }\n                    if (title.empty()) title = \"Song ID \" + std::to_string(currentSong);\n                } else {\n                    title = LevelTools::getAudioTitle(currentTrack);\n                    if (title.empty()) title = \"Official song \" + std::to_string(currentTrack);\n                }\n                auto music = proto::serializeMusicChanged(currentSong, currentTrack, title);\n                P2PManager::get().send(std::move(music), ChannelType::Reliable);\n                log::info(\"EditorHooks: host changed music to {} (songID={}, audioTrack={})\", title, currentSong, currentTrack);\n            }\n        }\n\n        auto& handler = RemoteActionHandler::get();",
    "host-only level music policy",
)
hooks = hooks.replace("        auto& session = SessionManager::get();\n        if (session.isInSession()) {\n            ActionSerializer::LevelSettingsData settings;", "        if (session.isInSession()) {\n            ActionSerializer::LevelSettingsData settings;", 1)
hooks_path.write_text(hooks, encoding="utf-8")

# Receiver: preserve sender's absolute placement by compensating local paste offset.
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")
remote = replace_once(
    remote,
    "            bool noUndo = false;\n            std::vector<std::string> dataChunks;",
    "            bool noUndo = false;\n            float anchorX = 0.f;\n            float anchorY = 0.f;\n            std::vector<std::string> dataChunks;",
    "bulk paste rx anchor state",
)
remote = replace_once(
    remote,
    "            state.withColor = msg.withColor;\n            state.noUndo = msg.noUndo;",
    "            state.withColor = msg.withColor;\n            state.noUndo = msg.noUndo;\n            state.anchorX = msg.anchorX;\n            state.anchorY = msg.anchorY;",
    "bulk paste rx save anchor",
)
remote = replace_once(
    remote,
    "            size_t index = 0;\n            for (auto* obj : CCArrayExt<GameObject*>(pasted)) {",
    "            GameObject* localAnchor = nullptr;\n            for (auto* obj : CCArrayExt<GameObject*>(pasted)) {\n                if (obj) { localAnchor = obj; break; }\n            }\n            float dx = localAnchor ? state.anchorX - localAnchor->getPositionX() : 0.f;\n            float dy = localAnchor ? state.anchorY - localAnchor->getPositionY() : 0.f;\n            if (localAnchor && (std::abs(dx) > 0.001f || std::abs(dy) > 0.001f)) {\n                for (auto* obj : CCArrayExt<GameObject*>(pasted)) {\n                    if (!obj) continue;\n                    obj->setPosition({obj->getPositionX() + dx, obj->getPositionY() + dy});\n                }\n                log::info(\"RemoteActionHandler: RAW bulk paste #{} anchor corrected by ({}, {})\", msg.pasteId, dx, dy);\n            }\n\n            size_t index = 0;\n            for (auto* obj : CCArrayExt<GameObject*>(pasted)) {",
    "bulk paste positional correction",
)

# MusicChanged is authoritative only from host (player 0). Apply + notify guests.
anchor = "        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {"
music_handler = '''        net.on(proto::Opcode::MusicChanged, [this](int playerId, proto::Reader& reader) {\n            auto msg = proto::deserializeMusicChanged(reader);\n            if (reader.hasError() || playerId != 0) return;\n            auto* editor = getEditorLayer();\n            if (!editor || !editor->m_level) return;\n            ProcessingRemoteGuard processingRemoteGuard(m_processingRemote);\n            editor->m_level->m_songID = msg.songID;\n            editor->m_level->m_audioTrack = msg.audioTrack;\n            editor->levelSettingsUpdated();\n            Notification::create(\"Host changed music: \" + msg.title, NotificationIcon::Info)->show();\n            log::info(\"RemoteActionHandler: host music applied: {}\", msg.title);\n        });\n\n'''
remote = replace_once(remote, anchor, music_handler + anchor, "MusicChanged handler")
remote_path.write_text(remote, encoding="utf-8")

print("Patched protocol v5: Object Workshop absolute anchor + host-only music notifications")