from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


# P2P state for coalesced HTTP-relay cursor delivery.
path = Path("src/P2PManager.hpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''            bool httpRelay = false;\n            bool httpRelayPostInFlight = false;\n            std::vector<PendingCandidate> pendingCandidates;''',
    '''            bool httpRelay = false;\n            bool httpRelayPostInFlight = false;\n            // CursorUpdate is latest-state data. Over HTTP relay, keep at most\n            // one POST in flight and one replacement packet so 30 Hz cursor\n            // traffic cannot build an unbounded request/backlog queue.\n            bool httpRelayCursorPostInFlight = false;\n            std::vector<uint8_t> pendingHttpRelayCursor;\n            std::vector<PendingCandidate> pendingCandidates;''',
    "PeerInfo relay cursor state",
)
text = replace_once(
    text,
    '''        void sendHttpRelayPacket(\n            int playerId,\n            std::vector<uint8_t> const& data,\n            ChannelType channel,\n            uint32_t trackedSequence = 0\n        );\n        void handleHttpRelayMessages(matjson::Value const& messages);''',
    '''        void sendHttpRelayPacket(\n            int playerId,\n            std::vector<uint8_t> const& data,\n            ChannelType channel,\n            uint32_t trackedSequence = 0\n        );\n        void sendHttpRelayCursorPacket(int playerId, std::vector<uint8_t> const& data);\n        void handleHttpRelayMessages(matjson::Value const& messages);''',
    "relay cursor helper declaration",
)
path.write_text(text, encoding="utf-8")


path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")

# Do not fill the pre-handshake queue with 30 Hz CursorUpdate / MoveBatch state.
# The authoritative snapshot follows the handshake, and fresh transient state is
# sent immediately afterwards.
text = replace_once(
    text,
    '''                if (!protocolVerified) {\n                    if (it->second.preHandshakeMessages.size() < kMaxPreHandshakeMessages) {\n                        it->second.preHandshakeMessages.emplace_back(data, data + len);\n                        log::debug(\n                            "P2PManager: buffered opcode {} from player {} until protocol handshake",\n                            static_cast<int>(opcode),\n                            fromPlayerId\n                        );\n                    } else {\n                        log::warn(\n                            "P2PManager: pre-handshake queue full for player {}; dropping opcode {}",\n                            fromPlayerId,\n                            static_cast<int>(opcode)\n                        );\n                    }\n                }''',
    '''                if (!protocolVerified) {\n                    const bool transientUnreliable =\n                        opcode == static_cast<uint8_t>(proto::Opcode::CursorUpdate) ||\n                        opcode == static_cast<uint8_t>(proto::Opcode::MoveBatch);\n                    if (!transientUnreliable) {\n                        if (it->second.preHandshakeMessages.size() < kMaxPreHandshakeMessages) {\n                            it->second.preHandshakeMessages.emplace_back(data, data + len);\n                            log::debug(\n                                "P2PManager: buffered opcode {} from player {} until protocol handshake",\n                                static_cast<int>(opcode),\n                                fromPlayerId\n                            );\n                        } else {\n                            log::warn(\n                                "P2PManager: pre-handshake queue full for player {}; dropping opcode {}",\n                                fromPlayerId,\n                                static_cast<int>(opcode)\n                            );\n                        }\n                    }\n                }''',
    "drop transient pre-handshake traffic",
)

# Coalesce cursor state on HTTP relay. Direct WebRTC remains unchanged at 30 Hz.
text = replace_once(
    text,
    '''        if (peer.httpRelay) {\n            if (data.size() > 48 * 1024) {\n                log::warn(\n                    "P2PManager: dropping oversized HTTP relay message (opcode={}, {} bytes)",\n                    data.empty() ? -1 : static_cast<int>(data[0]), data.size()\n                );\n                return;\n            }\n            sendHttpRelayPacket(playerId, data, channel);\n            return;\n        }''',
    '''        if (peer.httpRelay) {\n            if (data.size() > 48 * 1024) {\n                log::warn(\n                    "P2PManager: dropping oversized HTTP relay message (opcode={}, {} bytes)",\n                    data.empty() ? -1 : static_cast<int>(data[0]), data.size()\n                );\n                return;\n            }\n\n            if (\n                channel == ChannelType::Unreliable &&\n                !data.empty() &&\n                data[0] == static_cast<uint8_t>(proto::Opcode::CursorUpdate)\n            ) {\n                // CursorUpdate describes current state, not a delta. If the relay\n                // POST is still in flight, replace the pending packet with the\n                // newest cursor position instead of starting another HTTP request.\n                if (peer.httpRelayCursorPostInFlight) {\n                    peer.pendingHttpRelayCursor = data;\n                    return;\n                }\n                peer.httpRelayCursorPostInFlight = true;\n                sendHttpRelayCursorPacket(playerId, data);\n                return;\n            }\n\n            sendHttpRelayPacket(playerId, data, channel);\n            return;\n        }''',
    "HTTP relay cursor coalescing dispatch",
)

# Insert the dedicated cursor sender immediately before relay receive handling.
marker = '''    void P2PManager::handleHttpRelayMessages(matjson::Value const& messages) {'''
if text.count(marker) != 1:
    raise SystemExit("relay receive marker not unique")
helper = r'''    void P2PManager::sendHttpRelayCursorPacket(
        int playerId,
        std::vector<uint8_t> const& data
    ) {
        if (data.empty() || m_signalingToken.empty() || getRoomCode().empty()) return;

        auto body = matjson::Value();
        body["targetPlayerId"] = playerId;
        body["channel"] = "unreliable";
        body["payload"] = bytesToHex(data);

        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        req.header("Authorization", "Bearer " + m_signalingToken);
        req.bodyJSON(body);
        auto url = getSignalingUrl() + "/rooms/" + getRoomCode() + "/relay";

        async::spawn(
            req.post(url),
            [this, playerId](web::WebResponse res) {
                std::vector<uint8_t> nextCursor;
                {
                    std::lock_guard lock(m_peersMutex);
                    auto it = m_peers.find(playerId);
                    if (it != m_peers.end()) {
                        auto& peer = it->second;
                        if (!peer.pendingHttpRelayCursor.empty()) {
                            nextCursor = std::move(peer.pendingHttpRelayCursor);
                            peer.pendingHttpRelayCursor.clear();
                            // Keep httpRelayCursorPostInFlight=true while the
                            // replacement packet is sent below.
                        } else {
                            peer.httpRelayCursorPostInFlight = false;
                        }
                    }
                }

                if (!res.ok()) {
                    log::debug(
                        "P2PManager: HTTP relay cursor POST to player {} failed code={} error={}",
                        playerId, res.code(), res.errorMessage()
                    );
                }

                if (!nextCursor.empty()) {
                    sendHttpRelayCursorPacket(playerId, nextCursor);
                }
            }
        );
    }

'''
text = text.replace(marker, helper + marker, 1)
path.write_text(text, encoding="utf-8")


# Desired discovery UI: Public Rooms and Private Room stacked vertically, with
# the readable sizing from the user's UI-polish branch. No networking logic here.
path = Path("src/ui/MultiplayerPopup.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'serverLabel->setScale(0.27f);', 'serverLabel->setScale(0.62f);', "server label scale")
text = replace_once(
    text,
    '''        } else {\n            auto* browseSprite = ButtonSprite::create(\n                "Public Rooms", 135, true, "bigFont.fnt", "GJ_button_01.png", 30.f, 0.58f\n            );\n            auto* browseBtn = CCMenuItemSpriteExtra::create(\n                browseSprite, this, menu_selector(MultiplayerPopup::onBrowsePublic)\n            );\n            browseBtn->setPosition({center.width - 72.f, center.height + 10.f});\n            browseBtn->setID("public-rooms-button"_spr);\n            m_connectMenu->addChild(browseBtn);\n\n            auto* privateSprite = ButtonSprite::create(\n                "Private Room", 135, true, "bigFont.fnt", "GJ_button_05.png", 30.f, 0.58f\n            );\n            auto* privateBtn = CCMenuItemSpriteExtra::create(\n                privateSprite, this, menu_selector(MultiplayerPopup::onPrivateRoom)\n            );\n            privateBtn->setPosition({center.width + 72.f, center.height + 10.f});\n            privateBtn->setID("private-room-button"_spr);\n            m_connectMenu->addChild(privateBtn);\n\n            auto* hint = CCLabelBMFont::create(\n                "Public rooms are discovered from the Signaling Server URL in mod settings",\n                "chatFont.fnt"\n            );\n            hint->setScale(0.29f);\n            hint->setPosition({center.width, center.height - 38.f});\n            hint->setColor({185, 185, 185});\n            m_contentNode->addChild(hint);\n        }''',
    '''        } else {\n            constexpr int kDiscoveryButtonWidth = 176;\n            auto* browseSprite = ButtonSprite::create(\n                "Public Rooms", kDiscoveryButtonWidth, true, "bigFont.fnt", "GJ_button_01.png", 30.f, 0.58f\n            );\n            auto* browseBtn = CCMenuItemSpriteExtra::create(\n                browseSprite, this, menu_selector(MultiplayerPopup::onBrowsePublic)\n            );\n            browseBtn->setPosition({center.width, center.height + 18.f});\n            browseBtn->setID("public-rooms-button"_spr);\n            m_connectMenu->addChild(browseBtn);\n\n            auto* privateSprite = ButtonSprite::create(\n                "Private Room", kDiscoveryButtonWidth, true, "bigFont.fnt", "GJ_button_05.png", 30.f, 0.58f\n            );\n            auto* privateBtn = CCMenuItemSpriteExtra::create(\n                privateSprite, this, menu_selector(MultiplayerPopup::onPrivateRoom)\n            );\n            privateBtn->setPosition({center.width, center.height - 31.f});\n            privateBtn->setID("private-room-button"_spr);\n            m_connectMenu->addChild(privateBtn);\n\n            auto* hint = CCLabelBMFont::create(\n                "Rooms are loaded from the Signaling Server URL\\nselected in mod settings",\n                "chatFont.fnt"\n            );\n            hint->setScale(0.58f);\n            hint->setPosition({center.width, center.height - 78.f});\n            hint->setColor({185, 185, 185});\n            m_contentNode->addChild(hint);\n        }''',
    "stacked discovery buttons",
)
text = replace_once(
    text,
    'm_statusLabel->setPosition({center.width, center.height - 88.f});',
    'm_statusLabel->setPosition({center.width, 24.f});',
    "connect status placement",
)
path.write_text(text, encoding="utf-8")


# Keep current 4-second auto-refresh implementation; apply only visual polish to
# the create-room/browser popup.
path = Path("src/ui/RoomDiscoveryPopups.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'makeLabel("Player limit", 0.4f, {center.width - 105.f, center.height - 10.f}, m_mainLayer);',
    'makeLabel("Player limit", 0.52f, {center.width - 102.f, center.height - 10.f}, m_mainLayer);',
    "player limit label",
)
text = replace_once(
    text,
    'm_visibilitySprite = ButtonSprite::create("Public", 105, true, "bigFont.fnt", "GJ_button_04.png", 28.f, 0.5f);',
    'm_visibilitySprite = ButtonSprite::create("Public", 88, true, "bigFont.fnt", "GJ_button_04.png", 24.f, 0.46f);',
    "visibility button sizing",
)
text = replace_once(
    text,
    '''    auto* hint = makeLabel(\n        "Private rooms are hidden from the public browser",\n        0.3f,\n        {center.width, 68.f},\n        m_mainLayer\n    );''',
    '''    auto* hint = makeLabel(\n        "Private rooms are hidden\\nfrom the public browser",\n        0.56f,\n        {center.width, 70.f},\n        m_mainLayer\n    );''',
    "private room hint",
)
text = replace_once(
    text,
    'auto* serverLabel = makeLabel(P2PManager::getSignalingUrl().c_str(), 0.25f, {center.width, 255.f}, m_body);',
    'auto* serverLabel = makeLabel(P2PManager::getSignalingUrl().c_str(), 0.48f, {center.width - 32.f, 255.f}, m_body);',
    "browser server label",
)
text = replace_once(
    text,
    'auto* detailsLabel = makeLabel(details.c_str(), 0.25f, {48.f, y - 8.f}, m_body);',
    'auto* detailsLabel = makeLabel(details.c_str(), 0.34f, {48.f, y - 8.f}, m_body);',
    "browser details scale",
)
text = replace_once(
    text,
    'makeLabel(pageText.c_str(), 0.3f, {center.width, 32.f}, m_body);',
    'makeLabel(pageText.c_str(), 0.42f, {center.width, 32.f}, m_body);',
    "browser page scale",
)
path.write_text(text, encoding="utf-8")


# Guardrails: ensure current ghost-room, password and sync fixes were preserved.
p2p = Path("src/P2PManager.cpp").read_text(encoding="utf-8")
hpp = Path("src/P2PManager.hpp").read_text(encoding="utf-8")
popup = Path("src/ui/MultiplayerPopup.cpp").read_text(encoding="utf-8")
discovery = Path("src/ui/RoomDiscoveryPopups.cpp").read_text(encoding="utf-8")
server = Path("server/signaling/server.ts").read_text(encoding="utf-8")
hooks = Path("src/EditorHooks.cpp").read_text(encoding="utf-8")
remote = Path("src/RemoteActionHandler.cpp").read_text(encoding="utf-8")

checks = {
    "cursor coalescing": "httpRelayCursorPostInFlight" in p2p and "sendHttpRelayCursorPacket" in hpp,
    "stacked public/private": "browseBtn->setPosition({center.width, center.height + 18.f});" in popup and "privateBtn->setPosition({center.width, center.height - 31.f});" in popup,
    "room auto refresh": "fetchRooms(false);" in discovery and "m_autoRefreshTimer" in discovery,
    "password join": "Invalid room password" in p2p and "Password Required" in discovery,
    "guest leave delete": "m_role != Role::None && !m_roomCode.empty() && !m_signalingToken.empty()" in p2p,
    "server stale room filter": "HOST_DIRECTORY_STALE_MS = 45_000" in server,
    "ordered snapshot": "serializeSyncLevelStart" in hooks and "serializeSyncLevelEnd" in hooks,
    "position aware mapping": "candidatesByPosition" in remote,
}
for name, ok in checks.items():
    if not ok:
        raise SystemExit(f"guardrail failed: {name}")

print("complete v0.5.3 fix patch applied")
