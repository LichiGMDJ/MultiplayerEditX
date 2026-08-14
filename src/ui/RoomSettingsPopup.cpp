#include "RoomSettingsPopup.hpp"
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

    auto size = m_mainLayer->getContentSize();
    auto center = size / 2.f;
    auto settings = P2PManager::get().getRoomSettings();
    bool forceTurn = Mod::get()->getSettingValue<bool>("force-turn-relay");

    auto* menu = CCMenu::create();
    menu->setPosition({0.f, 0.f});
    m_body->addChild(menu);

    // Fixed two-column grid. Labels and toggles have independent coordinates so
    // long labels never overlap adjacent controls.
    constexpr float leftLabelX = 34.f;
    constexpr float leftButtonX = 166.f;
    constexpr float rightLabelX = 238.f;
    constexpr float rightButtonX = 346.f;
    constexpr float toggleWidth = 58.f;

    auto addToggle = [&](const char* label, bool value, int tag,
                         float labelX, float buttonX, float y) {
        auto* name = CCLabelBMFont::create(label, "chatFont.fnt");
        name->setScale(0.38f);
        name->setAnchorPoint({0.f, 0.5f});
        name->setPosition({labelX, y});
        m_body->addChild(name);

        auto* btn = makeButton(
            value ? "ON" : "OFF",
            this,
            menu_selector(RoomSettingsPopup::onToggle),
            toggleWidth
        );
        btn->setTag(tag);
        btn->setPosition({buttonX, y});
        menu->addChild(btn);
    };

    // Max players row, centered and compact.
    float topY = center.height + 82.f;
    auto* maxLabel = CCLabelBMFont::create(
        fmt::format("Max players: {}", settings.maxPlayers).c_str(),
        "chatFont.fnt"
    );
    maxLabel->setScale(0.43f);
    maxLabel->setAnchorPoint({1.f, 0.5f});
    maxLabel->setPosition({center.width - 18.f, topY});
    m_body->addChild(maxLabel);

    constexpr float maxButtonWidth = 28.f;
    constexpr float maxPairCenterX = 276.f;
    constexpr float maxButtonHalfGap = 34.f;

    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), maxButtonWidth);
    minus->setPosition({maxPairCenterX - maxButtonHalfGap, topY});
    menu->addChild(minus);

    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), maxButtonWidth);
    plus->setPosition({maxPairCenterX + maxButtonHalfGap, topY});
    menu->addChild(plus);

    constexpr float row1 = 196.f;
    constexpr float row2 = 160.f;
    constexpr float row3 = 124.f;
    constexpr float row4 = 88.f;

    addToggle("Guests can build/edit", settings.allowBuild, Build,
              leftLabelX, leftButtonX, row1);
    addToggle("Guests can delete", settings.allowDelete, Delete,
              rightLabelX, rightButtonX, row1);

    addToggle("Object Workshop", settings.allowWorkshop, Workshop,
              leftLabelX, leftButtonX, row2);
    addToggle("Level settings", settings.allowLevelSettings, LevelSettings,
              rightLabelX, rightButtonX, row2);

    addToggle("Auto repair", settings.autoRepair, AutoRepair,
              leftLabelX, leftButtonX, row3);
    addToggle("Force TURN (host)", forceTurn, ForceTurn,
              rightLabelX, rightButtonX, row3);

    addToggle("Lock room", settings.locked, LockRoom,
              leftLabelX, leftButtonX, row4);

    auto* note = CCLabelBMFont::create(
        "Force TURN affects new/reconnected peers",
        "chatFont.fnt"
    );
    note->setScale(0.28f);
    note->setAnchorPoint({0.5f, 0.5f});
    note->setColor({175, 175, 175});
    note->setPosition({rightButtonX - 18.f, row4});
    m_body->addChild(note);

    // Kick section kept close to the settings instead of floating at the bottom.
    constexpr float playerY = 48.f;
    auto* playersTitle = CCLabelBMFont::create("Kick players:", "chatFont.fnt");
    playersTitle->setScale(0.36f);
    playersTitle->setAnchorPoint({0.f, 0.5f});
    playersTitle->setPosition({leftLabelX, playerY});
    m_body->addChild(playersTitle);

    float x = 128.f;
    for (auto const& player : SessionManager::get().getPlayers()) {
        if (player.id == SessionManager::get().getLocalPlayerId()) continue;
        auto* btn = makeButton(
            ("X " + player.name).c_str(),
            this,
            menu_selector(RoomSettingsPopup::onKick),
            82.f
        );
        btn->setTag(player.id);
        btn->setPosition({x, playerY});
        menu->addChild(btn);
        x += 88.f;
        if (x > 390.f) break;
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
