#pragma once

#include <Geode/ui/Popup.hpp>
#include <Geode/ui/TextInput.hpp>
#include <Geode/utils/async.hpp>
#include <Geode/utils/web.hpp>

#include <cstdint>
#include <string>
#include <vector>

namespace mpedit {

class MultiplayerPopup;

struct BrowserRoomInfo {
    std::string roomCode;
    std::string roomName;
    std::string description;
    std::string hostName;
    int playerCount = 1;
    int playerLimit = 8;
    bool hasPassword = false;
    std::string transportMode = "auto";
};

class CreateRoomPopup final : public geode::Popup {
public:
    static CreateRoomPopup* create(MultiplayerPopup* owner);

protected:
    MultiplayerPopup* m_owner = nullptr;
    geode::TextInput* m_nameInput = nullptr;
    geode::TextInput* m_descriptionInput = nullptr;
    geode::TextInput* m_limitInput = nullptr;
    geode::TextInput* m_passwordInput = nullptr;
    ButtonSprite* m_visibilitySprite = nullptr;
    bool m_private = false;

    bool setup();
    void onVisibility(cocos2d::CCObject*);
    void onCreate(cocos2d::CCObject*);
};

class PasswordPopup final : public geode::Popup {
public:
    static PasswordPopup* create(MultiplayerPopup* owner, std::string roomCode, std::string roomName);

protected:
    MultiplayerPopup* m_owner = nullptr;
    std::string m_roomCode;
    std::string m_roomName;
    geode::TextInput* m_passwordInput = nullptr;

    bool setup();
    void onJoin(cocos2d::CCObject*);
};

class PrivateRoomPopup final : public geode::Popup {
public:
    static PrivateRoomPopup* create(MultiplayerPopup* owner);

protected:
    MultiplayerPopup* m_owner = nullptr;
    geode::TextInput* m_codeInput = nullptr;
    geode::TextInput* m_passwordInput = nullptr;

    bool setup();
    void onJoin(cocos2d::CCObject*);
};

class RoomBrowserPopup final : public geode::Popup {
public:
    static RoomBrowserPopup* create(MultiplayerPopup* owner);

protected:
    MultiplayerPopup* m_owner = nullptr;
    cocos2d::CCNode* m_body = nullptr;
    cocos2d::CCLabelBMFont* m_statusLabel = nullptr;
    std::vector<BrowserRoomInfo> m_rooms;
    std::size_t m_page = 0;
    geode::async::TaskHolder<geode::utils::web::WebResponse> m_request;

    bool setup();
    void fetchRooms();
    void rebuild();
    void onRefresh(cocos2d::CCObject*);
    void onJoin(cocos2d::CCObject*);
    void onPrev(cocos2d::CCObject*);
    void onNext(cocos2d::CCObject*);
};

} // namespace mpedit
