#include "SessionManager.hpp"
#include "P2PManager.hpp"
#include "RemoteActionHandler.hpp"
#include "BinaryProtocol.hpp"
#include "ui/CursorNode.hpp"
#include <Geode/loader/Log.hpp>
#include <Geode/loader/Mod.hpp>
#include <Geode/Geode.hpp>
#include <Geode/ui/Notification.hpp>

using namespace geode::prelude;

namespace mpedit {

    SessionManager& SessionManager::get() {
        static SessionManager instance;
        return instance;
    }

    void SessionManager::hostSession(
        std::string const& playerName,
        std::string const& roomName,
        std::string const& description,
        int playerLimit,
        bool isPrivate,
        std::string const& password
    ) {
        if (isInSession()) {
            log::warn("SessionManager: Already in a session");
            return;
        }

        m_localPlayerName = playerName;
        m_role = Role::Host;

        setupNetworkHandlers();
        P2PManager::get().hostSession(playerName, roomName, description, playerLimit, isPrivate, password);

        log::info("SessionManager: Hosting session as '{}'", playerName);
    }

    void SessionManager::joinSession(
        std::string const& roomCode,
        std::string const& playerName,
        std::string const& password
    ) {
        if (isInSession()) {
            log::warn("SessionManager: Already in a session");
            return;
        }

        m_localPlayerName = playerName;
        m_roomCode = roomCode;
        m_role = Role::Client;

        setupNetworkHandlers();
        P2PManager::get().joinSession(roomCode, playerName, password);

        log::info("SessionManager: Joining room '{}' as '{}'", roomCode, playerName);
    }

    void SessionManager::leaveSession() {
        if (!isInSession()) return;

        // The editor pause layer can suspend scheduled updates. Do not wait for
        // CursorNode::update() to notice Role::None: remove remote cursors and
        // playtest icons synchronously while the scene is still alive.
        if (auto* editor = LevelEditorLayer::get()) {
            if (editor->m_objectLayer) {
                if (auto* cursor = typeinfo_cast<CursorNode*>(editor->m_objectLayer->getChildByID("cursor-node"_spr))) {
                    cursor->clearRemoteVisuals();
                }
            }
        }

        P2PManager::get().leaveSession();
        RemoteActionHandler::get().clearMappings();
        
        auto sessionEndedCallbacks = m_onSessionEnded;
        clearNetworkHandlers();

        m_role = Role::None;
        m_roomCode.clear();
        m_localPlayerId = -1;
        m_players.clear();

        for (auto& cb : sessionEndedCallbacks) {
            cb();
        }

        log::info("SessionManager: Left session");
    }

    bool SessionManager::isInSession() const {
        return m_role != Role::None;
    }

    SessionManager::Role SessionManager::getRole() const {
        return m_role;
    }

    std::string SessionManager::getRoomCode() const {
        return m_roomCode;
    }

    int SessionManager::getLocalPlayerId() const {
        return m_localPlayerId;
    }

    std::string SessionManager::getLocalPlayerName() const {
        return m_localPlayerName;
    }

    std::vector<PlayerInfo> const& SessionManager::getPlayers() const {
        return m_players;
    }

    PlayerInfo const* SessionManager::getPlayer(int id) const {
        for (auto& p : m_players) {
            if (p.id == id) return &p;
        }
        return nullptr;
    }

    void SessionManager::updatePlayerCursor(int playerId, float x, float y, std::string const& status) {
        for (auto& p : m_players) {
            if (p.id == playerId) {
                p.cursorX = x;
                p.cursorY = y;
                p.status = status;
                return;
            }
        }
    }

    void SessionManager::onSessionStarted(SessionCallback cb) {
        m_onSessionStarted.push_back(std::move(cb));
    }

    void SessionManager::onSessionEnded(SessionCallback cb) {
        m_onSessionEnded.push_back(std::move(cb));
    }

    void SessionManager::onPlayerJoined(PlayerCallback cb) {
        m_onPlayerJoined.push_back(std::move(cb));
    }

    void SessionManager::onPlayerLeft(PlayerCallback cb) {
        m_onPlayerLeft.push_back(std::move(cb));
    }

    void SessionManager::onError(ErrorCallback cb) {
        m_onError.push_back(std::move(cb));
    }

    void SessionManager::clearCallbacks() {
        m_onSessionStarted.clear();
        m_onSessionEnded.clear();
        m_onPlayerJoined.clear();
        m_onPlayerLeft.clear();
        m_onError.clear();
    }

    void SessionManager::clearPopupCallbacks() {
        m_onSessionStarted.clear();
        m_onError.clear();
        m_onPlayerJoined.clear();
        m_onPlayerLeft.clear();
    }

    void SessionManager::setupNetworkHandlers() {
        auto& net = P2PManager::get();
        RemoteActionHandler::get().setupHandlers();

        net.onSessionStarted([this](std::string const& roomCode, int localPlayerId) {
            m_roomCode = roomCode;
            m_localPlayerId = localPlayerId;
            m_role = (localPlayerId == 0) ? Role::Host : Role::Client;

            m_players.clear();
            PlayerInfo self;
            self.id = localPlayerId;
            self.name = m_localPlayerName;
            self.colorIndex = (localPlayerId == 0) ? 0 : (localPlayerId % 6);
            m_players.push_back(self);

            auto callbacks = m_onSessionStarted;
            for (auto& cb : callbacks) cb();
        });

        net.onPeerConnected([this](int playerId, std::string const& name, int colorIndex) {
            // Check if player already exists
            for (auto& p : m_players) {
                if (p.id == playerId) {
                    p.name = name;
                    p.colorIndex = colorIndex;
                    return;
                }
            }

            PlayerInfo info;
            info.id = playerId;
            info.name = name;
            info.colorIndex = colorIndex;
            m_players.push_back(info);

            auto callbacks = m_onPlayerJoined;
            for (auto& cb : callbacks) cb(info);
        });

        net.onPeerDisconnected([this](int playerId) {
            PlayerInfo leftPlayer;
            for (auto it = m_players.begin(); it != m_players.end(); ++it) {
                if (it->id == playerId) {
                    leftPlayer = *it;
                    m_players.erase(it);
                    break;
                }
            }

            auto callbacks = m_onPlayerLeft;
            for (auto& cb : callbacks) cb(leftPlayer);
        });

        net.onError([this](std::string const& error) {
            auto role = m_role;
            auto callbacks = m_onError;
            leaveSession();

            for (auto& cb : callbacks) {
                cb(error);
            }

            if (role == Role::Client) {
                geode::queueInMainThread([error]() {
                    if (auto* editor = LevelEditorLayer::get()) {
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

                            geode::Notification::create(error, geode::NotificationIcon::Error)->show();
                        }
                    }
                });
            }
        });

        net.on(proto::Opcode::CursorUpdate, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeCursorUpdate(reader);
            updatePlayerCursor(playerId, msg.x, msg.y, msg.status);
        });

        net.on(proto::Opcode::RoomInfo, [this](int playerId, proto::Reader& reader) {
            auto msg = proto::deserializeRoomInfo(reader);
            PlayerInfo self;
            for (auto const& p : m_players) {
                if (p.id == m_localPlayerId) {
                    self = p;
                    break;
                }
            }
            m_players.clear();
            m_players.push_back(self);

            for (auto const& p : msg.players) {
                if (p.id == m_localPlayerId) continue;
                
                bool exists = false;
                for (auto& existing : m_players) {
                    if (existing.id == p.id) {
                        exists = true;
                        break;
                    }
                }
                
                if (!exists) {
                    PlayerInfo info;
                    info.id = p.id;
                    info.name = p.name;
                    info.colorIndex = p.colorIndex;
                    m_players.push_back(info);
                }
            }
        });
    }

    void SessionManager::clearNetworkHandlers() {
        P2PManager::get().clearHandlers();
        RemoteActionHandler::get().clearHandlers();
        m_onSessionStarted.clear();
        m_onSessionEnded.clear();
        m_onPlayerJoined.clear();
        m_onPlayerLeft.clear();
        m_onError.clear();
    }

} // namespace mpedit
