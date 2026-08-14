#pragma once
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
