from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing pattern: {label}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"regex pattern {label}: expected 1 match, got {count}")
    return new_text


# ---------------------------------------------------------------------------
# Room discovery popup header: make Geode/ButtonSprite symbols explicit.
# ---------------------------------------------------------------------------
header = Path("src/ui/RoomDiscoveryPopups.hpp")
text = header.read_text(encoding="utf-8")
text = replace_once(
    text,
    '#include <Geode/ui/Popup.hpp>\n',
    '#include <Geode/Geode.hpp>\n#include <Geode/ui/Popup.hpp>\n',
    "room discovery Geode include",
)
header.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# P2PManager API + pending creation/join metadata.
# ---------------------------------------------------------------------------
path = Path("src/P2PManager.hpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        void hostSession(std::string const& playerName);\n        void joinSession(std::string const& roomCode, std::string const& playerName);',
    '''        void hostSession(
            std::string const& playerName,
            std::string const& roomName = "",
            std::string const& description = "",
            int playerLimit = 8,
            bool isPrivate = false,
            std::string const& password = ""
        );
        void joinSession(
            std::string const& roomCode,
            std::string const& playerName,
            std::string const& password = ""
        );''',
    "P2P public session signatures",
)
text = replace_once(
    text,
    '        std::string m_localPlayerName;\n        std::string m_error;',
    '''        std::string m_localPlayerName;
        std::string m_error;
        std::string m_pendingRoomName;
        std::string m_pendingRoomDescription;
        std::string m_pendingRoomPassword;
        std::string m_pendingJoinPassword;
        int m_pendingPlayerLimit = 8;
        bool m_pendingRoomPrivate = false;''',
    "P2P pending room metadata",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# P2PManager implementation.
# ---------------------------------------------------------------------------
path = Path("src/P2PManager.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    void P2PManager::hostSession(std::string const& playerName) {\n        auto selectedNetwork = net::NetworkConfig::load();',
    '''    void P2PManager::hostSession(
        std::string const& playerName,
        std::string const& roomName,
        std::string const& description,
        int playerLimit,
        bool isPrivate,
        std::string const& password
    ) {
        auto selectedNetwork = net::NetworkConfig::load();''',
    "P2P host signature",
)
text = replace_once(
    text,
    '''        m_state.store(State::Connecting);
        m_nextPlayerId = 1;
        {
            std::lock_guard lock(m_roomSettingsMutex);
            m_roomSettings = RoomSettings{};
        }''',
    '''        m_pendingRoomName = roomName.empty() ? (playerName + "'s Room") : roomName;
        m_pendingRoomDescription = description;
        m_pendingRoomPassword = password;
        m_pendingPlayerLimit = std::clamp(playerLimit, 2, 16);
        m_pendingRoomPrivate = isPrivate;

        m_state.store(State::Connecting);
        m_nextPlayerId = 1;
        {
            std::lock_guard lock(m_roomSettingsMutex);
            m_roomSettings = RoomSettings{};
            m_roomSettings.maxPlayers = static_cast<uint32_t>(m_pendingPlayerLimit);
        }''',
    "P2P host metadata state",
)
text = replace_once(
    text,
    '''        body["transportMode"] = net::NetworkConfig::load().transportModeName();
        req.bodyJSON(body);''',
    '''        body["transportMode"] = net::NetworkConfig::load().transportModeName();
        body["roomName"] = m_pendingRoomName;
        body["description"] = m_pendingRoomDescription;
        body["playerLimit"] = m_pendingPlayerLimit;
        body["isPrivate"] = m_pendingRoomPrivate;
        body["password"] = m_pendingRoomPassword;
        req.bodyJSON(body);''',
    "P2P create room JSON metadata",
)
text = replace_once(
    text,
    '    void P2PManager::joinSession(std::string const& roomCode, std::string const& playerName) {\n        auto selectedNetwork = net::NetworkConfig::load();',
    '''    void P2PManager::joinSession(
        std::string const& roomCode,
        std::string const& playerName,
        std::string const& password
    ) {
        auto selectedNetwork = net::NetworkConfig::load();''',
    "P2P join signature",
)
text = replace_once(
    text,
    '''        m_state.store(State::Connecting);
        m_globalRevision.store(0);''',
    '''        m_pendingJoinPassword = password;
        m_state.store(State::Connecting);
        m_globalRevision.store(0);''',
    "P2P join password state",
)
# The second transportMode occurrence belongs to join JSON.
join_marker = '        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);\n        body["transportMode"] = net::NetworkConfig::load().transportModeName();\n        req.bodyJSON(body);'
text = replace_once(
    text,
    join_marker,
    '''        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);
        body["transportMode"] = net::NetworkConfig::load().transportModeName();
        body["password"] = m_pendingJoinPassword;
        req.bodyJSON(body);''',
    "P2P join password JSON",
)
text = replace_once(
    text,
    '''        m_signalingApi = 1;
        m_hostMigrationAvailable.store(false);''',
    '''        m_signalingApi = 1;
        m_pendingRoomName.clear();
        m_pendingRoomDescription.clear();
        m_pendingRoomPassword.clear();
        m_pendingJoinPassword.clear();
        m_pendingPlayerLimit = 8;
        m_pendingRoomPrivate = false;
        m_hostMigrationAvailable.store(false);''',
    "P2P pending metadata cleanup",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# SessionManager forwards room metadata/password without touching sync handlers.
# ---------------------------------------------------------------------------
path = Path("src/SessionManager.hpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''        void hostSession(std::string const& playerName);
        void joinSession(std::string const& roomCode, std::string const& playerName);''',
    '''        void hostSession(
            std::string const& playerName,
            std::string const& roomName = "",
            std::string const& description = "",
            int playerLimit = 8,
            bool isPrivate = false,
            std::string const& password = ""
        );
        void joinSession(
            std::string const& roomCode,
            std::string const& playerName,
            std::string const& password = ""
        );''',
    "SessionManager signatures",
)
path.write_text(text, encoding="utf-8")

path = Path("src/SessionManager.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    void SessionManager::hostSession(std::string const& playerName) {',
    '''    void SessionManager::hostSession(
        std::string const& playerName,
        std::string const& roomName,
        std::string const& description,
        int playerLimit,
        bool isPrivate,
        std::string const& password
    ) {''',
    "SessionManager host signature",
)
text = replace_once(
    text,
    '        P2PManager::get().hostSession(playerName);',
    '        P2PManager::get().hostSession(playerName, roomName, description, playerLimit, isPrivate, password);',
    "SessionManager host forwarding",
)
text = replace_once(
    text,
    '    void SessionManager::joinSession(std::string const& roomCode, std::string const& playerName) {',
    '''    void SessionManager::joinSession(
        std::string const& roomCode,
        std::string const& playerName,
        std::string const& password
    ) {''',
    "SessionManager join signature",
)
text = replace_once(
    text,
    '        P2PManager::get().joinSession(roomCode, playerName);',
    '        P2PManager::get().joinSession(roomCode, playerName, password);',
    "SessionManager join forwarding",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Multiplayer popup: original-style room menu, no Patreon.
# ---------------------------------------------------------------------------
path = Path("src/ui/MultiplayerPopup.hpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        void onHost(cocos2d::CCObject*);\n        void onJoin(cocos2d::CCObject*);',
    '''        void onHost(cocos2d::CCObject*);
        void onJoin(cocos2d::CCObject*);
        void onBrowsePublic(cocos2d::CCObject*);
        void onPrivateRoom(cocos2d::CCObject*);''',
    "MultiplayerPopup browser callbacks",
)
text = text.replace('        void onPatreon(cocos2d::CCObject*);\n', '')
text = replace_once(
    text,
    '''        static inline MultiplayerPopup* s_instance = nullptr;
        static MultiplayerPopup* create();''',
    '''        static inline MultiplayerPopup* s_instance = nullptr;
        static MultiplayerPopup* create();
        void beginHost(
            std::string const& roomName,
            std::string const& description,
            int playerLimit,
            bool isPrivate,
            std::string const& password
        );
        void beginJoin(std::string const& roomCode, std::string const& password);''',
    "MultiplayerPopup public launch helpers",
)
path.write_text(text, encoding="utf-8")

path = Path("src/ui/MultiplayerPopup.cpp")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '#include "RoomSettingsPopup.hpp"\n',
    '#include "RoomSettingsPopup.hpp"\n#include "RoomDiscoveryPopups.hpp"\n',
    "MultiplayerPopup discovery include",
)

new_connect = r'''    void MultiplayerPopup::createConnectView() {
        auto center = m_mainLayer->getContentSize() / 2.f;
        bool inEditor = LevelEditorLayer::get() != nullptr;

        std::string accountName = GJAccountManager::sharedState()->m_username;
        if (accountName.empty()) accountName = "Player";
        Mod::get()->setSettingValue<std::string>("player-name", accountName);

        m_connectMenu = CCMenu::create();
        m_connectMenu->setPosition({0.f, 0.f});
        m_connectMenu->setID("connect-menu"_spr);

        auto* serverLabel = CCLabelBMFont::create(P2PManager::getSignalingUrl().c_str(), "chatFont.fnt");
        serverLabel->setScale(0.27f);
        serverLabel->setPosition({center.width, center.height + 78.f});
        serverLabel->setColor({165, 165, 165});
        m_contentNode->addChild(serverLabel);

        if (inEditor) {
            auto* hint = CCLabelBMFont::create("Host this level on the selected signaling server", "chatFont.fnt");
            hint->setScale(0.34f);
            hint->setPosition({center.width, center.height + 35.f});
            m_contentNode->addChild(hint);

            auto* createSprite = ButtonSprite::create(
                "Create Room", 140, true, "bigFont.fnt", "GJ_button_02.png", 30.f, 0.62f
            );
            auto* createBtn = CCMenuItemSpriteExtra::create(
                createSprite, this, menu_selector(MultiplayerPopup::onHost)
            );
            createBtn->setPosition({center.width, center.height - 12.f});
            createBtn->setID("create-room-button"_spr);
            m_connectMenu->addChild(createBtn);
        } else {
            auto* browseSprite = ButtonSprite::create(
                "Public Rooms", 135, true, "bigFont.fnt", "GJ_button_01.png", 30.f, 0.58f
            );
            auto* browseBtn = CCMenuItemSpriteExtra::create(
                browseSprite, this, menu_selector(MultiplayerPopup::onBrowsePublic)
            );
            browseBtn->setPosition({center.width - 72.f, center.height + 10.f});
            browseBtn->setID("public-rooms-button"_spr);
            m_connectMenu->addChild(browseBtn);

            auto* privateSprite = ButtonSprite::create(
                "Private Room", 135, true, "bigFont.fnt", "GJ_button_05.png", 30.f, 0.58f
            );
            auto* privateBtn = CCMenuItemSpriteExtra::create(
                privateSprite, this, menu_selector(MultiplayerPopup::onPrivateRoom)
            );
            privateBtn->setPosition({center.width + 72.f, center.height + 10.f});
            privateBtn->setID("private-room-button"_spr);
            m_connectMenu->addChild(privateBtn);

            auto* hint = CCLabelBMFont::create(
                "Public rooms are discovered from the Signaling Server URL in mod settings",
                "chatFont.fnt"
            );
            hint->setScale(0.29f);
            hint->setPosition({center.width, center.height - 38.f});
            hint->setColor({185, 185, 185});
            m_contentNode->addChild(hint);
        }

        m_contentNode->addChild(m_connectMenu);

        m_statusLabel = CCLabelBMFont::create("", "chatFont.fnt");
        m_statusLabel->setScale(0.55f);
        m_statusLabel->setPosition({center.width, center.height - 88.f});
        m_statusLabel->setID("status-label"_spr);
        m_statusLabel->setColor({200, 200, 200});
        m_contentNode->addChild(m_statusLabel);
    }

'''
text = regex_once(
    text,
    r'    void MultiplayerPopup::createConnectView\(\) \{.*?\n    void MultiplayerPopup::createSessionView\(\) \{',
    new_connect + '    void MultiplayerPopup::createSessionView() {',
    "MultiplayerPopup connect view",
)

new_host_join = r'''    void MultiplayerPopup::onHost(CCObject*) {
        if (!LevelEditorLayer::get()) return;
        if (auto* popup = CreateRoomPopup::create(this)) popup->show();
    }

    void MultiplayerPopup::onBrowsePublic(CCObject*) {
        if (auto* popup = RoomBrowserPopup::create(this)) popup->show();
    }

    void MultiplayerPopup::onPrivateRoom(CCObject*) {
        if (auto* popup = PrivateRoomPopup::create(this)) popup->show();
    }

    void MultiplayerPopup::beginHost(
        std::string const& roomName,
        std::string const& description,
        int playerLimit,
        bool isPrivate,
        std::string const& password
    ) {
        std::string name = GJAccountManager::sharedState()->m_username;
        if (name.empty()) name = "Player";
        Mod::get()->setSettingValue<std::string>("player-name", name);

        if (m_statusLabel) {
            m_statusLabel->setString("Creating room...");
            m_statusLabel->setColor({255, 255, 100});
        }

        auto& session = SessionManager::get();
        session.onSessionStarted([this]() {
            auto& current = SessionManager::get();
            if (current.getRole() == SessionManager::Role::Client) {
                createLoadingView("Waiting for level sync from host...");
            } else {
                this->clearContentNode();
                createSessionView();
                Notification::create("Room created!", NotificationIcon::Success)->show();
            }
        });
        session.onError([this](std::string const& error) {
            auto& net = P2PManager::get();
            std::string fullError = error;
            if (net.getState() == P2PManager::State::Error) {
                fullError = fmt::format("{}\n\nNetwork: {}", error, net.getError());
            }
            m_connectionPending = false;
            m_connectionElapsed = 0.f;
            m_lastConnectionStage = -1;
            this->clearContentNode();
            this->createConnectView();
            if (m_statusLabel) {
                m_statusLabel->setString(error.c_str());
                m_statusLabel->setColor({255, 100, 100});
            }
            log::error("MultiplayerPopup: Session error - {}", fullError);
            FLAlertLayer::create("Connection Error", fullError.c_str(), "OK")->show();
        });

        session.hostSession(name, roomName, description, playerLimit, isPrivate, password);
    }

    void MultiplayerPopup::onJoin(CCObject*) {
        if (!m_roomCodeInput) return;
        beginJoin(std::string(m_roomCodeInput->getString()), "");
    }

    void MultiplayerPopup::beginJoin(std::string const& roomCode, std::string const& password) {
        std::string name = GJAccountManager::sharedState()->m_username;
        if (name.empty()) name = "Player";
        std::string code = roomCode;
        if (code.empty()) {
            Notification::create("Please enter a room code", NotificationIcon::Error)->show();
            return;
        }

        Mod::get()->setSettingValue<std::string>("player-name", name);
        m_connectionPending = true;
        m_connectionElapsed = 0.f;
        m_lastConnectionStage = -1;
        if (m_statusLabel) {
            m_statusLabel->setString("Stage 1/4: Contacting signaling server...");
            m_statusLabel->setColor({255, 255, 100});
        }

        auto& session = SessionManager::get();
        session.onSessionStarted([this]() {
            createLoadingView("Stage 2/4: Negotiating selected transport...");
            m_connectionPending = true;
            m_lastConnectionStage = 2;
        });
        session.onError([this](std::string const& error) {
            auto& net = P2PManager::get();
            std::string fullError = error;
            if (net.getState() == P2PManager::State::Error) {
                fullError = fmt::format("{}\n\nNetwork: {}", error, net.getError());
            }
            m_connectionPending = false;
            this->clearContentNode();
            this->createConnectView();
            if (m_statusLabel) {
                m_statusLabel->setString(error.c_str());
                m_statusLabel->setColor({255, 100, 100});
            }
            log::error("MultiplayerPopup: Session error - {}", fullError);
            FLAlertLayer::create("Connection Error", fullError.c_str(), "OK")->show();
        });
        session.joinSession(code, name, password);
    }

'''
text = regex_once(
    text,
    r'    void MultiplayerPopup::onHost\(CCObject\*\) \{.*?\n    void MultiplayerPopup::onLeave\(CCObject\*\) \{',
    new_host_join + '    void MultiplayerPopup::onLeave(CCObject*) {',
    "MultiplayerPopup host/join actions",
)
text = re.sub(
    r'\n    void MultiplayerPopup::onPatreon\(CCObject\*\) \{.*?\n    \}\n',
    '\n',
    text,
    count=1,
    flags=re.S,
)
if "patreon.com" in text or "Patreon" in text:
    raise RuntimeError("Patreon UI/link still present in MultiplayerPopup.cpp")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Signaling server room directory + private/password room semantics.
# ---------------------------------------------------------------------------
path = Path("server/signaling/server.ts")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''  nextPlayerId: number;
  host: Participant;
  clients: Map<number, Participant>;''',
    '''  nextPlayerId: number;
  roomName: string;
  description: string;
  playerLimit: number;
  isPrivate: boolean;
  password: string;
  host: Participant;
  clients: Map<number, Participant>;''',
    "server Room metadata fields",
)
text = replace_once(
    text,
    '''function sanitizeTransportMode(value: unknown): string {
  if (typeof value !== "string") return "auto";
  const normalized = value.trim().toLowerCase();
  if (["auto", "webrtc", "turn", "http-relay"].includes(normalized)) return normalized;
  return "auto";
}
''',
    '''function sanitizeTransportMode(value: unknown): string {
  if (typeof value !== "string") return "auto";
  const normalized = value.trim().toLowerCase();
  if (["auto", "webrtc", "turn", "http-relay"].includes(normalized)) return normalized;
  return "auto";
}

function sanitizeRoomText(value: unknown, maxLength: number, fallback = ""): string {
  if (typeof value !== "string") return fallback;
  const clean = value.replace(/[\\r\\n\\t]/g, " ").trim().slice(0, maxLength);
  return clean || fallback;
}

function sanitizePlayerLimit(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 8;
  return Math.max(2, Math.min(16, Math.trunc(numeric)));
}

function sanitizePassword(value: unknown): string {
  return typeof value === "string" ? value.slice(0, 48) : "";
}
''',
    "server metadata sanitizers",
)
text = replace_once(
    text,
    '''  if (req.method === "POST" && path === "/rooms") {''',
    '''  if (req.method === "GET" && path === "/rooms") {
    const publicRooms = [...rooms.values()]
      .filter((room) => !room.isPrivate)
      .sort((a, b) => b.lastActivityAt - a.lastActivityAt)
      .slice(0, 100)
      .map((room) => ({
        roomCode: room.roomCode,
        roomName: room.roomName,
        description: room.description,
        hostName: room.host.playerName,
        playerCount: room.clients.size + 1,
        playerLimit: room.playerLimit,
        hasPassword: room.password.length > 0,
        transportMode: room.host.transportMode,
        createdAt: room.createdAt,
      }));
    return json(publicRooms);
  }

  if (req.method === "POST" && path === "/rooms") {''',
    "server public room list endpoint",
)
text = replace_once(
    text,
    '''      generation: 1,
      nextPlayerId: 1,
      host,
      clients: new Map(),''',
    '''      generation: 1,
      nextPlayerId: 1,
      roomName: sanitizeRoomText(body.roomName, 32, `${host.playerName}'s Room`),
      description: sanitizeRoomText(body.description, 64),
      playerLimit: sanitizePlayerLimit(body.playerLimit),
      isPrivate: body.isPrivate === true,
      password: sanitizePassword(body.password),
      host,
      clients: new Map(),''',
    "server room metadata initialization",
)
text = replace_once(
    text,
    '''      hostTransportMode: host.transportMode,
    }, 201);''',
    '''      hostTransportMode: host.transportMode,
      roomName: room.roomName,
      isPrivate: room.isPrivate,
      hasPassword: room.password.length > 0,
      playerLimit: room.playerLimit,
    }, 201);''',
    "server create metadata response",
)
text = replace_once(
    text,
    '''      const body = await readJson(req);
      if (!body) return json({ error: "invalid request body" }, 400);

      const previousToken = bearerToken(req);''',
    '''      const body = await readJson(req);
      if (!body) return json({ error: "invalid request body" }, 400);

      if (room.password.length > 0 && sanitizePassword(body.password) !== room.password) {
        return json({ error: "invalid room password", passwordRequired: true }, 403);
      }

      const previousToken = bearerToken(req);''',
    "server join password validation",
)
text = replace_once(
    text,
    '''      // Hard server-side safety cap. Room Settings may enforce a lower limit.
      if (room.clients.size >= 31) {
        return json({ error: "room capacity reached" }, 429);
      }''',
    '''      // Directory-level capacity is enforced before signaling/WebRTC setup.
      // Protocol Room Settings still apply host-side permissions after handshake.
      if (room.clients.size + 1 >= room.playerLimit) {
        return json({ error: "room capacity reached" }, 429);
      }''',
    "server room player limit",
)
text = replace_once(
    text,
    '''        hostTransportMode: room.host.transportMode,
      });''',
    '''        hostTransportMode: room.host.transportMode,
        roomName: room.roomName,
        hasPassword: room.password.length > 0,
        playerLimit: room.playerLimit,
      });''',
    "server join metadata response",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Strengthen production CI invariants for this feature.
# ---------------------------------------------------------------------------
path = Path(".github/workflows/multi-platform-release.yml")
text = path.read_text(encoding="utf-8")
needle = '''          assert "194.226.126.115" not in p2p

          print("v0.5.3 transport + synchronization architecture verification passed")'''
replacement = '''          assert "194.226.126.115" not in p2p

          popup = Path("src/ui/MultiplayerPopup.cpp").read_text(encoding="utf-8")
          discovery = Path("src/ui/RoomDiscoveryPopups.cpp").read_text(encoding="utf-8")
          assert "Public Rooms" in popup
          assert "Private Room" in popup
          assert "CreateRoomPopup" in popup
          assert "RoomBrowserPopup" in discovery
          assert "PasswordPopup" in discovery
          assert "patreon.com" not in popup.lower()
          assert "Patreon" not in popup
          assert 'req.method === "GET" && path === "/rooms"' in signaling
          assert "isPrivate" in signaling
          assert "passwordRequired" in signaling
          assert "playerLimit" in signaling

          print("v0.5.3 transport + synchronization + room browser verification passed")'''
text = replace_once(text, needle, replacement, "production CI room browser invariants")
path.write_text(text, encoding="utf-8")

print("room browser integration patch applied")
