from pathlib import Path

path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

func_sig = "    void P2PManager::onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len) {"
func_start = text.find(func_sig)
if func_start == -1:
    raise SystemExit("v4 relay bridge: onPeerMessage not found")

func_brace = text.find("{", func_start)
depth = 0
func_end = -1
for i in range(func_brace, len(text)):
    if text[i] == "{":
        depth += 1
    elif text[i] == "}":
        depth -= 1
        if depth == 0:
            func_end = i + 1
            break
if func_end == -1:
    raise SystemExit("v4 relay bridge: onPeerMessage end not found")

segment = text[func_start:func_end]
marker = "        if (m_role == Role::Host) {"
rel = segment.rfind(marker)
if rel == -1:
    raise SystemExit("v4 relay bridge: host relay block not found")
block_start = func_start + rel
open_brace = text.find("{", block_start)
depth = 0
block_end = -1
for i in range(open_brace, func_end):
    if text[i] == "{":
        depth += 1
    elif text[i] == "}":
        depth -= 1
        if depth == 0:
            block_end = i + 1
            break
if block_end == -1:
    raise SystemExit("v4 relay bridge: host relay block end not found")

normalized = '''        if (m_role == Role::Host) {
            uint8_t opcode = data[0];
            if (opcode == static_cast<uint8_t>(proto::Opcode::ProtocolHello)) return;
            if (
                opcode == static_cast<uint8_t>(proto::Opcode::LevelDigest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::LevelManifest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::LevelRepairRequest) ||
                opcode == static_cast<uint8_t>(proto::Opcode::FullResyncRequest)
            ) return;
            ChannelType ch = ChannelType::Reliable;
            if (opcode == static_cast<uint8_t>(proto::Opcode::CursorUpdate) ||
                opcode == static_cast<uint8_t>(proto::Opcode::MoveBatch)) {
                ch = ChannelType::Unreliable;
            }
            relayMessage(fromPlayerId, data, len, ch);
        }'''

text = text[:block_start] + normalized + text[block_end:]
path.write_text(text, encoding="utf-8")
print("Normalized onPeerMessage host relay block for Global Shared State v4")
