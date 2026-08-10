from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# Explicit standard-library dependency for std::pair in the public integrity API.
hpp_path = Path("src/RemoteActionHandler.hpp")
hpp = hpp_path.read_text(encoding="utf-8")
if "#include <utility>" not in hpp:
    hpp = hpp.replace("#include <vector>\n", "#include <vector>\n#include <utility>\n", 1)
hpp_path.write_text(hpp, encoding="utf-8")


# Normalize local-only Start Position keys before hashing so integrity checks do
# not report a mismatch for state that MultiplayerEdit intentionally keeps local.
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")
remote = replace_once(
    remote,
    '''            std::string save = obj->getSaveString(editor);\n            entries.push_back({uuid, stableIntegrityHash(save)});''',
    '''            std::string save = obj->getSaveString(editor);\n            if (obj->m_objectID == 31) {\n                auto ordered = ActionSerializer::parseSaveStringOrdered(save);\n                std::vector<std::pair<std::string, std::string>> normalized;\n                normalized.reserve(ordered.size());\n                for (auto const& pair : ordered) {\n                    if (pair.first == "kA21" || pair.first == "kA9" || pair.first == "93") continue;\n                    normalized.push_back(pair);\n                }\n                save = ActionSerializer::buildSaveStringOrdered(normalized);\n            }\n            entries.push_back({uuid, stableIntegrityHash(save)});''',
    "normalize StartPos integrity hash",
)
remote_path.write_text(remote, encoding="utf-8")


p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")

# Host/client integrity control messages are point-to-point protocol traffic and
# must not be relayed to unrelated peers by the star-topology relay path.
p2p = replace_once(
    p2p,
    '''        if (m_role == Role::Host) {\n            uint8_t opcode = data[0];\n            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;\n            ChannelType ch = ChannelType::Reliable;''',
    '''        if (m_role == Role::Host) {\n            uint8_t opcode = data[0];\n            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;\n            if (\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelDigest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelManifest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::LevelRepairRequest) ||\n                opcode == static_cast<uint8_t>(proto::Opcode::FullResyncRequest)\n            ) return;\n            ChannelType ch = ChannelType::Reliable;''',
    "do not relay integrity control packets",
)

# A successful HTTP response without a usable player ID is retryable during an
# active reconnect instead of becoming a fatal session error.
p2p = replace_once(
    p2p,
    '''                    if (m_localPlayerId < 0) {\n                        std::vector<ErrorCb> callbacks;''',
    '''                    if (m_localPlayerId < 0) {\n                        if (m_state.load() == State::Reconnecting) {\n                            log::warn("P2PManager: reconnect response had no playerId; retrying");\n                            scheduleClientReconnect();\n                            return;\n                        }\n                        std::vector<ErrorCb> callbacks;''',
    "retry reconnect without player ID",
)

# Reset reconnect bookkeeping on an intentional session exit.
p2p = replace_once(
    p2p,
    '''        m_state.store(State::Disconnected);\n        m_nextPlayerId = 1;\n        m_signalingRoomId.clear();''',
    '''        m_state.store(State::Disconnected);\n        m_nextPlayerId = 1;\n        m_reconnectAttempts = 0;\n        m_reconnectScheduled.store(false);\n        m_recentDisconnectedNames.clear();\n        m_signalingRoomId.clear();''',
    "clear reconnect bookkeeping",
)

p2p_path.write_text(p2p, encoding="utf-8")
print("Hardened ACK/integrity/reconnect layer")
