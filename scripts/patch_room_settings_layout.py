from pathlib import Path

path = Path("src/ui/RoomSettingsPopup.cpp")
text = path.read_text(encoding="utf-8")

signature = "void RoomSettingsPopup::rebuild()"
start = text.find(signature)
if start == -1:
    raise SystemExit("Room Settings layout: rebuild() not found")
brace = text.find('{', start)
if brace == -1:
    raise SystemExit("Room Settings layout: rebuild() opening brace not found")

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
    raise SystemExit("Room Settings layout: rebuild() closing brace not found")

new_func = r'''void RoomSettingsPopup::rebuild() {
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
    constexpr float leftButtonX = 176.f;
    constexpr float rightLabelX = 220.f;
    constexpr float rightButtonX = 364.f;
    constexpr float toggleWidth = 62.f;

    auto addToggle = [&](const char* label, bool value, int tag,
                         float labelX, float buttonX, float y) {
        auto* name = CCLabelBMFont::create(label, "chatFont.fnt");
        name->setScale(0.40f);
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

    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), 34.f);
    minus->setPosition({center.width + 18.f, topY});
    menu->addChild(minus);

    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), 34.f);
    plus->setPosition({center.width + 58.f, topY});
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
    note->setPosition({rightButtonX - 34.f, row4});
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
}'''

text = text[:start] + new_func + text[end:]
path.write_text(text, encoding="utf-8")
print("Polished Room Settings two-column layout")
