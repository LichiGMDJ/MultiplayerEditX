#include "RoomDiscoveryPopups.hpp"
#include "MultiplayerPopup.hpp"
#include "../P2PManager.hpp"

#include <Geode/Geode.hpp>
#include <Geode/ui/Notification.hpp>

#include <algorithm>
#include <cctype>

using namespace geode::prelude;

namespace mpedit {
namespace {
    CCMenuItemSpriteExtra* makeButton(
        char const* text,
        CCObject* target,
        SEL_MenuHandler callback,
        float width = 112.f,
        char const* texture = "GJ_button_01.png"
    ) {
        auto* sprite = ButtonSprite::create(text, static_cast<int>(width), true, "bigFont.fnt", texture, 28.f, 0.52f);
        return CCMenuItemSpriteExtra::create(sprite, target, callback);
    }

    CCLabelBMFont* makeLabel(char const* text, float scale, CCPoint pos, CCNode* parent) {
        auto* label = CCLabelBMFont::create(text, "chatFont.fnt");
        label->setScale(scale);
        label->setPosition(pos);
        parent->addChild(label);
        return label;
    }

    std::string trimmed(std::string value, std::size_t maxLen) {
        while (!value.empty() && std::isspace(static_cast<unsigned char>(value.front()))) value.erase(value.begin());
        while (!value.empty() && std::isspace(static_cast<unsigned char>(value.back()))) value.pop_back();
        if (value.size() > maxLen) value.resize(maxLen);
        return value;
    }
}

CreateRoomPopup* CreateRoomPopup::create(MultiplayerPopup* owner) {
    auto* ret = new CreateRoomPopup();
    ret->m_owner = owner;
    if (ret->init(390.f, 300.f) && ret->setup()) {
        ret->autorelease();
        return ret;
    }
    delete ret;
    return nullptr;
}

bool CreateRoomPopup::setup() {
    this->setTitle("Create Room", "goldFont.fnt", 0.75f, 18.f);
    auto center = m_mainLayer->getContentSize() / 2.f;

    m_nameInput = TextInput::create(260.f, "Room name", "chatFont.fnt");
    m_nameInput->setPosition({center.width, center.height + 70.f});
    m_nameInput->setMaxCharCount(32);
    m_mainLayer->addChild(m_nameInput);

    m_descriptionInput = TextInput::create(260.f, "Description (optional)", "chatFont.fnt");
    m_descriptionInput->setPosition({center.width, center.height + 30.f});
    m_descriptionInput->setMaxCharCount(64);
    m_mainLayer->addChild(m_descriptionInput);

    makeLabel("Player limit", 0.52f, {center.width - 102.f, center.height - 10.f}, m_mainLayer);
    m_limitInput = TextInput::create(54.f, "8", "chatFont.fnt");
    m_limitInput->setPosition({center.width - 25.f, center.height - 10.f});
    m_limitInput->setFilter("0123456789");
    m_limitInput->setMaxCharCount(2);
    m_limitInput->setString("8");
    m_mainLayer->addChild(m_limitInput);

    auto* menu = CCMenu::create();
    menu->setPosition({0.f, 0.f});
    m_mainLayer->addChild(menu);

    m_visibilitySprite = ButtonSprite::create("Public", 88, true, "bigFont.fnt", "GJ_button_04.png", 24.f, 0.46f);
    auto* visibility = CCMenuItemSpriteExtra::create(
        m_visibilitySprite, this, menu_selector(CreateRoomPopup::onVisibility)
    );
    visibility->setPosition({center.width + 82.f, center.height - 10.f});
    menu->addChild(visibility);

    m_passwordInput = TextInput::create(260.f, "Password (optional)", "chatFont.fnt");
    m_passwordInput->setPosition({center.width, center.height - 52.f});
    m_passwordInput->setMaxCharCount(48);
    m_passwordInput->setPasswordMode(true);
    m_mainLayer->addChild(m_passwordInput);

    auto* create = makeButton("Create", this, menu_selector(CreateRoomPopup::onCreate), 126.f, "GJ_button_02.png");
    create->setPosition({center.width, 42.f});
    menu->addChild(create);

    auto* hint = makeLabel(
        "Private rooms are hidden\nfrom the public browser",
        0.56f,
        {center.width, 70.f},
        m_mainLayer
    );
    hint->setColor({180, 180, 180});
    return true;
}

void CreateRoomPopup::onVisibility(CCObject*) {
    m_private = !m_private;
    if (m_visibilitySprite) {
        m_visibilitySprite->setString(m_private ? "Private" : "Public");
        m_visibilitySprite->updateBGImage(m_private ? "GJ_button_05.png" : "GJ_button_04.png");
    }
}

void CreateRoomPopup::onCreate(CCObject*) {
    if (!m_owner || !m_nameInput || !m_limitInput || !m_passwordInput) return;

    auto roomName = trimmed(std::string(m_nameInput->getString()), 32);
    if (roomName.empty()) roomName = "Untitled Room";
    auto description = m_descriptionInput
        ? trimmed(std::string(m_descriptionInput->getString()), 64)
        : std::string{};
    auto password = trimmed(std::string(m_passwordInput->getString()), 48);

    int playerLimit = 8;
    try {
        auto raw = std::string(m_limitInput->getString());
        if (!raw.empty()) playerLimit = std::stoi(raw);
    } catch (...) {
        playerLimit = 8;
    }
    playerLimit = std::clamp(playerLimit, 2, 16);

    auto* owner = m_owner;
    this->onClose(nullptr);
    owner->beginHost(roomName, description, playerLimit, m_private, password);
}

PasswordPopup* PasswordPopup::create(MultiplayerPopup* owner, std::string roomCode, std::string roomName) {
    auto* ret = new PasswordPopup();
    ret->m_owner = owner;
    ret->m_roomCode = std::move(roomCode);
    ret->m_roomName = std::move(roomName);
    if (ret->init(330.f, 190.f) && ret->setup()) {
        ret->autorelease();
        return ret;
    }
    delete ret;
    return nullptr;
}

bool PasswordPopup::setup() {
    this->setTitle("Password Required", "goldFont.fnt", 0.7f, 18.f);
    auto center = m_mainLayer->getContentSize() / 2.f;
    auto* name = makeLabel(m_roomName.c_str(), 0.45f, {center.width, center.height + 28.f}, m_mainLayer);
    name->setColor({220, 220, 220});

    m_passwordInput = TextInput::create(220.f, "Enter password", "chatFont.fnt");
    m_passwordInput->setPosition({center.width, center.height - 10.f});
    m_passwordInput->setMaxCharCount(48);
    m_passwordInput->setPasswordMode(true);
    m_mainLayer->addChild(m_passwordInput);

    auto* menu = CCMenu::create();
    menu->setPosition({0.f, 0.f});
    auto* join = makeButton("Join", this, menu_selector(PasswordPopup::onJoin), 110.f);
    join->setPosition({center.width, 36.f});
    menu->addChild(join);
    m_mainLayer->addChild(menu);
    return true;
}

void PasswordPopup::onJoin(CCObject*) {
    if (!m_owner || !m_passwordInput) return;
    auto password = trimmed(std::string(m_passwordInput->getString()), 48);
    auto* owner = m_owner;
    auto roomCode = m_roomCode;
    this->onClose(nullptr);
    owner->beginJoin(roomCode, password);
}

PrivateRoomPopup* PrivateRoomPopup::create(MultiplayerPopup* owner) {
    auto* ret = new PrivateRoomPopup();
    ret->m_owner = owner;
    if (ret->init(340.f, 220.f) && ret->setup()) {
        ret->autorelease();
        return ret;
    }
    delete ret;
    return nullptr;
}

bool PrivateRoomPopup::setup() {
    this->setTitle("Private Room", "goldFont.fnt", 0.72f, 18.f);
    auto center = m_mainLayer->getContentSize() / 2.f;

    m_codeInput = TextInput::create(220.f, "Room code", "chatFont.fnt");
    m_codeInput->setPosition({center.width, center.height + 25.f});
    m_codeInput->setCommonFilter(CommonFilter::Alphanumeric);
    m_codeInput->setMaxCharCount(12);
    m_mainLayer->addChild(m_codeInput);

    m_passwordInput = TextInput::create(220.f, "Password (if required)", "chatFont.fnt");
    m_passwordInput->setPosition({center.width, center.height - 20.f});
    m_passwordInput->setMaxCharCount(48);
    m_passwordInput->setPasswordMode(true);
    m_mainLayer->addChild(m_passwordInput);

    auto* menu = CCMenu::create();
    menu->setPosition({0.f, 0.f});
    auto* join = makeButton("Join", this, menu_selector(PrivateRoomPopup::onJoin), 110.f);
    join->setPosition({center.width, 38.f});
    menu->addChild(join);
    m_mainLayer->addChild(menu);
    return true;
}

void PrivateRoomPopup::onJoin(CCObject*) {
    if (!m_owner || !m_codeInput || !m_passwordInput) return;
    auto code = trimmed(std::string(m_codeInput->getString()), 12);
    if (code.empty()) {
        Notification::create("Enter a room code", NotificationIcon::Error)->show();
        return;
    }
    std::transform(code.begin(), code.end(), code.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    auto password = trimmed(std::string(m_passwordInput->getString()), 48);
    auto* owner = m_owner;
    this->onClose(nullptr);
    owner->beginJoin(code, password);
}

RoomBrowserPopup* RoomBrowserPopup::create(MultiplayerPopup* owner) {
    auto* ret = new RoomBrowserPopup();
    ret->m_owner = owner;
    if (ret->init(430.f, 310.f) && ret->setup()) {
        ret->autorelease();
        return ret;
    }
    delete ret;
    return nullptr;
}

bool RoomBrowserPopup::setup() {
    this->setTitle("Public Rooms", "goldFont.fnt", 0.75f, 18.f);
    m_body = CCNode::create();
    m_mainLayer->addChild(m_body);
    fetchRooms();
    this->scheduleUpdate();
    return true;
}

void RoomBrowserPopup::update(float dt) {
    m_autoRefreshTimer += dt;
    if (m_autoRefreshTimer < 4.f) return;
    m_autoRefreshTimer = 0.f;
    fetchRooms(false);
}

void RoomBrowserPopup::fetchRooms(bool showLoading) {
    if (!m_body || m_fetchInFlight) return;
    m_fetchInFlight = true;
    if (showLoading) {
        m_rooms.clear();
        m_page = 0;
        m_body->removeAllChildren();
        auto center = m_mainLayer->getContentSize() / 2.f;
        m_statusLabel = makeLabel("Loading rooms...", 0.45f, center, m_body);
    }

    auto url = P2PManager::getSignalingUrl() + "/rooms";
    auto req = web::WebRequest();
    req.timeout(std::chrono::seconds(10));
    m_request.spawn(req.get(url), [this, url, showLoading](web::WebResponse res) {
        m_fetchInFlight = false;
        if (!m_body) return;
        if (!res.ok()) {
            log::warn("RoomBrowserPopup: GET {} failed code={} error={}", url, res.code(), res.errorMessage());
            if (showLoading) {
                m_body->removeAllChildren();
                m_statusLabel = makeLabel("Could not load rooms", 0.45f, m_mainLayer->getContentSize() / 2.f, m_body);
                m_statusLabel->setColor({255, 120, 120});
            }
            return;
        }

        auto json = res.json().unwrapOr(matjson::Value());
        if (!json.isArray()) {
            m_body->removeAllChildren();
            m_statusLabel = makeLabel("Invalid server response", 0.45f, m_mainLayer->getContentSize() / 2.f, m_body);
            return;
        }

        std::vector<BrowserRoomInfo> freshRooms;
        freshRooms.reserve(json.size());
        for (std::size_t i = 0; i < json.size(); ++i) {
            auto itemResult = json.get(i);
            if (!itemResult.isOk()) continue;
            auto item = itemResult.unwrap();
            BrowserRoomInfo room;
            room.roomCode = item.get<std::string>("roomCode").unwrapOr("");
            room.roomName = item.get<std::string>("roomName").unwrapOr("Untitled Room");
            room.description = item.get<std::string>("description").unwrapOr("");
            room.hostName = item.get<std::string>("hostName").unwrapOr("Host");
            room.playerCount = item.get<int>("playerCount").unwrapOr(1);
            room.playerLimit = item.get<int>("playerLimit").unwrapOr(8);
            room.hasPassword = item.get<bool>("hasPassword").unwrapOr(false);
            room.transportMode = item.get<std::string>("transportMode").unwrapOr("auto");
            if (!room.roomCode.empty()) freshRooms.push_back(std::move(room));
        }
        m_rooms = std::move(freshRooms);
        rebuild();
    });
}

void RoomBrowserPopup::rebuild() {
    if (!m_body) return;
    m_body->removeAllChildren();
    auto center = m_mainLayer->getContentSize() / 2.f;

    auto* serverLabel = makeLabel(P2PManager::getSignalingUrl().c_str(), 0.48f, {center.width - 32.f, 255.f}, m_body);
    serverLabel->setColor({160, 160, 160});

    auto* menu = CCMenu::create();
    menu->setPosition({0.f, 0.f});
    m_body->addChild(menu);

    auto* refresh = makeButton("Refresh", this, menu_selector(RoomBrowserPopup::onRefresh), 82.f, "GJ_button_04.png");
    refresh->setPosition({center.width + 155.f, 255.f});
    menu->addChild(refresh);

    if (m_rooms.empty()) {
        auto* empty = makeLabel("No public rooms on this signaling server", 0.42f, {center.width, center.height}, m_body);
        empty->setColor({190, 190, 190});
        return;
    }

    constexpr std::size_t perPage = 5;
    std::size_t maxPage = (m_rooms.size() - 1) / perPage;
    if (m_page > maxPage) m_page = maxPage;
    std::size_t begin = m_page * perPage;
    std::size_t end = std::min(begin + perPage, m_rooms.size());

    float y = 220.f;
    for (std::size_t i = begin; i < end; ++i, y -= 39.f) {
        auto const& room = m_rooms[i];
        auto* bg = extension::CCScale9Sprite::create("square02_small.png");
        bg->setContentSize({382.f, 34.f});
        bg->setPosition({center.width, y});
        bg->setOpacity(90);
        m_body->addChild(bg);

        std::string title = room.hasPassword ? "[LOCK] " + room.roomName : room.roomName;
        auto* titleLabel = makeLabel(title.c_str(), 0.38f, {48.f, y + 7.f}, m_body);
        titleLabel->setAnchorPoint({0.f, 0.5f});

        auto details = fmt::format("{}  {}/{}  {}", room.hostName, room.playerCount, room.playerLimit, room.transportMode);
        auto* detailsLabel = makeLabel(details.c_str(), 0.34f, {48.f, y - 8.f}, m_body);
        detailsLabel->setAnchorPoint({0.f, 0.5f});
        detailsLabel->setColor({175, 175, 175});

        auto* join = makeButton("Join", this, menu_selector(RoomBrowserPopup::onJoin), 64.f);
        join->setTag(static_cast<int>(i));
        join->setPosition({center.width + 150.f, y});
        menu->addChild(join);
    }

    auto pageText = fmt::format("Page {}/{}", m_page + 1, maxPage + 1);
    makeLabel(pageText.c_str(), 0.42f, {center.width, 32.f}, m_body);

    if (m_page > 0) {
        auto* prev = makeButton("<", this, menu_selector(RoomBrowserPopup::onPrev), 42.f, "GJ_button_04.png");
        prev->setPosition({center.width - 70.f, 32.f});
        menu->addChild(prev);
    }
    if (m_page < maxPage) {
        auto* next = makeButton(">", this, menu_selector(RoomBrowserPopup::onNext), 42.f, "GJ_button_04.png");
        next->setPosition({center.width + 70.f, 32.f});
        menu->addChild(next);
    }
}

void RoomBrowserPopup::onRefresh(CCObject*) {
    fetchRooms();
}

void RoomBrowserPopup::onJoin(CCObject* sender) {
    auto* node = typeinfo_cast<CCNode*>(sender);
    if (!node || !m_owner) return;
    int index = node->getTag();
    if (index < 0 || static_cast<std::size_t>(index) >= m_rooms.size()) return;
    auto room = m_rooms[static_cast<std::size_t>(index)];
    if (room.playerCount >= room.playerLimit) {
        Notification::create("Room is full", NotificationIcon::Error)->show();
        return;
    }
    if (room.hasPassword) {
        auto* owner = m_owner;
        auto code = room.roomCode;
        auto name = room.roomName;
        this->onClose(nullptr);
        if (auto* popup = PasswordPopup::create(owner, std::move(code), std::move(name))) {
            popup->show();
        }
    } else {
        auto* owner = m_owner;
        auto code = room.roomCode;
        this->onClose(nullptr);
        owner->beginJoin(code, "");
    }
}

void RoomBrowserPopup::onPrev(CCObject*) {
    if (m_page > 0) --m_page;
    rebuild();
}

void RoomBrowserPopup::onNext(CCObject*) {
    constexpr std::size_t perPage = 5;
    if ((m_page + 1) * perPage < m_rooms.size()) ++m_page;
    rebuild();
}

} // namespace mpedit
