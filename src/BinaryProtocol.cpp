#include "BinaryProtocol.hpp"

namespace mpedit::proto {

    // ── Data helpers ─────────────────────────────────────────

    void writeObjectData(Writer& w, ActionSerializer::ObjectData const& obj) {
        w.writeString(obj.uuid);
        w.writeString(obj.saveString);
        w.writeVarInt(static_cast<uint32_t>(obj.objectID));
        w.writeF32(obj.x);
        w.writeF32(obj.y);
        w.writeF32(obj.rotation);
        w.writeF32(obj.scaleX);
        w.writeF32(obj.scaleY);
        uint8_t flags = 0;
        if (obj.flipX) flags |= 0x01;
        if (obj.flipY) flags |= 0x02;
        w.writeU8(flags);
        w.writeI32(obj.zOrder);
        w.writeVarInt(static_cast<uint32_t>(obj.editorLayer));
        w.writeVarInt(static_cast<uint32_t>(obj.editorLayer2));
        w.writeI32(obj.mainColorChannel);
        w.writeI32(obj.secondColorChannel);
        w.writeVarInt(static_cast<uint32_t>(obj.groups.size()));
        for (auto g : obj.groups) {
            w.writeVarInt(static_cast<uint32_t>(g));
        }
    }

    ActionSerializer::ObjectData readObjectData(Reader& r) {
        ActionSerializer::ObjectData obj;
        obj.uuid = r.readString();
        obj.saveString = r.readString();
        obj.objectID = static_cast<int>(r.readVarInt());
        obj.x = r.readF32();
        obj.y = r.readF32();
        obj.rotation = r.readF32();
        obj.scaleX = r.readF32();
        obj.scaleY = r.readF32();
        uint8_t flags = r.readU8();
        obj.flipX = (flags & 0x01) != 0;
        obj.flipY = (flags & 0x02) != 0;
        obj.zOrder = r.readI32();
        obj.editorLayer = static_cast<int>(r.readVarInt());
        obj.editorLayer2 = static_cast<int>(r.readVarInt());
        obj.mainColorChannel = r.readI32();
        obj.secondColorChannel = r.readI32();
        uint32_t groupCount = r.readVarInt();
        obj.groups.resize(groupCount);
        for (uint32_t i = 0; i < groupCount; ++i) {
            obj.groups[i] = static_cast<int>(r.readVarInt());
        }
        return obj;
    }

    void writeMoveData(Writer& w, ActionSerializer::MoveData const& move) {
        w.writeString(move.uuid);
        w.writeF32(move.dx);
        w.writeF32(move.dy);
    }

    ActionSerializer::MoveData readMoveData(Reader& r) {
        ActionSerializer::MoveData m;
        m.uuid = r.readString();
        m.dx = r.readF32();
        m.dy = r.readF32();
        return m;
    }

    void writeTransformData(Writer& w, ActionSerializer::TransformData const& t) {
        w.writeString(t.uuid);
        w.writeF32(t.rotation);
        w.writeF32(t.scaleX);
        w.writeF32(t.scaleY);
        uint8_t flags = 0;
        if (t.flipX) flags |= 0x01;
        if (t.flipY) flags |= 0x02;
        w.writeU8(flags);
    }

    ActionSerializer::TransformData readTransformData(Reader& r) {
        ActionSerializer::TransformData t;
        t.uuid = r.readString();
        t.rotation = r.readF32();
        t.scaleX = r.readF32();
        t.scaleY = r.readF32();
        uint8_t flags = r.readU8();
        t.flipX = (flags & 0x01) != 0;
        t.flipY = (flags & 0x02) != 0;
        return t;
    }

    void writeReconcileData(Writer& w, ActionSerializer::ReconcileData const& r) {
        w.writeString(r.uuid);
        w.writeF32(r.x);
        w.writeF32(r.y);
        w.writeF32(r.rotation);
        w.writeF32(r.scaleX);
        w.writeF32(r.scaleY);
        uint8_t flags = 0;
        if (r.flipX) flags |= 0x01;
        if (r.flipY) flags |= 0x02;
        w.writeU8(flags);
    }

    ActionSerializer::ReconcileData readReconcileData(Reader& r) {
        ActionSerializer::ReconcileData data;
        data.uuid = r.readString();
        data.x = r.readF32();
        data.y = r.readF32();
        data.rotation = r.readF32();
        data.scaleX = r.readF32();
        data.scaleY = r.readF32();
        uint8_t flags = r.readU8();
        data.flipX = (flags & 0x01) != 0;
        data.flipY = (flags & 0x02) != 0;
        return data;
    }

    void writeLockData(Writer& w, ActionSerializer::LockData const& lock) {
        w.writeString(lock.uuid);
        w.writeVarInt(static_cast<uint32_t>(lock.playerId));
        w.writeF32(lock.timeLeft);
    }

    ActionSerializer::LockData readLockData(Reader& r) {
        ActionSerializer::LockData l;
        l.uuid = r.readString();
        l.playerId = static_cast<int>(r.readVarInt());
        l.timeLeft = r.readF32();
        return l;
    }

    void writeSettingsData(Writer& w, ActionSerializer::LevelSettingsData const& s) {
        w.writeString(s.saveString);
        w.writeVarInt(static_cast<uint32_t>(s.audioTrack));
        w.writeVarInt(static_cast<uint32_t>(s.songID));
        w.writeF32(s.levelLength);
    }

    ActionSerializer::LevelSettingsData readSettingsData(Reader& r) {
        ActionSerializer::LevelSettingsData s;
        s.saveString = r.readString();
        s.audioTrack = static_cast<int>(r.readVarInt());
        s.songID = static_cast<int>(r.readVarInt());
        s.levelLength = r.readF32();
        return s;
    }

    // ── Complete message serializers ─────────────────────────

    std::vector<uint8_t> serializePlaceObjects(
        std::vector<ActionSerializer::ObjectData> const& objects)
    {
        Writer w;
        w.writeOpcode(Opcode::PlaceObjects);
        w.writeVarInt(static_cast<uint32_t>(objects.size()));
        for (auto const& obj : objects) {
            writeObjectData(w, obj);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeDeleteObjects(
        std::vector<std::string> const& uuids)
    {
        Writer w;
        w.writeOpcode(Opcode::DeleteObjects);
        w.writeVarInt(static_cast<uint32_t>(uuids.size()));
        for (auto const& uuid : uuids) {
            w.writeString(uuid);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeMoveObjects(
        std::vector<ActionSerializer::MoveData> const& moves)
    {
        Writer w;
        w.writeOpcode(Opcode::MoveObjects);
        w.writeVarInt(static_cast<uint32_t>(moves.size()));
        for (auto const& m : moves) {
            writeMoveData(w, m);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeTransformObjects(
        std::vector<ActionSerializer::TransformData> const& transforms)
    {
        Writer w;
        w.writeOpcode(Opcode::TransformObjects);
        w.writeVarInt(static_cast<uint32_t>(transforms.size()));
        for (auto const& t : transforms) {
            writeTransformData(w, t);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeReconcileObjects(
        std::vector<ActionSerializer::ReconcileData> const& reconciles)
    {
        Writer w;
        w.writeOpcode(Opcode::ReconcileObjects);
        w.writeVarInt(static_cast<uint32_t>(reconciles.size()));
        for (auto const& r : reconciles) {
            writeReconcileData(w, r);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeUpdateObjects(
        std::vector<ActionSerializer::ObjectData> const& objects)
    {
        Writer w;
        w.writeOpcode(Opcode::UpdateObjects);
        w.writeVarInt(static_cast<uint32_t>(objects.size()));
        for (auto const& obj : objects) {
            writeObjectData(w, obj);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeLockObjects(
        std::vector<std::string> const& uuids, bool locked)
    {
        Writer w;
        w.writeOpcode(Opcode::LockObjects);
        w.writeBool(locked);
        w.writeVarInt(static_cast<uint32_t>(uuids.size()));
        for (auto const& uuid : uuids) {
            w.writeString(uuid);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeCursorUpdate(
        float x, float y, std::string const& status)
    {
        Writer w;
        w.writeOpcode(Opcode::CursorUpdate);
        w.writeF32(x);
        w.writeF32(y);
        w.writeString(status);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeMoveBatch(
        std::vector<ActionSerializer::MoveData> const& moves)
    {
        Writer w;
        w.writeOpcode(Opcode::MoveBatch);
        w.writeVarInt(static_cast<uint32_t>(moves.size()));
        for (auto const& m : moves) {
            writeMoveData(w, m);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeUpdateSettings(
        ActionSerializer::LevelSettingsData const& settings)
    {
        Writer w;
        w.writeOpcode(Opcode::UpdateSettings);
        writeSettingsData(w, settings);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeSyncLevelStart(
        uint32_t totalChunks, uint32_t totalObjects,
        ActionSerializer::LevelSettingsData const& settings)
    {
        Writer w;
        w.writeOpcode(Opcode::SyncLevelStart);
        w.writeVarInt(totalChunks);
        w.writeVarInt(totalObjects);
        writeSettingsData(w, settings);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeSyncLevelChunk(
        uint32_t chunkIndex, const uint8_t* data, size_t dataLen,
        std::vector<std::string> const& uuids)
    {
        Writer w;
        w.writeOpcode(Opcode::SyncLevelChunk);
        w.writeVarInt(chunkIndex);
        w.writeVarInt(static_cast<uint32_t>(dataLen));
        w.writeBytes(data, dataLen);
        w.writeVarInt(static_cast<uint32_t>(uuids.size()));
        for (auto const& uuid : uuids) {
            w.writeString(uuid);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeSyncLevelEnd(
        std::vector<ActionSerializer::LockData> const& locks)
    {
        Writer w;
        w.writeOpcode(Opcode::SyncLevelEnd);
        w.writeVarInt(static_cast<uint32_t>(locks.size()));
        for (auto const& lock : locks) {
            writeLockData(w, lock);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializePlayerJoined(
        int playerId, std::string const& name, int colorIndex)
    {
        Writer w;
        w.writeOpcode(Opcode::PlayerJoined);
        w.writeVarInt(static_cast<uint32_t>(playerId));
        w.writeString(name);
        w.writeVarInt(static_cast<uint32_t>(colorIndex));
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializePlayerLeft(int playerId) {
        Writer w;
        w.writeOpcode(Opcode::PlayerLeft);
        w.writeVarInt(static_cast<uint32_t>(playerId));
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion) {
        Writer w;
        w.writeOpcode(Opcode::ProtocolHello);
        w.writeVarInt(protocolVersion);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeReliableEnvelope(
        uint32_t sequence, std::vector<uint8_t> const& payload)
    {
        Writer w(payload.size() + 16);
        w.writeOpcode(Opcode::ReliableEnvelope);
        w.writeVarInt(sequence);
        w.writeVarInt(static_cast<uint32_t>(payload.size()));
        if (!payload.empty()) w.writeBytes(payload.data(), payload.size());
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeReliableAck(uint32_t sequence) {
        Writer w;
        w.writeOpcode(Opcode::ReliableAck);
        w.writeVarInt(sequence);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeLevelDigest(uint32_t objectCount, std::string const& hash) {
        Writer w;
        w.writeOpcode(Opcode::LevelDigest);
        w.writeVarInt(objectCount);
        w.writeString(hash);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeLevelManifest(
        uint32_t scanId, uint32_t chunkIndex, uint32_t totalChunks,
        std::vector<LevelManifestEntry> const& entries)
    {
        Writer w;
        w.writeOpcode(Opcode::LevelManifest);
        w.writeVarInt(scanId);
        w.writeVarInt(chunkIndex);
        w.writeVarInt(totalChunks);
        w.writeVarInt(static_cast<uint32_t>(entries.size()));
        for (auto const& entry : entries) {
            w.writeString(entry.uuid);
            w.writeString(entry.hash);
        }
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeLevelRepairRequest(
        uint32_t scanId,
        std::vector<std::string> const& missing,
        std::vector<std::string> const& changed)
    {
        Writer w;
        w.writeOpcode(Opcode::LevelRepairRequest);
        w.writeVarInt(scanId);
        w.writeVarInt(static_cast<uint32_t>(missing.size()));
        for (auto const& uuid : missing) w.writeString(uuid);
        w.writeVarInt(static_cast<uint32_t>(changed.size()));
        for (auto const& uuid : changed) w.writeString(uuid);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeFullResyncRequest() {
        Writer w;
        w.writeOpcode(Opcode::FullResyncRequest);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeInitialSyncRequest() {
        Writer w;
        w.writeOpcode(Opcode::InitialSyncRequest);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeBulkPasteStart(
        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,
        bool withColor, bool noUndo, float anchorX, float anchorY)
    {
        Writer w;
        w.writeOpcode(Opcode::BulkPasteStart);
        w.writeVarInt(pasteId);
        w.writeVarInt(totalChunks);
        w.writeVarInt(totalObjects);
        w.writeBool(withColor);
        w.writeBool(noUndo);
        w.writeF32(anchorX);
        w.writeF32(anchorY);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeBulkPasteChunk(
        uint32_t pasteId, uint32_t chunkIndex, std::string const& data,
        std::vector<std::string> const& uuids)
    {
        Writer w(data.size() + uuids.size() * 40 + 32);
        w.writeOpcode(Opcode::BulkPasteChunk);
        w.writeVarInt(pasteId);
        w.writeVarInt(chunkIndex);
        w.writeString(data);
        w.writeVarInt(static_cast<uint32_t>(uuids.size()));
        for (auto const& uuid : uuids) w.writeString(uuid);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId) {
        Writer w;
        w.writeOpcode(Opcode::BulkPasteEnd);
        w.writeVarInt(pasteId);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeGlobalRevision(uint32_t revision, int authorPlayerId) {
        Writer w;
        w.writeOpcode(Opcode::GlobalRevision);
        w.writeVarInt(revision);
        w.writeI32(authorPlayerId);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeSharedDigest(
        uint32_t revision, uint32_t objectCount, std::string const& hash)
    {
        Writer w;
        w.writeOpcode(Opcode::SharedDigest);
        w.writeVarInt(revision);
        w.writeVarInt(objectCount);
        w.writeString(hash);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeGlobalSnapshotRequest(uint32_t revision) {
        Writer w;
        w.writeOpcode(Opcode::GlobalSnapshotRequest);
        w.writeVarInt(revision);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeKickPlayer(int targetPlayerId, std::string const& reason) {
        Writer w;
        w.writeOpcode(Opcode::KickPlayer);
        w.writeI32(targetPlayerId);
        w.writeString(reason);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title) {
        Writer w;
        w.writeOpcode(Opcode::MusicChanged);
        w.writeI32(songID);
        w.writeI32(audioTrack);
        w.writeString(title);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeRoomSettingsChanged(
        uint32_t maxPlayers, bool allowBuild, bool allowDelete, bool allowWorkshop,
        bool allowLevelSettings, bool autoRepair, bool locked)
    {
        Writer w;
        w.writeOpcode(Opcode::RoomSettingsChanged);
        w.writeVarInt(maxPlayers);
        w.writeBool(allowBuild);
        w.writeBool(allowDelete);
        w.writeBool(allowWorkshop);
        w.writeBool(allowLevelSettings);
        w.writeBool(autoRepair);
        w.writeBool(locked);
        return std::move(w.takeData());
    }

    std::vector<uint8_t> serializeError(std::string const& message) {
        Writer w;
        w.writeOpcode(Opcode::Error);
        w.writeString(message);
        return std::move(w.takeData());
    }

    // ── Deserialization ──────────────────────────────────────

    PlaceObjectsMsg deserializePlaceObjects(Reader& r) {
        PlaceObjectsMsg msg;
        uint32_t count = r.readVarInt();
        msg.objects.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.objects.push_back(readObjectData(r));
        }
        return msg;
    }

    DeleteObjectsMsg deserializeDeleteObjects(Reader& r) {
        DeleteObjectsMsg msg;
        uint32_t count = r.readVarInt();
        msg.uuids.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.uuids.push_back(r.readString());
        }
        return msg;
    }

    MoveObjectsMsg deserializeMoveObjects(Reader& r) {
        MoveObjectsMsg msg;
        uint32_t count = r.readVarInt();
        msg.moves.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.moves.push_back(readMoveData(r));
        }
        return msg;
    }

    TransformObjectsMsg deserializeTransformObjects(Reader& r) {
        TransformObjectsMsg msg;
        uint32_t count = r.readVarInt();
        msg.transforms.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.transforms.push_back(readTransformData(r));
        }
        return msg;
    }

    ReconcileObjectsMsg deserializeReconcileObjects(Reader& r) {
        ReconcileObjectsMsg msg;
        uint32_t count = r.readVarInt();
        msg.reconciles.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.reconciles.push_back(readReconcileData(r));
        }
        return msg;
    }

    UpdateObjectsMsg deserializeUpdateObjects(Reader& r) {
        UpdateObjectsMsg msg;
        uint32_t count = r.readVarInt();
        msg.objects.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.objects.push_back(readObjectData(r));
        }
        return msg;
    }

    LockObjectsMsg deserializeLockObjects(Reader& r) {
        LockObjectsMsg msg;
        msg.locked = r.readBool();
        uint32_t count = r.readVarInt();
        msg.uuids.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.uuids.push_back(r.readString());
        }
        return msg;
    }

    CursorUpdateMsg deserializeCursorUpdate(Reader& r) {
        CursorUpdateMsg msg;
        msg.x = r.readF32();
        msg.y = r.readF32();
        msg.status = r.readString();
        return msg;
    }

    MoveBatchMsg deserializeMoveBatch(Reader& r) {
        MoveBatchMsg msg;
        uint32_t count = r.readVarInt();
        msg.moves.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            msg.moves.push_back(readMoveData(r));
        }
        return msg;
    }

    SyncLevelStartMsg deserializeSyncLevelStart(Reader& r) {
        SyncLevelStartMsg msg;
        msg.totalChunks = r.readVarInt();
        msg.totalObjects = r.readVarInt();
        msg.settings = readSettingsData(r);
        return msg;
    }

    SyncLevelChunkMsg deserializeSyncLevelChunk(Reader& r) {
        SyncLevelChunkMsg msg;
        msg.chunkIndex = r.readVarInt();
        uint32_t dataLen = r.readVarInt();
        msg.data.resize(dataLen);
        if (dataLen > 0) {
            const uint8_t* ptr = r.currentPtr();
            std::memcpy(msg.data.data(), ptr, dataLen);
            r.skip(dataLen);
        }
        uint32_t uuidCount = r.readVarInt();
        msg.uuids.reserve(uuidCount);
        for (uint32_t i = 0; i < uuidCount; ++i) {
            msg.uuids.push_back(r.readString());
        }
        return msg;
    }

    SyncLevelEndMsg deserializeSyncLevelEnd(Reader& r) {
        SyncLevelEndMsg msg;
        uint32_t lockCount = r.readVarInt();
        msg.locks.reserve(lockCount);
        for (uint32_t i = 0; i < lockCount; ++i) {
            msg.locks.push_back(readLockData(r));
        }
        return msg;
    }

    PlayerJoinedMsg deserializePlayerJoined(Reader& r) {
        PlayerJoinedMsg msg;
        msg.playerId = static_cast<int>(r.readVarInt());
        msg.name = r.readString();
        msg.colorIndex = static_cast<int>(r.readVarInt());
        return msg;
    }

    PlayerLeftMsg deserializePlayerLeft(Reader& r) {
        PlayerLeftMsg msg;
        msg.playerId = static_cast<int>(r.readVarInt());
        return msg;
    }

    ProtocolHelloMsg deserializeProtocolHello(Reader& r) {
        ProtocolHelloMsg msg;
        msg.protocolVersion = r.readVarInt();
        return msg;
    }

    ReliableEnvelopeMsg deserializeReliableEnvelope(Reader& r) {
        ReliableEnvelopeMsg msg;
        msg.sequence = r.readVarInt();
        uint32_t len = r.readVarInt();
        if (r.hasError() || len > r.remaining()) return msg;
        msg.payload.assign(r.currentPtr(), r.currentPtr() + len);
        r.skip(len);
        return msg;
    }

    ReliableAckMsg deserializeReliableAck(Reader& r) {
        ReliableAckMsg msg;
        msg.sequence = r.readVarInt();
        return msg;
    }

    LevelDigestMsg deserializeLevelDigest(Reader& r) {
        LevelDigestMsg msg;
        msg.objectCount = r.readVarInt();
        msg.hash = r.readString();
        return msg;
    }

    LevelManifestMsg deserializeLevelManifest(Reader& r) {
        LevelManifestMsg msg;
        msg.scanId = r.readVarInt();
        msg.chunkIndex = r.readVarInt();
        msg.totalChunks = r.readVarInt();
        uint32_t count = r.readVarInt();
        msg.entries.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            LevelManifestEntry entry;
            entry.uuid = r.readString();
            entry.hash = r.readString();
            msg.entries.push_back(std::move(entry));
        }
        return msg;
    }

    LevelRepairRequestMsg deserializeLevelRepairRequest(Reader& r) {
        LevelRepairRequestMsg msg;
        msg.scanId = r.readVarInt();
        uint32_t missingCount = r.readVarInt();
        msg.missing.reserve(missingCount);
        for (uint32_t i = 0; i < missingCount; ++i) msg.missing.push_back(r.readString());
        uint32_t changedCount = r.readVarInt();
        msg.changed.reserve(changedCount);
        for (uint32_t i = 0; i < changedCount; ++i) msg.changed.push_back(r.readString());
        return msg;
    }

    FullResyncRequestMsg deserializeFullResyncRequest(Reader&) {
        return {};
    }

    BulkPasteStartMsg deserializeBulkPasteStart(Reader& r) {
        BulkPasteStartMsg msg;
        msg.pasteId = r.readVarInt();
        msg.totalChunks = r.readVarInt();
        msg.totalObjects = r.readVarInt();
        msg.withColor = r.readBool();
        msg.noUndo = r.readBool();
        msg.anchorX = r.readF32();
        msg.anchorY = r.readF32();
        return msg;
    }

    BulkPasteChunkMsg deserializeBulkPasteChunk(Reader& r) {
        BulkPasteChunkMsg msg;
        msg.pasteId = r.readVarInt();
        msg.chunkIndex = r.readVarInt();
        msg.data = r.readString();
        uint32_t count = r.readVarInt();
        msg.uuids.reserve(count);
        for (uint32_t i = 0; i < count; ++i) msg.uuids.push_back(r.readString());
        return msg;
    }

    BulkPasteEndMsg deserializeBulkPasteEnd(Reader& r) {
        BulkPasteEndMsg msg;
        msg.pasteId = r.readVarInt();
        return msg;
    }

    GlobalRevisionMsg deserializeGlobalRevision(Reader& r) {
        GlobalRevisionMsg msg;
        msg.revision = r.readVarInt();
        msg.authorPlayerId = r.readI32();
        return msg;
    }

    SharedDigestMsg deserializeSharedDigest(Reader& r) {
        SharedDigestMsg msg;
        msg.revision = r.readVarInt();
        msg.objectCount = r.readVarInt();
        msg.hash = r.readString();
        return msg;
    }

    GlobalSnapshotRequestMsg deserializeGlobalSnapshotRequest(Reader& r) {
        GlobalSnapshotRequestMsg msg;
        msg.revision = r.readVarInt();
        return msg;
    }

    KickPlayerMsg deserializeKickPlayer(Reader& r) {
        KickPlayerMsg msg;
        msg.targetPlayerId = r.readI32();
        msg.reason = r.readString();
        return msg;
    }

    MusicChangedMsg deserializeMusicChanged(Reader& r) {
        MusicChangedMsg msg;
        msg.songID = r.readI32();
        msg.audioTrack = r.readI32();
        msg.title = r.readString();
        return msg;
    }

    RoomSettingsChangedMsg deserializeRoomSettingsChanged(Reader& r) {
        RoomSettingsChangedMsg msg;
        msg.maxPlayers = r.readVarInt();
        msg.allowBuild = r.readBool();
        msg.allowDelete = r.readBool();
        msg.allowWorkshop = r.readBool();
        msg.allowLevelSettings = r.readBool();
        msg.autoRepair = r.readBool();
        msg.locked = r.readBool();
        return msg;
    }

    ErrorMsg deserializeError(Reader& r) {
        ErrorMsg msg;
        msg.message = r.readString();
        return msg;
    }

    UpdateSettingsMsg deserializeUpdateSettings(Reader& r) {
        UpdateSettingsMsg msg;
        msg.settings = readSettingsData(r);
        return msg;
    }

    std::vector<uint8_t> serializeRoomInfo(std::vector<RoomInfoPlayer> const& players) {
        Writer w;
        w.writeOpcode(Opcode::RoomInfo);
        w.writeVarInt(static_cast<uint32_t>(players.size()));
        for (auto const& p : players) {
            w.writeVarInt(static_cast<uint32_t>(p.id));
            w.writeString(p.name);
            w.writeVarInt(static_cast<uint32_t>(p.colorIndex));
        }
        return w.takeData();
    }

    RoomInfoMsg deserializeRoomInfo(Reader& r) {
        RoomInfoMsg msg;
        uint32_t count = r.readVarInt();
        msg.players.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            RoomInfoPlayer p;
            p.id = static_cast<int>(r.readVarInt());
            p.name = r.readString();
            p.colorIndex = static_cast<int>(r.readVarInt());
            msg.players.push_back(p);
        }
        return msg;
    }

} // namespace mpedit::proto
