from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


# Add an explicit bootstrap control message. Initial sync must not depend on the
# timing of host-side onPlayerJoined callbacks.
proto_hpp_path = Path("src/BinaryProtocol.hpp")
proto_hpp = proto_hpp_path.read_text(encoding="utf-8")
proto_hpp = replace_once(
    proto_hpp,
    '''        FullResyncRequest  = 0x3B,\n\n        // Cursor (unreliable channel)''',
    '''        FullResyncRequest  = 0x3B,\n        InitialSyncRequest = 0x3C,\n\n        // Cursor (unreliable channel)''',
    "InitialSyncRequest opcode",
)
proto_hpp = replace_once(
    proto_hpp,
    '''    std::vector<uint8_t> serializeFullResyncRequest();\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    '''    std::vector<uint8_t> serializeFullResyncRequest();\n    std::vector<uint8_t> serializeInitialSyncRequest();\n\n    std::vector<uint8_t> serializeError(std::string const& message);''',
    "InitialSyncRequest serializer declaration",
)
proto_hpp_path.write_text(proto_hpp, encoding="utf-8")

proto_cpp_path = Path("src/BinaryProtocol.cpp")
proto_cpp = proto_cpp_path.read_text(encoding="utf-8")
proto_cpp = replace_once(
    proto_cpp,
    '''    std::vector<uint8_t> serializeFullResyncRequest() {\n        Writer w;\n        w.writeOpcode(Opcode::FullResyncRequest);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    '''    std::vector<uint8_t> serializeFullResyncRequest() {\n        Writer w;\n        w.writeOpcode(Opcode::FullResyncRequest);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeInitialSyncRequest() {\n        Writer w;\n        w.writeOpcode(Opcode::InitialSyncRequest);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeError(std::string const& message) {''',
    "InitialSyncRequest serializer",
)
proto_cpp_path.write_text(proto_cpp, encoding="utf-8")


# Host answers the explicit bootstrap request with the authoritative chunked
# sync. This handler exists before either side opens the editor scene.
remote_cpp_path = Path("src/RemoteActionHandler.cpp")
remote_cpp = remote_cpp_path.read_text(encoding="utf-8")
remote_cpp = replace_once(
    remote_cpp,
    '''        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {''',
    '''        net.on(proto::Opcode::InitialSyncRequest, [this](int playerId, proto::Reader&) {\n            if (SessionManager::get().getRole() != SessionManager::Role::Host) return;\n            log::info("RemoteActionHandler: InitialSyncRequest from player {}", playerId);\n            sendFullLevelSyncTo(playerId);\n        });\n\n        net.on(proto::Opcode::SyncLevelStart, [this](int playerId, proto::Reader& reader) {''',
    "InitialSyncRequest host handler",
)
remote_cpp_path.write_text(remote_cpp, encoding="utf-8")


# Once the client has completed ProtocolHello v2, explicitly request the host
# level. Keep this as immediate control traffic; it must not wait on editor FIFO.
p2p_cpp_path = Path("src/P2PManager.cpp")
p2p_cpp = p2p_cpp_path.read_text(encoding="utf-8")
p2p_cpp = replace_once(
    p2p_cpp,
    '''        if (m_role == Role::Client && pid == 0) {\n            m_state.store(State::Connected);\n            m_reconnectAttempts = 0;\n            m_reconnectScheduled.store(false);\n            stopSignalPolling();\n        }''',
    '''        if (m_role == Role::Client && pid == 0) {\n            m_state.store(State::Connected);\n            m_reconnectAttempts = 0;\n            m_reconnectScheduled.store(false);\n            stopSignalPolling();\n\n            auto syncRequest = proto::serializeInitialSyncRequest();\n            sendTo(0, syncRequest, ChannelType::Reliable);\n            log::info("P2PManager: requested authoritative initial sync from host");\n        }''',
    "client initial sync request after handshake",
)
p2p_cpp_path.write_text(p2p_cpp, encoding="utf-8")


# Remove push-based host sync on PlayerJoined. The request path above is the one
# source of truth, preventing duplicate overlapping SyncLevel streams.
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
start = hooks.find('        SessionManager::get().onPlayerJoined([this](PlayerInfo const& info) {')
if start == -1:
    raise SystemExit("initial sync callback: onPlayerJoined block start not found; refusing to patch")
brace = hooks.find('{', start)
if brace == -1:
    raise SystemExit("initial sync callback: opening brace not found; refusing to patch")
depth = 0
end = -1
for i in range(brace, len(hooks)):
    if hooks[i] == '{':
        depth += 1
    elif hooks[i] == '}':
        depth -= 1
        if depth == 0:
            semi = hooks.find(';', i)
            if semi == -1:
                raise SystemExit("initial sync callback: terminator not found; refusing to patch")
            end = semi + 1
            break
if end == -1:
    raise SystemExit("initial sync callback: block end not found; refusing to patch")
replacement = '''        // Initial level transfer is request-driven after ProtocolHello.\n        // This avoids a first-join race between peer callbacks and bootstrap sync.\n'''
hooks = hooks[:start] + replacement + hooks[end:]
hooks_path.write_text(hooks, encoding="utf-8")

print("Patched first-join bootstrap to explicit InitialSyncRequest -> authoritative SyncLevel")
