from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)

# =============================================================================
# Protocol v6: synchronized host Room Settings.
# =============================================================================
proto_hpp_path = Path("src/BinaryProtocol.hpp")
proto_hpp = proto_hpp_path.read_text(encoding="utf-8")
proto_hpp = replace_once(
    proto_hpp,
    "        MusicChanged          = 0x46,\n",
    "        MusicChanged          = 0x46,\n        RoomSettingsChanged   = 0x47,\n",
    "RoomSettingsChanged opcode",
)
proto_hpp = replace_once(
    proto_hpp,
    "    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title);\n",
    "    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title);\n    std::vector<uint8_t> serializeRoomSettingsChanged(\n        uint32_t maxPlayers, bool allowBuild, bool allowDelete, bool allowWorkshop,\n        bool allowLevelSettings, bool autoRepair, bool locked);\n",
    "room settings serializer declaration",
)
proto_hpp = replace_once(
    proto_hpp,
    "    struct MusicChangedMsg {\n        int songID = 0;\n        int audioTrack = 0;\n        std::string title;\n    };\n    MusicChangedMsg deserializeMusicChanged(Reader& r);\n",
    "    struct MusicChangedMsg {\n        int songID = 0;\n        int audioTrack = 0;\n        std::string title;\n    };\n    MusicChangedMsg deserializeMusicChanged(Reader& r);\n\n    struct RoomSettingsChangedMsg {\n        uint32_t maxPlayers = 8;\n        bool allowBuild = true;\n        bool allowDelete = true;\n        bool allowWorkshop = true;\n        bool allowLevelSettings = true;\n        bool autoRepair = true;\n        bool locked = false;\n    };\n    RoomSettingsChangedMsg deserializeRoomSettingsChanged(Reader& r);\n",
    "room settings message declaration",
)
proto_hpp_path.write_text(proto_hpp, encoding="utf-8")

proto_cpp_path = Path("src/BinaryProtocol.cpp")
proto_cpp = proto_cpp_path.read_text(encoding="utf-8")
proto_cpp = replace_once(
    proto_cpp,
    "    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title) {\n        Writer w;\n        w.writeOpcode(Opcode::MusicChanged);\n        w.writeI32(songID);\n        w.writeI32(audioTrack);\n        w.writeString(title);\n        return std::move(w.takeData());\n    }\n",
    "    std::vector<uint8_t> serializeMusicChanged(int songID, int audioTrack, std::string const& title) {\n        Writer w;\n        w.writeOpcode(Opcode::MusicChanged);\n        w.writeI32(songID);\n        w.writeI32(audioTrack);\n        w.writeString(title);\n        return std::move(w.takeData());\n    }\n\n    std::vector<uint8_t> serializeRoomSettingsChanged(\n        uint32_t maxPlayers, bool allowBuild, bool allowDelete, bool allowWorkshop,\n        bool allowLevelSettings, bool autoRepair, bool locked)\n    {\n        Writer w;\n        w.writeOpcode(Opcode::RoomSettingsChanged);\n        w.writeVarInt(maxPlayers);\n        w.writeBool(allowBuild);\n        w.writeBool(allowDelete);\n        w.writeBool(allowWorkshop);\n        w.writeBool(allowLevelSettings);\n        w.writeBool(autoRepair);\n        w.writeBool(locked);\n        return std::move(w.takeData());\n    }\n",
    "room settings serializer",
)
proto_cpp = replace_once(
    proto_cpp,
    "    MusicChangedMsg deserializeMusicChanged(Reader& r) {\n        MusicChangedMsg msg;\n        msg.songID = r.readI32();\n        msg.audioTrack = r.readI32();\n        msg.title = r.readString();\n        return msg;\n    }\n",
    "    MusicChangedMsg deserializeMusicChanged(Reader& r) {\n        MusicChangedMsg msg;\n        msg.songID = r.readI32();\n        msg.audioTrack = r.readI32();\n        msg.title = r.readString();\n        return msg;\n    }\n\n    RoomSettingsChangedMsg deserializeRoomSettingsChanged(Reader& r) {\n        RoomSettingsChangedMsg msg;\n        msg.maxPlayers = r.readVarInt();\n        msg.allowBuild = r.readBool();\n        msg.allowDelete = r.readBool();\n        msg.allowWorkshop = r.readBool();\n        msg.allowLevelSettings = r.readBool();\n        msg.autoRepair = r.readBool();\n        msg.locked = r.readBool();\n        return msg;\n    }\n",
    "room settings deserializer",
)
proto_cpp_path.write_text(proto_cpp, encoding="utf-8")

# =============================================================================
# P2P state / enforcement.
# =============================================================================
p2p_hpp_path = Path("src/P2PManager.hpp")
p2p_hpp = p2p_hpp_path.read_text(encoding="utf-8")
p2p_hpp = replace_once(
    p2p_hpp,
    "        void kickPlayer(int playerId);",
    "        struct RoomSettings {\n            uint32_t maxPlayers = 8;\n            bool allowBuild = true;\n            bool allowDelete = true;\n            bool allowWorkshop = true;\n            bool allowLevelSettings = true;\n            bool autoRepair = true;\n            bool locked = false;\n        };\n\n        RoomSettings getRoomSettings() const;\n        void setRoomSettings(RoomSettings const& settings);\n        void kickPlayer(int playerId);",
    "room settings public API",
)
p2p_hpp = replace_once(
    p2p_hpp,
    "        std::unordered_set<std::string> m_kickedNames;",
    "        std::unordered_set<std::string> m_kickedNames;\n        RoomSettings m_roomSettings;\n        mutable std::mutex m_roomSettingsMutex;",
    "room settings state",
)
p2p_hpp_path.write_text(p2p_hpp, encoding="utf-8")

p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(p2p, "constexpr uint32_t kProtocolVersion = 5;", "constexpr uint32_t kProtocolVersion = 6;", "protocol v6")
p2p = replace_once(
    p2p,
    "                        opcode == proto::Opcode::MusicChanged;",
    "                        opcode == proto::Opcode::MusicChanged ||\n                        opcode == proto::Opcode::RoomSettingsChanged;",
    "RoomSettingsChanged ACK FIFO",
)

# API implementation before kickPlayer.
kick_sig = "    void P2PManager::kickPlayer(int playerId) {"
api_impl = '''    P2PManager::RoomSettings P2PManager::getRoomSettings() const {
        std::lock_guard lock(m_roomSettingsMutex);
        return m_roomSettings;
    }

    void P2PManager::setRoomSettings(RoomSettings const& settings) {
        if (m_role != Role::Host) return;
        RoomSettings safe = settings;
        safe.maxPlayers = std::clamp<uint32_t>(safe.maxPlayers, 2, 16);
        {
            std::lock_guard lock(m_roomSettingsMutex);
            m_roomSettings = safe;
        }
        auto packet = proto::serializeRoomSettingsChanged(
            safe.maxPlayers, safe.allowBuild, safe.allowDelete, safe.allowWorkshop,
            safe.allowLevelSettings, safe.autoRepair, safe.locked
        );
        broadcast(packet, ChannelType::Reliable);
        log::info(
            "P2PManager: ROOM SETTINGS max={} build={} delete={} workshop={} settings={} repair={} locked={}",
            safe.maxPlayers, safe.allowBuild, safe.allowDelete, safe.allowWorkshop,
            safe.allowLevelSettings, safe.autoRepair, safe.locked
        );
    }

'''
if kick_sig not in p2p:
    raise SystemExit("room settings API: kickPlayer anchor missing")
p2p = p2p.replace(kick_sig, api_impl + kick_sig, 1)

# Host-side permission enforcement after protocol verification, before control/editor handling.
anchor = "        if (!protocolVerified) return;\n\n        if (opcode == static_cast<uint8_t>(proto::Opcode::GlobalRevision)) {"
permission = '''        if (!protocolVerified) return;

        if (m_role == Role::Host && fromPlayerId > 0) {
            auto settings = getRoomSettings();
            auto op = static_cast<proto::Opcode>(opcode);
            bool denied = false;
            const char* deniedReason = nullptr;

            if (!settings.allowWorkshop && (
                op == proto::Opcode::BulkPasteStart ||
                op == proto::Opcode::BulkPasteChunk ||
                op == proto::Opcode::BulkPasteEnd
            )) {
                denied = true;
                deniedReason = "Object Workshop is disabled by host";
            } else if (!settings.allowDelete && op == proto::Opcode::DeleteObjects) {
                denied = true;
                deniedReason = "Guest deletion is disabled by host";
            } else if (!settings.allowLevelSettings && op == proto::Opcode::UpdateSettings) {
                denied = true;
                deniedReason = "Level settings are host-only";
            } else if (!settings.allowBuild && (
                op == proto::Opcode::PlaceObjects ||
                op == proto::Opcode::MoveObjects ||
                op == proto::Opcode::MoveBatch ||
                op == proto::Opcode::TransformObjects ||
                op == proto::Opcode::ReconcileObjects ||
                op == proto::Opcode::UpdateObjects
            )) {
                denied = true;
                deniedReason = "Guest building/editing is disabled by host";
            }

            if (denied) {
                log::warn("P2PManager: blocked guest {} opcode {}: {}", fromPlayerId, static_cast<int>(opcode), deniedReason);
                return;
            }
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::RoomSettingsChanged)) {
            if (m_role != Role::Client || fromPlayerId != 0) return;
            proto::Reader roomReader(data + 1, len - 1);
            auto msg = proto::deserializeRoomSettingsChanged(roomReader);
            if (roomReader.hasError()) return;
            RoomSettings settings;
            settings.maxPlayers = std::clamp<uint32_t>(msg.maxPlayers, 2, 16);
            settings.allowBuild = msg.allowBuild;
            settings.allowDelete = msg.allowDelete;
            settings.allowWorkshop = msg.allowWorkshop;
            settings.allowLevelSettings = msg.allowLevelSettings;
            settings.autoRepair = msg.autoRepair;
            settings.locked = msg.locked;
            {
                std::lock_guard lock(m_roomSettingsMutex);
                m_roomSettings = settings;
            }
            log::info("P2PManager: applied ROOM SETTINGS from host");
            return;
        }

        if (opcode == static_cast<uint8_t>(proto::Opcode::GlobalRevision)) {'''
p2p = replace_once(p2p, anchor, permission, "room permission gate and settings control")

# Enforce locked/max players at handshake and send current settings to accepted new peer.
handshake_log = '''        log::info(
            "P2PManager: protocol handshake complete for player {}; releasing {} pending messages",
            pid,
            pending.size()
        );'''
handshake_new = '''        if (m_role == Role::Host && pid > 0 && !isPeerReconnect(pid)) {
            auto settings = getRoomSettings();
            size_t peerCount = 0;
            {
                std::lock_guard lock(m_peersMutex);
                peerCount = m_peers.size() + 1; // + host
            }
            std::string rejection;
            if (settings.locked) rejection = "Room is locked by host";
            else if (peerCount > settings.maxPlayers) rejection = "Room is full";
            if (!rejection.empty()) {
                auto packet = proto::serializeKickPlayer(pid, rejection);
                sendTo(pid, packet, ChannelType::Reliable);
                log::warn("P2PManager: rejected player {}: {}", pid, rejection);
                std::thread([this, pid]() {
                    std::this_thread::sleep_for(std::chrono::milliseconds(300));
                    onPeerDisconnected(pid, false);
                }).detach();
                return;
            }
        }

        log::info(
            "P2PManager: protocol handshake complete for player {}; releasing {} pending messages",
            pid,
            pending.size()
        );

        if (m_role == Role::Host && pid > 0) {
            auto settings = getRoomSettings();
            auto roomPacket = proto::serializeRoomSettingsChanged(
                settings.maxPlayers, settings.allowBuild, settings.allowDelete, settings.allowWorkshop,
                settings.allowLevelSettings, settings.autoRepair, settings.locked
            );
            sendTo(pid, roomPacket, ChannelType::Reliable);
        }'''
p2p = replace_once(p2p, handshake_log, handshake_new, "room capacity handshake enforcement")

# Reset host room settings when a new room is created.
host_reset = '''        m_state.store(State::Connecting);
        m_nextPlayerId = 1;'''
host_reset_new = '''        m_state.store(State::Connecting);
        m_nextPlayerId = 1;
        {
            std::lock_guard lock(m_roomSettingsMutex);
            m_roomSettings = RoomSettings{};
        }'''
p2p = replace_once(p2p, host_reset, host_reset_new, "room settings host reset")
p2p_path.write_text(p2p, encoding="utf-8")

# =============================================================================
# Auto repair toggle in shared integrity handler.
# =============================================================================
remote_path = Path("src/RemoteActionHandler.cpp")
remote = remote_path.read_text(encoding="utf-8")
repair_anchor = '''            log::warn(
                "RemoteActionHandler: GLOBAL HASH mismatch rev={} player={} host={}/{} remote={}/{} author={}",
                revision, playerId, localCount, localHash, msg.objectCount, msg.hash,
                p2p.getLastGlobalAuthor()
            );'''
repair_new = repair_anchor + '''

            if (!p2p.getRoomSettings().autoRepair) {
                log::warn("RemoteActionHandler: AUTO REPAIR disabled; leaving rev={} mismatch untouched", revision);
                return;
            }'''
remote = replace_once(remote, repair_anchor, repair_new, "auto repair room toggle")
remote_path.write_text(remote, encoding="utf-8")

# =============================================================================
# Local guest UX guards for direct actions. Host-side checks above remain the
# security/correctness authority even if another mod bypasses these hooks.
# =============================================================================
hooks_path = Path("src/EditorHooks.cpp")
hooks = hooks_path.read_text(encoding="utf-8")
hooks = replace_once(
    hooks,
    '''    GameObject* createObject(int objectID, cocos2d::CCPoint position, bool noUndo) {
        auto* obj = LevelEditorLayer::createObject(objectID, position, noUndo);''',
    '''    GameObject* createObject(int objectID, cocos2d::CCPoint position, bool noUndo) {
        auto& session = SessionManager::get();
        if (session.isInSession() && session.getRole() == SessionManager::Role::Client &&
            !RemoteActionHandler::get().isProcessingRemote() && !P2PManager::get().getRoomSettings().allowBuild) {
            Notification::create("Host disabled guest building", NotificationIcon::Warning)->show();
            return nullptr;
        }
        auto* obj = LevelEditorLayer::createObject(objectID, position, noUndo);''',
    "local build guard",
)
hooks = replace_once(
    hooks,
    '''    void removeObject(GameObject* obj, bool undo) {
        if (!obj) {''',
    '''    void removeObject(GameObject* obj, bool undo) {
        auto& permissionSession = SessionManager::get();
        if (obj && permissionSession.isInSession() && permissionSession.getRole() == SessionManager::Role::Client &&
            !RemoteActionHandler::get().isProcessingRemote() && !P2PManager::get().getRoomSettings().allowDelete) {
            Notification::create("Host disabled guest deletion", NotificationIcon::Warning)->show();
            return;
        }
        if (!obj) {''',
    "local delete guard",
)
# Bulk paste hook from v5.
hooks = replace_once(
    hooks,
    '''        bool shouldBulkSync = session.isInSession()
            && !handler.isProcessingRemote()
            && handler.isInitialSyncCompleted();''',
    '''        if (session.isInSession() && session.getRole() == SessionManager::Role::Client &&
            !handler.isProcessingRemote() && !P2PManager::get().getRoomSettings().allowWorkshop) {
            Notification::create("Host disabled Object Workshop / bulk paste", NotificationIcon::Warning)->show();
            return nullptr;
        }

        bool shouldBulkSync = session.isInSession()
            && !handler.isProcessingRemote()
            && handler.isInitialSyncCompleted();''',
    "local workshop guard",
)
# Level settings: guests may only update when allowed (music remains host-only from v5).
hooks = replace_once(
    hooks,
    '''        auto& handler = RemoteActionHandler::get();
        if (handler.isProcessingRemote() || !handler.isInitialSyncCompleted()) return;''',
    '''        auto& handler = RemoteActionHandler::get();
        if (handler.isProcessingRemote() || !handler.isInitialSyncCompleted()) return;
        if (session.isInSession() && session.getRole() == SessionManager::Role::Client &&
            !P2PManager::get().getRoomSettings().allowLevelSettings) {
            Notification::create("Host disabled guest level settings", NotificationIcon::Warning)->show();
            return;
        }''',
    "local level settings guard",
)
hooks_path.write_text(hooks, encoding="utf-8")

# =============================================================================
# Host Room Settings popup (generated at patch time, picked up by CMake glob).
# =============================================================================
room_hpp = r'''#pragma once
#include <Geode/ui/Popup.hpp>

namespace mpedit {
class RoomSettingsPopup : public geode::Popup {
protected:
    cocos2d::CCNode* m_body = nullptr;
    bool setup();
    void rebuild();
    void onToggle(cocos2d::CCObject* sender);
    void onMaxMinus(cocos2d::CCObject*);
    void onMaxPlus(cocos2d::CCObject*);
    void onKick(cocos2d::CCObject* sender);
public:
    static RoomSettingsPopup* create();
};
}
'''
Path("src/ui/RoomSettingsPopup.hpp").write_text(room_hpp, encoding="utf-8")

room_cpp = r'''#include "RoomSettingsPopup.hpp"
#include "../P2PManager.hpp"
#include "../SessionManager.hpp"
#include <Geode/Geode.hpp>
#include <Geode/ui/Notification.hpp>

using namespace geode::prelude;

namespace mpedit {
namespace {
    enum ToggleTag {
        Build = 1,
        Delete = 2,
        Workshop = 3,
        LevelSettings = 4,
        AutoRepair = 5,
        ForceTurn = 6,
        LockRoom = 7,
    };

    CCMenuItemSpriteExtra* makeButton(const std::string& text, CCObject* target, SEL_MenuHandler cb, float width = 118.f) {
        auto* sprite = ButtonSprite::create(text.c_str(), static_cast<int>(width), true, "bigFont.fnt", "GJ_button_01.png", 20.f, 0.45f);
        return CCMenuItemSpriteExtra::create(sprite, target, cb);
    }
}

RoomSettingsPopup* RoomSettingsPopup::create() {
    auto* ret = new RoomSettingsPopup();
    if (ret->init(410.f, 300.f) && ret->setup()) {
        ret->autorelease();
        return ret;
    }
    delete ret;
    return nullptr;
}

bool RoomSettingsPopup::setup() {
    if (SessionManager::get().getRole() != SessionManager::Role::Host) return false;
    this->setTitle("Room Settings", "goldFont.fnt", 0.75f, 18.f);
    rebuild();
    return true;
}

void RoomSettingsPopup::rebuild() {
    if (m_body) m_body->removeFromParent();
    m_body = CCNode::create();
    m_body->setID("room-settings-body"_spr);
    m_mainLayer->addChild(m_body);

    auto center = m_mainLayer->getContentSize() / 2.f;
    auto settings = P2PManager::get().getRoomSettings();
    bool forceTurn = Mod::get()->getSettingValue<bool>("force-turn-relay");

    auto* menu = CCMenu::create();
    menu->setPosition({0.f, 0.f});
    m_body->addChild(menu);

    auto addToggle = [&](const char* label, bool value, int tag, float x, float y) {
        auto* name = CCLabelBMFont::create(label, "chatFont.fnt");
        name->setScale(0.45f);
        name->setAnchorPoint({0.f, 0.5f});
        name->setPosition({x - 102.f, y});
        m_body->addChild(name);
        auto* btn = makeButton(value ? "ON" : "OFF", this, menu_selector(RoomSettingsPopup::onToggle), 56.f);
        btn->setTag(tag);
        btn->setPosition({x + 78.f, y});
        menu->addChild(btn);
    };

    auto* maxLabel = CCLabelBMFont::create(fmt::format("Max players: {}", settings.maxPlayers).c_str(), "chatFont.fnt");
    maxLabel->setScale(0.48f);
    maxLabel->setPosition({center.width - 95.f, center.height + 83.f});
    m_body->addChild(maxLabel);
    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), 34.f);
    minus->setPosition({center.width - 20.f, center.height + 83.f});
    menu->addChild(minus);
    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), 34.f);
    plus->setPosition({center.width + 22.f, center.height + 83.f});
    menu->addChild(plus);

    addToggle("Guests can build/edit", settings.allowBuild, Build, center.width - 98.f, center.height + 48.f);
    addToggle("Guests can delete", settings.allowDelete, Delete, center.width + 100.f, center.height + 48.f);
    addToggle("Object Workshop", settings.allowWorkshop, Workshop, center.width - 98.f, center.height + 13.f);
    addToggle("Level settings", settings.allowLevelSettings, LevelSettings, center.width + 100.f, center.height + 13.f);
    addToggle("Auto repair", settings.autoRepair, AutoRepair, center.width - 98.f, center.height - 22.f);
    addToggle("Force TURN (host)", forceTurn, ForceTurn, center.width + 100.f, center.height - 22.f);
    addToggle("Lock room", settings.locked, LockRoom, center.width - 98.f, center.height - 57.f);

    auto* note = CCLabelBMFont::create("Force TURN applies to new/reconnected peers", "chatFont.fnt");
    note->setScale(0.35f);
    note->setColor({170, 170, 170});
    note->setPosition({center.width + 90.f, center.height - 58.f});
    m_body->addChild(note);

    float playerY = 42.f;
    auto* playersTitle = CCLabelBMFont::create("Kick players:", "chatFont.fnt");
    playersTitle->setScale(0.4f);
    playersTitle->setAnchorPoint({0.f, 0.5f});
    playersTitle->setPosition({35.f, playerY});
    m_body->addChild(playersTitle);
    float x = 115.f;
    for (auto const& player : SessionManager::get().getPlayers()) {
        if (player.id == SessionManager::get().getLocalPlayerId()) continue;
        auto* btn = makeButton(("X " + player.name).c_str(), this, menu_selector(RoomSettingsPopup::onKick), 86.f);
        btn->setTag(player.id);
        btn->setPosition({x, playerY});
        menu->addChild(btn);
        x += 92.f;
        if (x > 360.f) break;
    }
}

void RoomSettingsPopup::onToggle(CCObject* sender) {
    auto* node = typeinfo_cast<CCNode*>(sender);
    if (!node) return;
    int tag = node->getTag();
    if (tag == ForceTurn) {
        bool value = Mod::get()->getSettingValue<bool>("force-turn-relay");
        Mod::get()->setSettingValue<bool>("force-turn-relay", !value);
        rebuild();
        return;
    }

    auto settings = P2PManager::get().getRoomSettings();
    switch (tag) {
        case Build: settings.allowBuild = !settings.allowBuild; break;
        case Delete: settings.allowDelete = !settings.allowDelete; break;
        case Workshop: settings.allowWorkshop = !settings.allowWorkshop; break;
        case LevelSettings: settings.allowLevelSettings = !settings.allowLevelSettings; break;
        case AutoRepair: settings.autoRepair = !settings.autoRepair; break;
        case LockRoom: settings.locked = !settings.locked; break;
        default: return;
    }
    P2PManager::get().setRoomSettings(settings);
    rebuild();
}

void RoomSettingsPopup::onMaxMinus(CCObject*) {
    auto settings = P2PManager::get().getRoomSettings();
    if (settings.maxPlayers > 2) --settings.maxPlayers;
    P2PManager::get().setRoomSettings(settings);
    rebuild();
}

void RoomSettingsPopup::onMaxPlus(CCObject*) {
    auto settings = P2PManager::get().getRoomSettings();
    if (settings.maxPlayers < 16) ++settings.maxPlayers;
    P2PManager::get().setRoomSettings(settings);
    rebuild();
}

void RoomSettingsPopup::onKick(CCObject* sender) {
    auto* node = typeinfo_cast<CCNode*>(sender);
    if (!node || node->getTag() <= 0) return;
    P2PManager::get().kickPlayer(node->getTag());
    Notification::create("Player kicked", NotificationIcon::Info)->show();
    rebuild();
}
}
'''
Path("src/ui/RoomSettingsPopup.cpp").write_text(room_cpp, encoding="utf-8")

# Add Settings button to existing multiplayer popup host session view.
popup_hpp_path = Path("src/ui/MultiplayerPopup.hpp")
popup_hpp = popup_hpp_path.read_text(encoding="utf-8")
popup_hpp = replace_once(
    popup_hpp,
    "        void onKick(cocos2d::CCObject*);\n        void onPatreon(cocos2d::CCObject*);",
    "        void onKick(cocos2d::CCObject*);\n        void onRoomSettings(cocos2d::CCObject*);\n        void onPatreon(cocos2d::CCObject*);",
    "room settings popup callback declaration",
)
popup_hpp_path.write_text(popup_hpp, encoding="utf-8")

popup_path = Path("src/ui/MultiplayerPopup.cpp")
popup = popup_path.read_text(encoding="utf-8")
popup = popup.replace('#include "UpdateHelperNode.hpp"\n', '#include "UpdateHelperNode.hpp"\n#include "RoomSettingsPopup.hpp"\n', 1)
menu_anchor = '''        // Leave button
        auto* leaveSprite = ButtonSprite::create('''
settings_button = '''        if (session.getRole() == SessionManager::Role::Host) {
            auto* settingsSprite = ButtonSprite::create(
                "Settings", 82, true, "bigFont.fnt", "GJ_button_05.png", 24.f, 0.55f
            );
            auto* settingsBtn = CCMenuItemSpriteExtra::create(
                settingsSprite, this, menu_selector(MultiplayerPopup::onRoomSettings)
            );
            settingsBtn->setPosition({center.width, 72.f});
            settingsBtn->setID("room-settings-button"_spr);
            m_sessionMenu->addChild(settingsBtn);
        }

        // Leave button
        auto* leaveSprite = ButtonSprite::create('''
popup = replace_once(popup, menu_anchor, settings_button, "room settings button")
popup = replace_once(
    popup,
    '''    void MultiplayerPopup::onKick(CCObject* sender) {''',
    '''    void MultiplayerPopup::onRoomSettings(CCObject*) {
        if (SessionManager::get().getRole() != SessionManager::Role::Host) return;
        RoomSettingsPopup::create()->show();
    }

    void MultiplayerPopup::onKick(CCObject* sender) {''',
    "room settings callback implementation",
)
popup_path.write_text(popup, encoding="utf-8")

print("Applied Protocol v6 Room Settings, host permissions, capacity/lock enforcement and host UI")
