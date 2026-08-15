#pragma once

#include <cocos2d.h>
#include <unordered_map>
#include "../SessionManager.hpp"

class SimplePlayer;

namespace mpedit {

    class CursorNode : public cocos2d::CCNode {
    protected:
        struct PlayerCursor {
            cocos2d::CCDrawNode* drawNode = nullptr;
            cocos2d::CCLabelBMFont* label = nullptr;
            cocos2d::CCNode* toolIndicator = nullptr;
            SimplePlayer* playtestIcon = nullptr;
            SimplePlayer* playtestIcon2 = nullptr; // For dual mode
            std::string lastStatus;
            float targetX = 0.f;
            float targetY = 0.f;
            float target2X = 0.f; // Dual player X
            float target2Y = 0.f; // Dual player Y
        };

        std::unordered_map<int, PlayerCursor> m_cursors;
        cocos2d::CCDrawNode* m_selectionDrawNode = nullptr;

        bool init() override;
        void update(float dt) override;

    public:
        static CursorNode* create();

        // Remove every remote visual immediately. This is intentionally public
        // so SessionManager can clean the editor even while the pause layer has
        // suspended CursorNode::update().
        void clearRemoteVisuals();
        
        static cocos2d::ccColor3B getColorForIndex(int index);
    };

} 

