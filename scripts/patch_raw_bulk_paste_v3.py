from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


def replace_function(text: str, signature: str, new_func: str, label: str) -> str:
    start = text.find(signature)
    if start == -1:
        raise SystemExit(f"{label}: function signature not found")
    brace = text.find('{', start)
    if brace == -1:
        raise SystemExit(f"{label}: opening brace not found")
    depth = 0
    end = -1
    for i in range(brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise SystemExit(f"{label}: closing brace not found")
    return text[:start] + new_func + text[end:]


# =============================================================================
# Protocol v3: exact/raw bulk paste stream.
# Object Workshop and similar mods already pass the canonical structure string
# to EditorUI::pasteObjects. Preserve that exact string instead of decomposing
# it into per-object getSaveString() snapshots.
# =============================================================================
proto_hpp_path = Path("src/BinaryProtocol.hpp")
proto_hpp = proto_hpp_path.read_text(encoding="utf-8")
proto_hpp = replace_once(
    proto_hpp,
    '''        InitialSyncRequest = 0x3C,\n\n        // Cursor (unreliable channel)''',
    '''        InitialSyncRequest = 0x3C,\n        BulkPasteStart     = 0x3D,\n        BulkPasteChunk     = 0x3E,\n        BulkPasteEnd       = 0x3F,\n\n        // Cursor (unreliable channel)''',
    "raw bulk paste opcodes",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    std::vector<uint8_t> serializeInitialSyncRequest();\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    '''    std::vector<uint8_t> serializeInitialSyncRequest();\n\n    std::vector<uint8_t> serializeBulkPasteStart(\n        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,\n        bool withColor, bool noUndo);\n    std::vector<uint8_t> serializeBulkPasteChunk(\n        uint32_t pasteId, uint32_t chunkIndex, std::string const& data,\n        std::vector<std::string> const& uuids);\n    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId);\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    "raw bulk paste serializer declarations",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    struct ErrorMsg {\n        std::string message;\n    };''',
    '''    struct BulkPasteStartMsg {\n        uint32_t pasteId = 0;\n        uint32_t totalChunks = 0;\n        uint32_t totalObjects = 0;\n        bool withColor = false;\n        bool noUndo = false;\n    };\n    BulkPasteStartMsg deserializeBulkPasteStart(Reader& r);\n\n    struct BulkPasteChunkMsg {\n        uint32_t pasteId = 0;\n        uint32_t chunkIndex = 0;\n        std::string data;\n        std::vector<std::string> uuids;\n    };\n    BulkPasteChunkMsg deserializeBulkPasteChunk(Reader& r);\n\n    struct BulkPasteEndMsg {\n        uint32_t pasteId = 0;\n    };\n    BulkPasteEndMsg deserializeBulkPasteEnd(Reader& r);\n\n    struct ErrorMsg {\n        std::string message;\n    };''',
    "raw bulk paste deserializer declarations",
)
proto_hpp_path.write_text(proto_hpp, encoding="utf-8")

proto_cpp_path = Path("src/BinaryProtocol.cpp")
proto_cpp = proto_cpp_path.read_text(encoding="utf-8")
proto_cpp = replace_once(
    proto_cpp,
    '''    std::vector<uint8_t> serializeInitialSyncRequest() {\n        Writer w;\n        w.writeOpcode(Opcode::InitialSyncRequest);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    '''    std::vector<uint8_t> serializeInitialSyncRequest() {\n        Writer w;\n        w.writeOpcode(Opcode::InitialSyncRequest);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeBulkPasteStart(\n        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,\n        bool withColor, bool noUndo)\n    {\n        Writer w;\n        w.writeOpcode(Opcode::BulkPasteStart);\n        w.writeVarInt(pasteId);\n        w.writeVarInt(totalChunks);\n        w.writeVarInt(totalObjects);\n        w.writeBool(withColor);\n        w.writeBool(noUndo);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeBulkPasteChunk(\n        uint32_t pasteId, uint32_t chunkIndex, std::string const& data,\n        std::vector<std::string> const& uuids)\n    {\n        Writer w(data.size() + uuids.size() * 40 + 32);\n        w.writeOpcode(Opcode::BulkPasteChunk);\n        w.writeVarInt(pasteId);\n        w.writeVarInt(chunkIndex);\n        w.writeString(data);\n        w.writeVarInt(static_cast<uint32_t>(uuids.size()));\n        for (auto const& uuid : uuids) w.writeString(uuid);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId) {\n        Writer w;\n        w.writeOpcode(Opcode::BulkPasteEnd);\n        w.writeVarInt(pasteId);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    "raw bulk paste serializers",
)
# Insert deserializers immediately before deserializeError.
proto_cpp = replace_once(
    proto_cpp,
    '''    ErrorMsg deserializeError(Reader& r) {''',
    '''    BulkPasteStartMsg deserializeBulkPasteStart(Reader& r) {\n        BulkPasteStartMsg msg;\n        msg.pasteId = r.readVarInt();\n        msg.totalChunks = r.readVarInt();\n        msg.totalObjects = r.readVarInt();\n        msg.withColor = r.readBool();\n        msg.noUndo = r.readBool();\n        return msg;\n    }\n\n    BulkPasteChunkMsg deserializeBulkPasteChunk(Reader& r) {\n        BulkPasteChunkMsg msg;\n        msg.pasteId = r.readVarInt();\n        msg.chunkIndex = r.readVarInt();\n        msg.data = r.readString();\n        uint32_t count = r.readVarInt();\n        msg.uuids.reserve(count);\n        for (uint32_t i = 0; i < count; ++i) msg.uuids.push_back(r.readString());\n        return msg;\n    }\n\n    BulkPasteEndMsg deserializeBulkPasteEnd(Reader& r) {\n        BulkPasteEndMsg msg;\n        msg.pasteId = r.readVarInt();\n        return msg;\n    }\n\n    ErrorMsg deserializeError(Reader& r) {''',
    "raw bulk paste deserializers",
)
proto_cpp_path.write_text(proto_cpp, encoding="utf-8")


# =============================================================================
# P2P: v3 + carry bulk-paste frames through the same ACK/FIFO path.
# =============================================================================
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(
    p2p,
    'constexpr uint32_t kProtocolVersion = 2;',
    'constexpr uint32_t kProtocolVersion = 3;',
    "protocol v3",
)
p2p = replace_once(
    p2p,
    '''                        opcode == proto::Opcode::FullResyncRequest;''',
    '''                        opcode == proto::Opcode::FullResyncRequest ||\n                        opcode == proto::Opcode::BulkPasteStart ||\n                        opcode == proto::Opcode::BulkPasteChunk ||\n                        opcode == proto::Opcode::BulkPasteEnd;''',
    "bulk paste frames in ACK FIFO",
)
p2p_path.write_text(p2p, encoding="utf-8")


# =============================================================================
# Sender: replace per-object bulk-paste serialization with exact structure data.
# =============================================================================
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
new_paste = r'''    cocos2d::CCArray* pasteObjects(gd::string str, bool withColor, bool noUndo) {
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

        if (!pasted || pasted->count() == 0) return pasted;

        // Assign UUIDs in the exact order returned by the native paste operation.
        // The receiver performs the same paste and binds these UUIDs by the same
        // returned-array order, avoiding lossy per-object reconstruction.
        std::vector<std::string> uuids;
        uuids.reserve(pasted->count());
        for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
            if (!obj) continue;
            auto uuid = handler.getUUIDForObject(obj);
            if (uuid.empty()) {
                uuid = RemoteActionHandler::generateUUID();
                handler.registerObject(uuid, obj);
            }
            uuids.push_back(uuid);
            MessageBatcher::get().removePending(uuid);
        }

        static uint32_t s_nextBulkPasteId = 1;
        uint32_t pasteId = s_nextBulkPasteId++;
        if (pasteId == 0) pasteId = s_nextBulkPasteId++;

        std::string raw = std::string(str);
        constexpr size_t kRawBytesPerChunk = 12000;
        constexpr size_t kUuidsPerChunk = 200;
        size_t dataChunks = std::max<size_t>(1, (raw.size() + kRawBytesPerChunk - 1) / kRawBytesPerChunk);
        size_t uuidChunks = std::max<size_t>(1, (uuids.size() + kUuidsPerChunk - 1) / kUuidsPerChunk);
        uint32_t totalChunks = static_cast<uint32_t>(std::max(dataChunks, uuidChunks));

        auto start = proto::serializeBulkPasteStart(
            pasteId, totalChunks, static_cast<uint32_t>(uuids.size()), withColor, noUndo
        );
        P2PManager::get().send(std::move(start), ChannelType::Reliable);

        for (uint32_t i = 0; i < totalChunks; ++i) {
            size_t dataOffset = static_cast<size_t>(i) * kRawBytesPerChunk;
            size_t uuidOffset = static_cast<size_t>(i) * kUuidsPerChunk;
            std::string dataChunk;
            std::vector<std::string> uuidChunk;

            if (dataOffset < raw.size()) {
                dataChunk = raw.substr(dataOffset, std::min(kRawBytesPerChunk, raw.size() - dataOffset));
            }
            if (uuidOffset < uuids.size()) {
                size_t count = std::min(kUuidsPerChunk, uuids.size() - uuidOffset);
                uuidChunk.insert(uuidChunk.end(), uuids.begin() + uuidOffset, uuids.begin() + uuidOffset + count);
            }

            auto chunk = proto::serializeBulkPasteChunk(pasteId, i, dataChunk, uuidChunk);
            P2PManager::get().send(std::move(chunk), ChannelType::Reliable);
        }

        auto end = proto::serializeBulkPasteEnd(pasteId);
        P2PManager::get().send(std::move(end), ChannelType::Reliable);

        log::info(
            "EditorHooks: RAW bulk paste #{} synced {} objects, {} bytes in {} chunks",
            pasteId, uuids.size(), raw.size(), totalChunks
        );
        return pasted;
    }'''
hooks = replace_function(
    hooks,
    '    cocos2d::CCArray* pasteObjects(gd::string str, bool withColor, bool noUndo)',
    new_paste,
    "raw bulk paste sender hook",
)
hooks_path.write_text(hooks, encoding="utf-8")


# =============================================================================
# Receiver: reassemble exact string, execute native paste once, bind UUIDs.
# =============================================================================
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")
remote = replace_once(
    remote,
    '''    namespace {\n        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {''',
    '''    namespace {\n        struct RawBulkPasteRx {\n            bool active = false;\n            uint32_t pasteId = 0;\n            uint32_t totalChunks = 0;\n            uint32_t totalObjects = 0;\n            bool withColor = false;\n            bool noUndo = false;\n            std::vector<std::string> dataChunks;\n            std::vector<std::vector<std::string>> uuidChunks;\n            std::vector<bool> received;\n        };\n        std::unordered_map<int, RawBulkPasteRx> s_rawBulkPasteRx;\n\n        std::set<GameObject*> snapshotExistingObjects(LevelEditorLayer* editor) {''',
    "raw bulk paste receive state",
)
anchor = '''        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {'''
handlers = r'''        net.on(proto::Opcode::BulkPasteStart, [this](int playerId, proto::Reader& reader) {
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

            size_t index = 0;
            for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
                if (!obj) continue;
                if (index < uuids.size()) registerObject(uuids[index], obj);
                else registerObject(RemoteActionHandler::generateUUID(), obj);
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

'''
remote = replace_once(remote, anchor, handlers + anchor, "raw bulk paste receive handlers")
remote_path.write_text(remote, encoding="utf-8")

print("Patched protocol v3 raw bulk-paste synchronization")
