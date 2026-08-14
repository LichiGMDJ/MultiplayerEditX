#pragma once

#include "ActionSerializer.hpp"
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <stdexcept>

namespace mpedit::proto {

    // ── Opcodes (1 byte) ──────────────────────────────────────
    // Reliable channel opcodes
    enum class Opcode : uint8_t {
        // Object editing (reliable channel)
        PlaceObjects      = 0x01,
        DeleteObjects     = 0x02,
        MoveObjects       = 0x03,
        TransformObjects  = 0x04,
        UpdateObjects     = 0x05,
        LockObjects       = 0x06,
        ReconcileObjects  = 0x07,

        // Level sync (reliable channel, chunked)
        SyncLevelStart    = 0x10,
        SyncLevelChunk    = 0x11,
        SyncLevelEnd      = 0x12,

        // Settings (reliable channel)
        UpdateSettings    = 0x20,

        // Session management (reliable channel)
        PlayerJoined      = 0x30,
        PlayerLeft        = 0x31,
        RoomInfo          = 0x32,
        HostMigration     = 0x33,
        Reconnect         = 0x34,
        ProtocolHello     = 0x35,
        ReliableEnvelope = 0x36,
        ReliableAck      = 0x37,
        LevelDigest      = 0x38,
        LevelManifest    = 0x39,
        LevelRepairRequest = 0x3A,
        FullResyncRequest  = 0x3B,
        InitialSyncRequest = 0x3C,
        BulkPasteStart     = 0x3D,
        BulkPasteChunk     = 0x3E,
        BulkPasteEnd       = 0x3F,

        // Global shared-state coordination (reliable channel)
        GlobalRevision        = 0x42,
        SharedDigest          = 0x43,
        GlobalSnapshotRequest = 0x44,
        KickPlayer            = 0x45,
        MusicChanged          = 0x46,
        RoomSettingsChanged   = 0x47,

        // Cursor (unreliable channel)
        CursorUpdate      = 0x40,

        // Batched moves during drag (unreliable channel)
        MoveBatch         = 0x41,

        // Error
        Error             = 0xFF,
    };

    // ── Writer ────────────────────────────────────────────────
    // Builds a binary message buffer. Little-endian byte order.

    class Writer {
    public:
        Writer() { m_buf.reserve(256); }
        explicit Writer(size_t reserve) { m_buf.reserve(reserve); }

        void writeU8(uint8_t v) {
            m_buf.push_back(v);
        }

        void writeU16(uint16_t v) {
            m_buf.push_back(static_cast<uint8_t>(v & 0xFF));
            m_buf.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
        }

        void writeU32(uint32_t v) {
            m_buf.push_back(static_cast<uint8_t>(v & 0xFF));
            m_buf.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
            m_buf.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
            m_buf.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
        }

        void writeI32(int32_t v) {
            writeU32(static_cast<uint32_t>(v));
        }

        void writeF32(float v) {
            uint32_t bits;
            std::memcpy(&bits, &v, sizeof(bits));
            writeU32(bits);
        }

        // Variable-length integer encoding (1-5 bytes for uint32_t)
        void writeVarInt(uint32_t v) {
            while (v >= 0x80) {
                m_buf.push_back(static_cast<uint8_t>(v | 0x80));
                v >>= 7;
            }
            m_buf.push_back(static_cast<uint8_t>(v));
        }

        void writeString(std::string const& s) {
            writeVarInt(static_cast<uint32_t>(s.size()));
            m_buf.insert(m_buf.end(), s.begin(), s.end());
        }

        void writeBool(bool v) {
            writeU8(v ? 1 : 0);
        }

        void writeBytes(const uint8_t* data, size_t len) {
            m_buf.insert(m_buf.end(), data, data + len);
        }

        // Write opcode as the first byte of a new message
        void writeOpcode(Opcode op) {
            writeU8(static_cast<uint8_t>(op));
        }

        std::vector<uint8_t> const& data() const { return m_buf; }
        std::vector<uint8_t>&& takeData() { return std::move(m_buf); }
        size_t size() const { return m_buf.size(); }

    private:
        std::vector<uint8_t> m_buf;
    };

    // ── Reader ────────────────────────────────────────────────
    // Reads from a binary message buffer. Little-endian byte order.

    class Reader {
    public:
        Reader(const uint8_t* data, size_t len)
            : m_data(data), m_len(len), m_pos(0) {}

        uint8_t readU8() {
            if (m_error || !checkRemaining(1)) return 0;
            return m_data[m_pos++];
        }

        uint16_t readU16() {
            if (m_error || !checkRemaining(2)) return 0;
            uint16_t v = static_cast<uint16_t>(m_data[m_pos])
                       | (static_cast<uint16_t>(m_data[m_pos + 1]) << 8);
            m_pos += 2;
            return v;
        }

        uint32_t readU32() {
            if (m_error || !checkRemaining(4)) return 0;
            uint32_t v = static_cast<uint32_t>(m_data[m_pos])
                       | (static_cast<uint32_t>(m_data[m_pos + 1]) << 8)
                       | (static_cast<uint32_t>(m_data[m_pos + 2]) << 16)
                       | (static_cast<uint32_t>(m_data[m_pos + 3]) << 24);
            m_pos += 4;
            return v;
        }

        int32_t readI32() {
            return static_cast<int32_t>(readU32());
        }

        float readF32() {
            if (m_error) return 0.0f;
            uint32_t bits = readU32();
            float v;
            std::memcpy(&v, &bits, sizeof(v));
            return v;
        }

        uint32_t readVarInt() {
            if (m_error) return 0;
            uint32_t v = 0;
            int shift = 0;
            while (true) {
                if (!checkRemaining(1)) return 0;
                uint8_t b = m_data[m_pos++];
                v |= static_cast<uint32_t>(b & 0x7F) << shift;
                if ((b & 0x80) == 0) break;
                shift += 7;
                if (shift >= 35) {
                    m_error = true;
                    return 0;
                }
            }
            return v;
        }

        std::string readString() {
            if (m_error) return "";
            uint32_t len = readVarInt();
            if (m_error || !checkRemaining(len)) return "";
            std::string s(reinterpret_cast<const char*>(m_data + m_pos), len);
            m_pos += len;
            return s;
        }

        bool readBool() {
            return readU8() != 0;
        }

        Opcode readOpcode() {
            return static_cast<Opcode>(readU8());
        }

        bool hasRemaining() const { return !m_error && m_pos < m_len; }
        size_t remaining() const { return m_error ? 0 : m_len - m_pos; }
        size_t position() const { return m_pos; }

        bool hasError() const { return m_error; }

        // Access raw remaining bytes (useful for chunked data)
        const uint8_t* currentPtr() const { return m_data + m_pos; }
        void skip(size_t bytes) {
            if (m_error || !checkRemaining(bytes)) return;
            m_pos += bytes;
        }

    private:
        bool checkRemaining(size_t need) {
            if (m_pos + need > m_len) {
                m_error = true;
                return false;
            }
            return true;
        }

        const uint8_t* m_data;
        size_t m_len;
        size_t m_pos;
        bool m_error = false;
    };

    // ── Serialization helpers ─────────────────────────────────
    // Each returns a complete binary message with opcode prefix.

    // ObjectData write/read (shared by PlaceObjects, UpdateObjects, SyncLevelEnd)
    void writeObjectData(Writer& w, ActionSerializer::ObjectData const& obj);
    ActionSerializer::ObjectData readObjectData(Reader& r);

    // MoveData write/read
    void writeMoveData(Writer& w, ActionSerializer::MoveData const& move);
    ActionSerializer::MoveData readMoveData(Reader& r);

    // TransformData write/read
    void writeTransformData(Writer& w, ActionSerializer::TransformData const& t);
    ActionSerializer::TransformData readTransformData(Reader& r);

    // LockData write/read
    void writeLockData(Writer& w, ActionSerializer::LockData const& lock);
    ActionSerializer::LockData readLockData(Reader& r);

    // LevelSettingsData write/read
    void writeSettingsData(Writer& w, ActionSerializer::LevelSettingsData const& s);
    ActionSerializer::LevelSettingsData readSettingsData(Reader& r);

    // ── Complete message serializers ──────────────────────────

    // Objects placed: [opcode][count:varint][ObjectData...]
    std::vector<uint8_t> serializePlaceObjects(
        std::vector<ActionSerializer::ObjectData> const& objects);

    // Objects deleted: [opcode][count:varint][uuid:string...]
    std::vector<uint8_t> serializeDeleteObjects(
        std::vector<std::string> const& uuids);

    // Objects moved: [opcode][count:varint][MoveData...]
    std::vector<uint8_t> serializeMoveObjects(
        std::vector<ActionSerializer::MoveData> const& moves);

    // Objects transformed: [opcode][count:varint][TransformData...]
    std::vector<uint8_t> serializeTransformObjects(
        std::vector<ActionSerializer::TransformData> const& transforms);

    // Objects reconciled: [opcode][count:varint][ReconcileData...]
    std::vector<uint8_t> serializeReconcileObjects(
        std::vector<ActionSerializer::ReconcileData> const& reconciles);

    // Objects updated: [opcode][count:varint][ObjectData...]
    std::vector<uint8_t> serializeUpdateObjects(
        std::vector<ActionSerializer::ObjectData> const& objects);

    // Lock/unlock objects: [opcode][locked:bool][count:varint][uuid:string...]
    std::vector<uint8_t> serializeLockObjects(
        std::vector<std::string> const& uuids, bool locked);

    // Cursor update (unreliable): [opcode][x:f32][y:f32][status:string]
    std::vector<uint8_t> serializeCursorUpdate(
        float x, float y, std::string const& status);

    // Batched moves (unreliable): [opcode][count:varint][MoveData...]
    std::vector<uint8_t> serializeMoveBatch(
        std::vector<ActionSerializer::MoveData> const& moves);

    // Update settings: [opcode][SettingsData]
    std::vector<uint8_t> serializeUpdateSettings(
        ActionSerializer::LevelSettingsData const& settings);

    // Sync level (chunked) - start message:
    // [opcode][totalChunks:varint][totalObjects:varint][SettingsData]
    std::vector<uint8_t> serializeSyncLevelStart(
        uint32_t totalChunks, uint32_t totalObjects,
        ActionSerializer::LevelSettingsData const& settings);

    // Sync level - chunk:
    // [opcode][chunkIndex:varint][dataLen:varint][compressedData:bytes]
    std::vector<uint8_t> serializeSyncLevelChunk(
        uint32_t chunkIndex, const uint8_t* data, size_t dataLen,
        std::vector<std::string> const& uuids);

    // Sync level - end:
    // [opcode][lockCount:varint][LockData...]
    std::vector<uint8_t> serializeSyncLevelEnd(
        std::vector<ActionSerializer::LockData> const& locks);

    // Session messages
    std::vector<uint8_t> serializePlayerJoined(
        int playerId, std::string const& name, int colorIndex);
    std::vector<uint8_t> serializePlayerLeft(int playerId);
    std::vector<uint8_t> serializeProtocolHello(uint32_t protocolVersion, uint64_t capabilities);

    std::vector<uint8_t> serializeReliableEnvelope(
        uint32_t sequence, std::vector<uint8_t> const& payload);
    std::vector<uint8_t> serializeReliableAck(uint32_t sequence);

    std::vector<uint8_t> serializeLevelDigest(uint32_t objectCount, std::string const& hash);

    struct LevelManifestEntry {
        std::string uuid;
        std::string hash;
    };
    std::vector<uint8_t> serializeLevelManifest(
        uint32_t scanId, uint32_t chunkIndex, uint32_t totalChunks,
        std::vector<LevelManifestEntry> const& entries);
    std::vector<uint8_t> serializeLevelRepairRequest(
        uint32_t scanId,
        std::vector<std::string> const& missing,
        std::vector<std::string> const& changed);
    std::vector<uint8_t> serializeFullResyncRequest();
    std::vector<uint8_t> serializeInitialSyncRequest();

    std::vector<uint8_t> serializeBulkPasteStart(
        uint32_t pasteId, uint32_t totalChunks, uint32_t totalObjects,
        bool withColor, bool noUndo, float anchorX, float anchorY);
    std::vector<uint8_t> serializeBulkPasteChunk(
        uint32_t pasteId, uint32_t chunkIndex, std::string const& data,
        std::vector<std::string> const& uuids);
    std::vector<uint8_t> serializeBulkPasteEnd(uint32_t pasteId);

    std::vector<uint8_t> serializeGlobalRevision(uint32_t revision, int authorPlayerId);
    std::vector<uint8_t> serializeSharedDigest(
        uint32_t revision, uint32_t objectCount, std::string const& hash);
    std::vector<uint8_t> serializeGlobalSnapshotRequest(uint32_t revision);
    std::vector<uint8_t> serializeKickPlayer(int targetPlayerId, std::string const& reason);
    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title);
    std::vector<uint8_t> serializeRoomSettingsChanged(
        uint32_t maxPlayers, bool allowBuild, bool allowDelete, bool allowWorkshop,
        bool allowLevelSettings, bool autoRepair, bool locked);

    std::vector<uint8_t> serializeError(std::string const& message);

    struct RoomInfoPlayer {
        int id;
        std::string name;
        int colorIndex;
    };
    struct RoomInfoMsg {
        std::vector<RoomInfoPlayer> players;
    };

    std::vector<uint8_t> serializeRoomInfo(std::vector<RoomInfoPlayer> const& players);
    RoomInfoMsg deserializeRoomInfo(Reader& r);

    // ── Deserialization ───────────────────────────────────────
    // These read from a Reader positioned AFTER the opcode byte.

    struct PlaceObjectsMsg {
        std::vector<ActionSerializer::ObjectData> objects;
    };
    PlaceObjectsMsg deserializePlaceObjects(Reader& r);

    struct DeleteObjectsMsg {
        std::vector<std::string> uuids;
    };
    DeleteObjectsMsg deserializeDeleteObjects(Reader& r);

    struct MoveObjectsMsg {
        std::vector<ActionSerializer::MoveData> moves;
    };
    MoveObjectsMsg deserializeMoveObjects(Reader& r);

    struct TransformObjectsMsg {
        std::vector<ActionSerializer::TransformData> transforms;
    };
    TransformObjectsMsg deserializeTransformObjects(Reader& r);

    struct ReconcileObjectsMsg {
        std::vector<ActionSerializer::ReconcileData> reconciles;
    };
    ReconcileObjectsMsg deserializeReconcileObjects(Reader& r);

    struct UpdateObjectsMsg {
        std::vector<ActionSerializer::ObjectData> objects;
    };
    UpdateObjectsMsg deserializeUpdateObjects(Reader& r);

    struct LockObjectsMsg {
        bool locked;
        std::vector<std::string> uuids;
    };
    LockObjectsMsg deserializeLockObjects(Reader& r);

    struct CursorUpdateMsg {
        float x, y;
        std::string status;
    };
    CursorUpdateMsg deserializeCursorUpdate(Reader& r);

    struct MoveBatchMsg {
        std::vector<ActionSerializer::MoveData> moves;
    };
    MoveBatchMsg deserializeMoveBatch(Reader& r);

    struct SyncLevelStartMsg {
        uint32_t totalChunks;
        uint32_t totalObjects;
        ActionSerializer::LevelSettingsData settings;
    };
    SyncLevelStartMsg deserializeSyncLevelStart(Reader& r);

    struct SyncLevelChunkMsg {
        uint32_t chunkIndex;
        std::vector<uint8_t> data;  // raw or compressed object data
        std::vector<std::string> uuids;
    };
    SyncLevelChunkMsg deserializeSyncLevelChunk(Reader& r);

    struct SyncLevelEndMsg {
        std::vector<ActionSerializer::LockData> locks;
    };
    SyncLevelEndMsg deserializeSyncLevelEnd(Reader& r);

    struct PlayerJoinedMsg {
        int playerId;
        std::string name;
        int colorIndex;
    };
    PlayerJoinedMsg deserializePlayerJoined(Reader& r);

    struct PlayerLeftMsg {
        int playerId;
    };
    PlayerLeftMsg deserializePlayerLeft(Reader& r);

    struct ProtocolHelloMsg {
        uint32_t protocolVersion = 0;
        uint64_t capabilities = 0;
    };
    ProtocolHelloMsg deserializeProtocolHello(Reader& r);

    struct ReliableEnvelopeMsg {
        uint32_t sequence = 0;
        std::vector<uint8_t> payload;
    };
    ReliableEnvelopeMsg deserializeReliableEnvelope(Reader& r);

    struct ReliableAckMsg {
        uint32_t sequence = 0;
    };
    ReliableAckMsg deserializeReliableAck(Reader& r);

    struct LevelDigestMsg {
        uint32_t objectCount = 0;
        std::string hash;
    };
    LevelDigestMsg deserializeLevelDigest(Reader& r);

    struct LevelManifestMsg {
        uint32_t scanId = 0;
        uint32_t chunkIndex = 0;
        uint32_t totalChunks = 0;
        std::vector<LevelManifestEntry> entries;
    };
    LevelManifestMsg deserializeLevelManifest(Reader& r);

    struct LevelRepairRequestMsg {
        uint32_t scanId = 0;
        std::vector<std::string> missing;
        std::vector<std::string> changed;
    };
    LevelRepairRequestMsg deserializeLevelRepairRequest(Reader& r);

    struct FullResyncRequestMsg {};
    FullResyncRequestMsg deserializeFullResyncRequest(Reader& r);

    struct BulkPasteStartMsg {
        uint32_t pasteId = 0;
        uint32_t totalChunks = 0;
        uint32_t totalObjects = 0;
        bool withColor = false;
        bool noUndo = false;
        float anchorX = 0.f;
        float anchorY = 0.f;
    };
    BulkPasteStartMsg deserializeBulkPasteStart(Reader& r);

    struct BulkPasteChunkMsg {
        uint32_t pasteId = 0;
        uint32_t chunkIndex = 0;
        std::string data;
        std::vector<std::string> uuids;
    };
    BulkPasteChunkMsg deserializeBulkPasteChunk(Reader& r);

    struct BulkPasteEndMsg {
        uint32_t pasteId = 0;
    };
    BulkPasteEndMsg deserializeBulkPasteEnd(Reader& r);

    struct GlobalRevisionMsg {
        uint32_t revision = 0;
        int authorPlayerId = 0;
    };
    GlobalRevisionMsg deserializeGlobalRevision(Reader& r);

    struct SharedDigestMsg {
        uint32_t revision = 0;
        uint32_t objectCount = 0;
        std::string hash;
    };
    SharedDigestMsg deserializeSharedDigest(Reader& r);

    struct GlobalSnapshotRequestMsg {
        uint32_t revision = 0;
    };
    GlobalSnapshotRequestMsg deserializeGlobalSnapshotRequest(Reader& r);

    struct KickPlayerMsg {
        int targetPlayerId = -1;
        std::string reason;
    };
    KickPlayerMsg deserializeKickPlayer(Reader& r);

    struct MusicChangedMsg {
        int songID = 0;
        int audioTrack = 0;
        std::string title;
    };
    MusicChangedMsg deserializeMusicChanged(Reader& r);

    struct RoomSettingsChangedMsg {
        uint32_t maxPlayers = 8;
        bool allowBuild = true;
        bool allowDelete = true;
        bool allowWorkshop = true;
        bool allowLevelSettings = true;
        bool autoRepair = true;
        bool locked = false;
    };
    RoomSettingsChangedMsg deserializeRoomSettingsChanged(Reader& r);

    struct ErrorMsg {
        std::string message;
    };
    ErrorMsg deserializeError(Reader& r);

    struct UpdateSettingsMsg {
        ActionSerializer::LevelSettingsData settings;
    };
    UpdateSettingsMsg deserializeUpdateSettings(Reader& r);

} // namespace mpedit::proto
