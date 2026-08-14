#pragma once

#include <Geode/ui/Popup.hpp>
#include <Geode/ui/TextInput.hpp>

namespace mpedit {

    class MultiplayerPopup : public geode::Popup {
    protected:
        geode::TextInput* m_roomCodeInput = nullptr;
        cocos2d::CCLabelBMFont* m_statusLabel = nullptr;
        cocos2d::CCLabelBMFont* m_roomCodeLabel = nullptr;
        cocos2d::CCMenu* m_connectMenu = nullptr;
        cocos2d::CCMenu* m_sessionMenu = nullptr;
        cocos2d::CCNode* m_contentNode = nullptr;

        // v0.5.2 connection diagnostics. This is UI-only state and does not
        // affect signaling/WebRTC behavior or the wire protocol.
        bool m_connectionPending = false;
        float m_connectionElapsed = 0.f;
        int m_lastConnectionStage = -1;

        ~MultiplayerPopup();

        bool setup();

        void createConnectView();
        void createSessionView();
        void createLoadingView(std::string const& statusText);
        void clearContentNode();

        void onHost(cocos2d::CCObject*);
        void onJoin(cocos2d::CCObject*);
        void onLeave(cocos2d::CCObject*);
        void onCopyCode(cocos2d::CCObject*);
        void onKick(cocos2d::CCObject*);
        void onRoomSettings(cocos2d::CCObject*);
        void onPatreon(cocos2d::CCObject*);
        void pollNetwork(float dt);

    public:
        static inline MultiplayerPopup* s_instance = nullptr;
        static MultiplayerPopup* create();
        void forceClose() {
            this->onClose(nullptr);
        }
    };

} // namespace mpedit
