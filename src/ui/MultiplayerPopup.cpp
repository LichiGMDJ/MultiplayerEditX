#include "MultiplayerPopup.hpp"
#include "UpdateHelperNode.hpp"
#include "RoomSettingsPopup.hpp"
#include "RoomDiscoveryPopups.hpp"
#include "../SessionManager.hpp"
#include "../P2PManager.hpp"
#include <Geode/Geode.hpp>
#include <Geode/ui/Notification.hpp>

using namespace geode::prelude;

namespace mpedit {

    MultiplayerPopup* MultiplayerPopup::create() {
        auto* ret = new MultiplayerPopup();
        if (ret->init(340.f, 260.f) && ret->setup()) {
            ret->autorelease();
            return ret;
        }
        delete ret;
        return nullptr;
    }

    MultiplayerPopup::~MultiplayerPopup() {
        auto& session = SessionManager::get();
        if (session.isInSession() && session.getRole() == SessionManager::Role::Client && !LevelEditorLayer::get()) {
            log::info("MultiplayerPopup: Leaving session because popup was closed during sync");
            session.leaveSession();
        }

        SessionManager::get().clearPopupCallbacks();
        if (s_instance == this) s_instance = nullptr;
    }

    bool MultiplayerPopup::setup() {
        s_instance = this;
        this->setTitle("Multiplayer Edit", "goldFont.fnt", 0.8f, 20.f);

        m_contentNode = cocos2d::CCNode::create();
        m_mainLayer->addChild(m_contentNode);

        auto* helper = UpdateHelperNode::create([this](float dt) {
            this->pollNetwork(dt);
        }, 0.05f);
        if (helper) {
            this->addChild(helper);
        }

        auto& session = SessionManager::get();
        
        session.onPlayerJoined([this](PlayerInfo const&) {
            if (SessionManager::get().isInSession() && !this->m_statusLabel) {
                this->clearContentNode();
                this->createSessionView();
            }
        });

        session.onPlayerLeft([this](PlayerInfo const&) {
            if (SessionManager::get().isInSession() && !this->m_statusLabel) {
                this->clearContentNode();
                this->createSessionView();
            }
        });

        if (session.isInSession()) {
            createSessionView();
        } else {
            createConnectView();
        }

        return true;
    }

    void MultiplayerPopup::createConnectView() {
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

    void MultiplayerPopup::createSessionView() {
        auto center = m_mainLayer->getContentSize() / 2.f;
        auto& session = SessionManager::get();

        auto* bg = cocos2d::extension::CCScale9Sprite::create("square02b_001.png");
        bg->setContentSize({300.f, 150.f});
        bg->setPosition({center.width, center.height - 10.f});
        bg->setColor({0, 0, 0});
        bg->setOpacity(100);
        m_contentNode->addChild(bg);

        // Room code display
        auto* codeTitle = CCLabelBMFont::create("Room Code:", "bigFont.fnt");
        codeTitle->setScale(0.45f);
        codeTitle->setPosition({center.width, center.height + 60.f});
        codeTitle->setID("code-title-label"_spr);
        m_contentNode->addChild(codeTitle);

        auto codeStr = session.getRoomCode();
        m_roomCodeLabel = CCLabelBMFont::create(codeStr.c_str(), "goldFont.fnt");
        m_roomCodeLabel->setScale(0.8f);
        m_roomCodeLabel->setPosition({center.width, center.height + 35.f});
        m_roomCodeLabel->setID("room-code-display"_spr);
        m_contentNode->addChild(m_roomCodeLabel);

        // Role display
        auto roleStr = session.getRole() == SessionManager::Role::Host ? "You are the Host" : "You are a Guest";
        auto* roleLabel = CCLabelBMFont::create(roleStr, "bigFont.fnt");
        roleLabel->setScale(0.35f);
        roleLabel->setPosition({center.width, center.height + 10.f});
        roleLabel->setColor({180, 255, 180});
        roleLabel->setID("role-label"_spr);
        m_contentNode->addChild(roleLabel);

        // Player count
        auto playerCountStr = fmt::format("Players: {}", session.getPlayers().size());
        auto* playerCountLabel = CCLabelBMFont::create(playerCountStr.c_str(), "bigFont.fnt");
        playerCountLabel->setScale(0.35f);
        playerCountLabel->setPosition({center.width, center.height - 10.f});
        playerCountLabel->setID("player-count-label"_spr);
        m_contentNode->addChild(playerCountLabel);

        // Player list
        static const std::array<ccColor3B, 6> colors = {
            ccColor3B{100, 200, 255},
            ccColor3B{255, 120, 100},
            ccColor3B{100, 255, 150},
            ccColor3B{255, 200, 100},
            ccColor3B{200, 150, 255},
            ccColor3B{255, 150, 200},
        };

        float yOffset = center.height - 30.f;
        for (auto& player : session.getPlayers()) {
            auto* label = CCLabelBMFont::create(player.name.c_str(), "chatFont.fnt");
            label->setScale(0.5f);
            label->setPosition({center.width, yOffset});
            label->setColor(colors[player.colorIndex % colors.size()]);
            m_contentNode->addChild(label);

            if (
                session.getRole() == SessionManager::Role::Host &&
                player.id != session.getLocalPlayerId()
            ) {
                auto* kickMenu = CCMenu::create();
                kickMenu->setPosition({0.f, 0.f});
                auto* kickSprite = ButtonSprite::create(
                    "X", 28, true, "bigFont.fnt", "GJ_button_06.png", 18.f, 0.5f
                );
                auto* kickButton = CCMenuItemSpriteExtra::create(
                    kickSprite, this, menu_selector(MultiplayerPopup::onKick)
                );
                kickButton->setTag(player.id);
                kickButton->setPosition({center.width + 105.f, yOffset});
                kickMenu->addChild(kickButton);
                m_contentNode->addChild(kickMenu);
            }

            yOffset -= 18.f;
        }

        // Session menu
        m_sessionMenu = CCMenu::create();
        m_sessionMenu->setPosition({0, 0});
        m_sessionMenu->setID("session-menu"_spr);

        // Copy code button
        auto* copySprite = ButtonSprite::create(
            "Copy Code", 100, true, "bigFont.fnt", "GJ_button_04.png", 30.f, 0.6f
        );
        auto* copyBtn = CCMenuItemSpriteExtra::create(
            copySprite, this, menu_selector(MultiplayerPopup::onCopyCode)
        );
        copyBtn->setPosition({center.width - 60.f, 40.f});
        copyBtn->setID("copy-button"_spr);
        m_sessionMenu->addChild(copyBtn);

        if (session.getRole() == SessionManager::Role::Host) {
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
        auto* leaveSprite = ButtonSprite::create(
            "Leave", 100, true, "bigFont.fnt", "GJ_button_06.png", 30.f, 0.6f
        );
        auto* leaveBtn = CCMenuItemSpriteExtra::create(
            leaveSprite, this, menu_selector(MultiplayerPopup::onLeave)
        );
        leaveBtn->setPosition({center.width + 60.f, 40.f});
        leaveBtn->setID("leave-button"_spr);
        m_sessionMenu->addChild(leaveBtn);

        m_contentNode->addChild(m_sessionMenu);
    }
 
    void MultiplayerPopup::clearContentNode() {
        m_contentNode->removeAllChildren();
        m_roomCodeInput = nullptr;
        m_statusLabel = nullptr;
        m_roomCodeLabel = nullptr;
        m_connectMenu = nullptr;
        m_sessionMenu = nullptr;
    }

    void MultiplayerPopup::createLoadingView(std::string const& statusText) {
        this->clearContentNode();

        auto center = m_mainLayer->getContentSize() / 2.f;

        // Translucent dark background card
        auto* bg = cocos2d::extension::CCScale9Sprite::create("square02b_001.png");
        bg->setContentSize({300.f, 150.f});
        bg->setPosition({center.width, center.height - 10.f});
        bg->setColor({10, 15, 28});
        bg->setOpacity(180);
        m_contentNode->addChild(bg);

        // Title: Synchronizing Level
        auto* titleLabel = CCLabelBMFont::create("Synchronizing Level", "goldFont.fnt");
        titleLabel->setScale(0.7f);
        titleLabel->setPosition({center.width, center.height + 40.f});
        titleLabel->setID("sync-title-label"_spr);
        m_contentNode->addChild(titleLabel);

        // Beautiful rotating native spinner
        auto* spinner = cocos2d::CCSprite::create("loadingCircle.png");
        if (spinner) {
            spinner->setScale(0.8f);
            spinner->setPosition({center.width, center.height + 10.f});
            spinner->runAction(cocos2d::CCRepeatForever::create(cocos2d::CCRotateBy::create(1.0f, 360.f)));
            spinner->setID("sync-spinner"_spr);
            m_contentNode->addChild(spinner);
        }

        // Status description
        m_statusLabel = CCLabelBMFont::create(statusText.c_str(), "chatFont.fnt");
        m_statusLabel->setScale(0.55f);
        m_statusLabel->setPosition({center.width, center.height - 45.f});
        m_statusLabel->setColor({200, 200, 200});
        m_statusLabel->setID("status-label"_spr);
        m_contentNode->addChild(m_statusLabel);

        // Cancel Menu and Button
        auto* cancelMenu = CCMenu::create();
        cancelMenu->setPosition({0, 0});
        cancelMenu->setID("cancel-menu"_spr);

        auto* cancelSprite = ButtonSprite::create(
            "Cancel", 100, true, "bigFont.fnt", "GJ_button_06.png", 30.f, 0.6f
        );
        auto* cancelBtn = CCMenuItemSpriteExtra::create(
            cancelSprite, this, menu_selector(MultiplayerPopup::onLeave)
        );
        cancelBtn->setPosition({center.width, 40.f});
        cancelBtn->setID("cancel-button"_spr);
        cancelMenu->addChild(cancelBtn);

        m_contentNode->addChild(cancelMenu);
    }

    void MultiplayerPopup::onHost(CCObject*) {
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
                fullError = fmt::format("{}

Network: {}", error, net.getError());
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
                fullError = fmt::format("{}

Network: {}", error, net.getError());
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

    void MultiplayerPopup::onLeave(CCObject*) {
        m_connectionPending = false;
        m_connectionElapsed = 0.f;
        m_lastConnectionStage = -1;
        auto& session = SessionManager::get();
        auto role = session.getRole();
        session.leaveSession();
        session.clearCallbacks();
        
        this->clearContentNode();
        createConnectView();

        Notification::create("Left session", NotificationIcon::Info)->show();

        // If client/guest left the lobby while inside the editor, close the level and exit
        if (role == SessionManager::Role::Client) {
            auto* director = cocos2d::CCDirector::sharedDirector();
            if (auto* runningScene = director->getRunningScene()) {
                std::function<EditorPauseLayer*(cocos2d::CCNode*)> findPauseLayer = [&](cocos2d::CCNode* parent) -> EditorPauseLayer* {
                    if (!parent) return nullptr;
                    if (auto* pause = typeinfo_cast<EditorPauseLayer*>(parent)) {
                        return pause;
                    }
                    if (parent->getChildren()) {
                        for (auto* child : CCArrayExt<CCNode*>(parent->getChildren())) {
                            if (auto* p = findPauseLayer(child)) return p;
                        }
                    }
                    return nullptr;
                };

                auto* pauseLayer = findPauseLayer(runningScene);
                if (pauseLayer) {
                    auto* dummySender = cocos2d::CCNode::create();
                    pauseLayer->onExitEditor(dummySender);
                } else {
                    director->popScene();
                }
            }
        }
    }

    void MultiplayerPopup::onCopyCode(CCObject*) {
        auto code = SessionManager::get().getRoomCode();
        utils::clipboard::write(code);
        Notification::create("Room code copied!", NotificationIcon::Success)->show();
    }

    void MultiplayerPopup::onRoomSettings(CCObject*) {
        if (SessionManager::get().getRole() != SessionManager::Role::Host) return;
        RoomSettingsPopup::create()->show();
    }

    void MultiplayerPopup::onKick(CCObject* sender) {
        if (SessionManager::get().getRole() != SessionManager::Role::Host || !sender) return;
        auto* node = typeinfo_cast<CCNode*>(sender);
        if (!node) return;
        int playerId = node->getTag();
        if (playerId <= 0) return;
        P2PManager::get().kickPlayer(playerId);
        Notification::create("Player kicked", NotificationIcon::Info)->show();
    }


    void MultiplayerPopup::pollNetwork(float dt) {
        auto& net = P2PManager::get();

        // dispatchMessages() can synchronously invoke callbacks that rebuild or
        // close this popup. Therefore all optional UI access must happen before
        // dispatch, and dispatch must be the final operation in this timer tick.
        if (!m_connectionPending || !m_statusLabel) {
            net.dispatchMessages();
            return;
        }

        m_connectionElapsed += dt;
        auto state = net.getState();
        auto& session = SessionManager::get();

        std::string text;
        cocos2d::ccColor3B color = {255, 255, 100};
        int stage = m_lastConnectionStage;

        if (state == P2PManager::State::Error) {
            text = net.getError().empty()
                ? "Connection failed: unknown network error"
                : "Connection failed: " + net.getError();
            color = {255, 100, 100};
            stage = 99;
            m_connectionPending = false;
        } else if (state == P2PManager::State::Reconnecting) {
            text = "Reconnecting: signaling / ICE negotiation...";
            stage = 5;
        } else if (session.getLocalPlayerId() < 0) {
            text = "Stage 1/4: Signaling - joining room...";
            stage = 1;
        } else if (state == P2PManager::State::Connecting) {
            text = "Stage 2/4: WebRTC - ICE / STUN / TURN negotiation...";
            stage = 2;
        } else if (state == P2PManager::State::Connected) {
            // Once WebRTC reports Connected, both data channels / protocol
            // bootstrap are the remaining path before the authoritative level
            // snapshot opens the editor and closes this loading popup.
            text = "Stage 3/4: P2P connected - waiting for level sync...";
            color = {140, 255, 140};
            stage = 3;
        } else if (state == P2PManager::State::Disconnected) {
            text = "Disconnected while joining room";
            color = {255, 100, 100};
            stage = 98;
        }

        if (m_connectionElapsed >= 20.f &&
            (state == P2PManager::State::Connecting || state == P2PManager::State::Reconnecting)) {
            text += "\nTaking unusually long - check TURN password / network";
            color = {255, 190, 90};
        }

        if (stage != m_lastConnectionStage || m_connectionElapsed >= 20.f) {
            log::info(
                "MultiplayerPopup: connection diagnostic stage={} elapsed={:.1f}s state={}",
                stage,
                m_connectionElapsed,
                static_cast<int>(state)
            );
            m_lastConnectionStage = stage;
        }

        m_statusLabel->setString(text.c_str());
        m_statusLabel->setColor(color);
        m_statusLabel->setScale(text.find('\n') == std::string::npos ? 0.55f : 0.44f);

        // Must remain last. A callback reached from here may destroy the popup.
        net.dispatchMessages();
    }

} // namespace mpedit
