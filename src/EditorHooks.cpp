#include <Geode/Geode.hpp>
#include <Geode/modify/EditorPauseLayer.hpp>
#include <Geode/modify/LevelEditorLayer.hpp>
#include <Geode/modify/EditorUI.hpp>
#include <Geode/modify/LevelBrowserLayer.hpp>
#include <Geode/modify/GJBaseGameLayer.hpp>
#include <Geode/binding/TeleportPortalObject.hpp>
#include <Geode/utils/file.hpp>
#include <Geode/loader/Dirs.hpp>

#include "SessionManager.hpp"
#include "P2PManager.hpp"
#include "BinaryProtocol.hpp"
#include "MessageBatcher.hpp"
#include "ActionSerializer.hpp"
#include "RemoteActionHandler.hpp"
#include "ui/MultiplayerPopup.hpp"
#include "ui/SessionStatusNode.hpp"
#include "ui/CursorNode.hpp"
#include "ui/UpdateHelperNode.hpp"
#include "sync/AdaptiveSyncPolicy.hpp"
#include "sync/SyncMetrics.hpp"

using namespace geode::prelude;
using namespace mpedit;

namespace {
    int s_selectedObjectID = 1;
    bool s_inTransformSync = false;
    bool s_inBulkPasteSync = false;
    cocos2d::CCPoint s_lastTouchPos = {0.f, 0.f};
    bool s_isTouching = false;
    std::set<GameObject*> s_startPosObjects;
    std::unordered_map<GameObject*, std::string> s_startPosSaveStrings;

    constexpr char kEditorLayerTag[] = "#EL#";

    std::string encodeLayerTaggedUuid(std::string const& uuid, int layer1, int layer2) {
        return uuid + kEditorLayerTag + std::to_string(layer1)
            + kEditorLayerTag + std::to_string(layer2);
    }

    std::string objectLayerSyncState(GameObject* obj, LevelEditorLayer* editor) {
        if (!obj || !editor) return {};
        auto state = std::string(obj->getSaveString(editor));
        state += "|mpedit-editor-layers:" + std::to_string(obj->m_editorLayer)
            + ":" + std::to_string(obj->m_editorLayer2);
        return state;
    }
}

namespace mpedit {
    void updateStartPosCache(GameObject* obj) {
        if (!obj || obj->m_objectID != 31) return;
        // A StartPos may be created by a remote placement, targeted repair or
        // initial snapshot after LevelEditorLayer::init() seeded the cache.
        // Always register it before storing its full serialized state.
        s_startPosObjects.insert(obj);
        if (auto* editor = LevelEditorLayer::get()) {
            s_startPosSaveStrings[obj] = obj->getSaveString(editor);
        }
    }
}

// ============================================================
// EditorPauseLayer — Add "Multiplayer" button to pause menu
// ============================================================

class $modify(MPEditorPauseLayer, EditorPauseLayer) {
    bool init(LevelEditorLayer* editor) {
        if (!EditorPauseLayer::init(editor)) return false;

        // Create the multiplayer button
        auto* btnSprite = ButtonSprite::create(
            "Multiplayer Edit", 90, true, "bigFont.fnt", "GJ_button_01.png", 30.f, 0.45f
        );
        auto* btn = CCMenuItemSpriteExtra::create(
            btnSprite,
            this,
            menu_selector(MPEditorPauseLayer::onMultiplayer)
        );
        btn->setID("multiplayer-button"_spr);

        // Find the center button menu
        CCMenu* targetMenu = typeinfo_cast<CCMenu*>(this->getChildByID("center-button-menu"));
        
        if (!targetMenu) {
            // Fallback: look through all menus to find one with the most buttons (likely the center one)
            for (CCNode* child : this->getChildrenExt()) {
                if (auto* menu = typeinfo_cast<CCMenu*>(child)) {
                    if (menu->getChildrenCount() >= 4) {
                        targetMenu = menu;
                        break;
                    }
                }
            }
        }

        if (targetMenu) {
            targetMenu->addChild(btn);
            targetMenu->updateLayout();
        } else {
            // Fallback: create our own menu
            auto* fallbackMenu = CCMenu::create();
            fallbackMenu->setID("multiplayer-menu"_spr);
            fallbackMenu->setPosition({0, 0});
            
            auto winSize = CCDirector::sharedDirector()->getWinSize();
            btn->setPosition({winSize.width / 2.f, 40.f}); // Bottom center
            fallbackMenu->addChild(btn);
            this->addChild(fallbackMenu, 10);
        }

        auto& session = SessionManager::get();
        if (session.isInSession()) {
            auto disableBtn = [this](const char* id) {
                if (auto* btn = typeinfo_cast<CCMenuItemSpriteExtra*>(this->getChildByIDRecursive(id))) {
                    btn->setEnabled(false);
                    if (auto* sprite = typeinfo_cast<cocos2d::CCSprite*>(btn->getNormalImage())) {
                        sprite->setColor({100, 100, 100});
                    }
                }
            };

            auto disableBtnByText = [this](bool isSavePlay, bool isSaveExit) {
                std::function<CCMenuItemSpriteExtra*(CCNode*)> findBtn = [&](CCNode* node) -> CCMenuItemSpriteExtra* {
                    if (!node) return nullptr;
                    if (auto* item = typeinfo_cast<CCMenuItemSpriteExtra*>(node)) {
                        if (auto* normal = item->getNormalImage()) {
                            std::function<CCLabelBMFont*(CCNode*)> findLabel = [&](CCNode* n) -> CCLabelBMFont* {
                                if (auto* lbl = typeinfo_cast<CCLabelBMFont*>(n)) return lbl;
                                if (n->getChildren()) {
                                    for (auto* c : CCArrayExt<CCNode*>(n->getChildren())) {
                                        if (auto* l = findLabel(c)) return l;
                                    }
                                }
                                return nullptr;
                            };
                            if (auto* label = findLabel(normal)) {
                                std::string s = label->getString();
                                bool hasSave = s.find("Save") != std::string::npos;
                                bool hasPlay = s.find("Play") != std::string::npos;
                                bool hasExit = s.find("Exit") != std::string::npos;
                                
                                if (isSavePlay && hasSave && hasPlay) return item;
                                if (isSaveExit && hasSave && hasExit) return item;
                                if (!isSavePlay && !isSaveExit && hasSave && !hasPlay && !hasExit) return item;
                            }
                        }
                    }
                    if (node->getChildren()) {
                        for (auto* c : CCArrayExt<CCNode*>(node->getChildren())) {
                            if (auto* b = findBtn(c)) return b;
                        }
                    }
                    return nullptr;
                };

                if (auto* btn = findBtn(this)) {
                    btn->setEnabled(false);
                    std::function<void(CCNode*)> grayOut = [&](CCNode* n) {
                        if (auto* rgba = typeinfo_cast<cocos2d::CCNodeRGBA*>(n)) {
                            rgba->setColor({100, 100, 100});
                        }
                        if (n->getChildren()) {
                            for (auto* c : CCArrayExt<CCNode*>(n->getChildren())) {
                                grayOut(c);
                            }
                        }
                    };
                    grayOut(btn->getNormalImage());
                }
            };

            if (session.getRole() == SessionManager::Role::Host) {
                disableBtn("save-and-play-button");
                disableBtnByText(true, false);
            } else if (session.getRole() == SessionManager::Role::Client) {
                disableBtn("save-button");
                disableBtn("save-and-play-button");
                disableBtn("save-and-exit-button");
                
                disableBtnByText(false, false);
                disableBtnByText(true, false);
                disableBtnByText(false, true);
            }
        }

        return true;
    }

    void onMultiplayer(CCObject*) {
        MultiplayerPopup::create()->show();
    }

    void onSave(CCObject* sender) {
        if (SessionManager::get().isInSession() && SessionManager::get().getRole() == SessionManager::Role::Client) {
            Notification::create("Guests cannot save levels", NotificationIcon::Warning)->show();
            return;
        }
        EditorPauseLayer::onSave(sender);
    }

    void onSaveAndPlay(CCObject* sender) {
        if (SessionManager::get().isInSession()) {
            Notification::create("Cannot Save & Play in multiplayer", NotificationIcon::Warning)->show();
            return;
        }
        EditorPauseLayer::onSaveAndPlay(sender);
    }

    void onSaveAndExit(CCObject* sender) {
        auto& session = SessionManager::get();
        if (session.isInSession()) {
            if (session.getRole() == SessionManager::Role::Client) {
                Notification::create("Guests cannot save levels", NotificationIcon::Warning)->show();
                return;
            }
            session.leaveSession();
        }
        EditorPauseLayer::onSaveAndExit(sender);
    }

    void onExitEditor(CCObject* sender) {
        auto& session = SessionManager::get();
        if (session.isInSession()) {
            session.leaveSession();
        }
        EditorPauseLayer::onExitEditor(sender);
    }
};

// ============================================================
// LevelBrowserLayer — Add "Multiplayer" button to My Levels page
// ============================================================

class $modify(MPLevelBrowserLayer, LevelBrowserLayer) {
    bool init(GJSearchObject* object) {
        if (!LevelBrowserLayer::init(object)) return false;

        if (object->m_searchType != SearchType::MyLevels) return true;

        auto* btnSprite = ButtonSprite::create(
            "Multiplayer Edit", 90, true, "bigFont.fnt", "GJ_button_01.png", 30.f, 0.45f
        );
        auto* btn = CCMenuItemSpriteExtra::create(
            btnSprite,
            this,
            menu_selector(MPLevelBrowserLayer::onMultiplayer)
        );
        btn->setID("multiplayer-button"_spr);

        // Create a menu at the bottom center, underneath the level list
        auto* centerMenu = CCMenu::create();
        centerMenu->setID("multiplayer-menu"_spr);
        
        auto winSize = CCDirector::sharedDirector()->getWinSize();
        // Place it horizontally centered and near the bottom edge
        centerMenu->setPosition({winSize.width / 2.f, 35.f});
        
        btn->setPosition({0, 0});
        centerMenu->addChild(btn);
        
        this->addChild(centerMenu, 10);

        return true;
    }

    void onMultiplayer(CCObject*) {
        MultiplayerPopup::create()->show();
    }
};

// ============================================================
// LevelEditorLayer — Hook editor lifecycle for session management
// ============================================================

namespace {
    void sendChunkedSync(LevelEditorLayer* editor, int targetPlayerId) {
        auto& handler = RemoteActionHandler::get();

        std::string fullObjectsString;
        std::vector<std::string> allUuids;

        if (editor->m_objects) {
            int index = 0;
            for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
                if (!obj) continue;
                auto uuid = handler.getUUIDForObject(obj);
                if (uuid.empty()) {
                    uuid = "lvl_obj_" + std::to_string(index);
                    handler.registerObject(uuid, obj);
                }
                allUuids.push_back(encodeLayerTaggedUuid(uuid, obj->m_editorLayer, obj->m_editorLayer2));
                fullObjectsString += std::string(obj->getSaveString(editor)) + ";";
                index++;
            }
        }

        // Compress the full objects string using Geode's cross-platform zip via a temp file to ensure EOCD is written
        std::string compressedBytes = "";
        if (!fullObjectsString.empty()) {
            auto tempPath = geode::dirs::getTempDir() / "sync_level.zip";
            {
                if (auto zipRes = geode::utils::file::Zip::create(tempPath)) {
                    (void)zipRes.unwrap().add("level.txt", fullObjectsString);
                } else {
                    log::error("Failed to create temp zip for sync payload");
                }
            } // Zip goes out of scope, writing EOCD and closing

            if (auto dataRes = geode::utils::file::readBinary(tempPath)) {
                auto bytes = dataRes.unwrap();
                compressedBytes = std::string(bytes.begin(), bytes.end());
            } else {
                log::error("Failed to read compressed sync payload from temp file");
            }

            // Clean up temp file
            std::error_code ec;
            std::filesystem::remove(tempPath, ec);
        }

        // Leave headroom for opcode/index/vector/string framing so every
        // SyncLevelChunk stays below P2PManager's 24 KiB safe message target.
        constexpr size_t MAX_CHUNK_BYTES = 12000;
        constexpr size_t MAX_UUIDS_PER_CHUNK = 250;

        struct ChunkData {
            std::string objectsString; // Compressed bytes chunk
            std::vector<std::string> uuids;
        };
        std::vector<ChunkData> chunks;

        size_t byteOffset = 0;
        size_t uuidOffset = 0;

        while (byteOffset < compressedBytes.size() || uuidOffset < allUuids.size()) {
            ChunkData chunk;
            
            size_t bytesToTake = std::min(MAX_CHUNK_BYTES, compressedBytes.size() - byteOffset);
            if (bytesToTake > 0) {
                chunk.objectsString = compressedBytes.substr(byteOffset, bytesToTake);
                byteOffset += bytesToTake;
            }

            size_t uuidsToTake = std::min(MAX_UUIDS_PER_CHUNK, allUuids.size() - uuidOffset);
            if (uuidsToTake > 0) {
                chunk.uuids.insert(chunk.uuids.end(), allUuids.begin() + uuidOffset, allUuids.begin() + uuidOffset + uuidsToTake);
                uuidOffset += uuidsToTake;
            }

            chunks.push_back(std::move(chunk));
        }

        if (chunks.empty()) {
            chunks.push_back(ChunkData()); // Ensure at least 1 chunk for empty level
        }

        // Settings only: LevelSettingsObject::getSaveString() uses the ','
        // separator and carries colors (EffectManager), start mode, song, etc.
        ActionSerializer::LevelSettingsData settings;
        if (editor->m_levelSettings) {
            settings.saveString = editor->m_levelSettings->getSaveString();
        }
        if (editor->m_level) {
            settings.audioTrack = editor->m_level->m_audioTrack;
            settings.songID = editor->m_level->m_songID;
            settings.levelLength = editor->m_level->m_levelLength;
        }

        uint32_t totalChunks = static_cast<uint32_t>(chunks.size());
        uint32_t totalObjects = static_cast<uint32_t>(allUuids.size());
        sync::SyncMetrics::get().recordSerializedObjects(totalObjects);
        sync::SyncMetrics::get().recordOutboundBytes(compressedBytes.size());
        if (totalObjects >= sync::AdaptiveSyncPolicy::fullSnapshotWarningThreshold()) {
            log::warn("EditorHooks: large authoritative snapshot: {} objects, {} compressed bytes", totalObjects, compressedBytes.size());
        }

        // 4. Send SyncLevelStart
        auto startMsg = proto::serializeSyncLevelStart(totalChunks, totalObjects, settings);
        P2PManager::get().sendTo(targetPlayerId, startMsg, ChannelType::Reliable);

        auto* seqArr = cocos2d::CCArray::create();
        
        for (uint32_t i = 0; i < totalChunks; ++i) {
            auto chunkMsg = proto::serializeSyncLevelChunk(
                i, 
                reinterpret_cast<const uint8_t*>(chunks[i].objectsString.data()), 
                chunks[i].objectsString.size(),
                chunks[i].uuids
            );
            
            auto* callFunc = geode::cocos::CallFuncExt::create([targetPlayerId, chunkMsg]() {
                P2PManager::get().sendTo(targetPlayerId, chunkMsg, ChannelType::Reliable);
            });
            
            seqArr->addObject(cocos2d::CCDelayTime::create(0.01f));
            seqArr->addObject(callFunc);
        }

        // 6. Gather locks
        std::vector<ActionSerializer::LockData> locks;
        for (auto const& [uuid, lockInfo] : handler.getObjectLocks()) {
            locks.push_back({uuid, lockInfo.playerId, lockInfo.timeLeft});
        }

        auto* endFunc = geode::cocos::CallFuncExt::create([targetPlayerId, locks]() {
            auto endMsg = proto::serializeSyncLevelEnd(locks);
            P2PManager::get().sendTo(targetPlayerId, endMsg, ChannelType::Reliable);
        });
        
        seqArr->addObject(endFunc);
        
        editor->runAction(cocos2d::CCSequence::create(seqArr));
    }

    // Registers UUIDs onto the editor's currently-spawned objects, aligned by
    // index with the provided uuids list. Missing/extra objects get fresh
    // generated UUIDs. Returns once registration is consistent.
    void registerObjectsWithUuids(LevelEditorLayer* editor,
                                  std::vector<std::string> const& uuids) {
        if (!editor || !editor->m_objects) return;
        auto& handler = RemoteActionHandler::get();
        int index = 0;
        for (auto* obj : CCArrayExt<GameObject*>(editor->m_objects)) {
            if (!obj) continue;
            if (index < static_cast<int>(uuids.size()) && !uuids[index].empty()) {
                handler.registerObject(uuids[index], obj);
            } else {
                // Object count mismatch with host (rare): assign a deterministic fallback UUID.
                if (handler.getUUIDForObject(obj).empty()) {
                    handler.registerObject("lvl_obj_" + std::to_string(index), obj);
                }
            }
            index++;
        }
        if (index != static_cast<int>(uuids.size())) {
            log::warn("EditorHooks: object/uuid count mismatch on sync "
                      "(objects={}, uuids={})", index, uuids.size());
        }
    }
}

namespace mpedit {
    void sendFullLevelSyncTo(int targetPlayerId) {
        if (auto* editor = LevelEditorLayer::get()) {
            sendChunkedSync(editor, targetPlayerId);
        }
    }
}

class $modify(MPLevelEditorLayer, LevelEditorLayer) {
    struct Fields {
        float m_cursorSendTimer = 0.f;
        bool m_sessionActive = false;
        bool m_inUndoRedo = false;
        cocos2d::CCPoint m_lastSentLevelPos = {0.f, 0.f};
        bool m_wasPlaytesting = false;
        int m_lastHostSongID = 0;
        int m_lastHostAudioTrack = 0;
        bool m_musicBaselineReady = false;
        float m_externalCompatScanTimer = 0.f;
        float m_syncMetricsTimer = 0.f;
        std::unordered_set<std::string> m_externalCompatLiveUuids;
        float m_integrityCheckTimer = 0.f;
        bool m_forceIntegrityCheck = false;

        ~Fields() {
            auto& session = SessionManager::get();
            if (session.isInSession()) {
                session.leaveSession();
                log::info("EditorHooks: Left session automatically on editor destructor (Fields)");
            }
            session.clearCallbacks();
        }
    };

    void levelSettingsUpdated() {
        LevelEditorLayer::levelSettingsUpdated();

        auto& session = SessionManager::get();
        if (session.isInSession() && this->m_level) {
            int currentSong = this->m_level->m_songID;
            int currentTrack = this->m_level->m_audioTrack;
            if (!m_fields->m_musicBaselineReady) {
                m_fields->m_lastHostSongID = currentSong;
                m_fields->m_lastHostAudioTrack = currentTrack;
                m_fields->m_musicBaselineReady = true;
            } else if (session.getRole() == SessionManager::Role::Client &&
                       (currentSong != m_fields->m_lastHostSongID || currentTrack != m_fields->m_lastHostAudioTrack)) {
                // GD may start the newly selected song preview before this
                // callback fires. Stop that unauthorized preview first, then
                // restore the authoritative host metadata.
                if (auto* audio = FMODAudioEngine::sharedEngine()) {
                    audio->stopAllMusic(true);
                }
                this->m_level->m_songID = m_fields->m_lastHostSongID;
                this->m_level->m_audioTrack = m_fields->m_lastHostAudioTrack;
                Notification::create("Only the host can change music", NotificationIcon::Warning)->show();
                log::info("EditorHooks: blocked guest music change and stopped unauthorized preview");
                return;
            } else if (session.getRole() == SessionManager::Role::Host &&
                       (currentSong != m_fields->m_lastHostSongID || currentTrack != m_fields->m_lastHostAudioTrack)) {
                m_fields->m_lastHostSongID = currentSong;
                m_fields->m_lastHostAudioTrack = currentTrack;
                std::string title;
                if (currentSong > 0) {
                    if (auto* song = LevelTools::getSongObject(currentSong)) {
                        title = std::string(song->m_artistName.c_str()) + " - " + std::string(song->m_songName.c_str());
                    }
                    if (title.empty()) title = "Song ID " + std::to_string(currentSong);
                } else {
                    title = LevelTools::getAudioTitle(currentTrack);
                    if (title.empty()) title = "Official song " + std::to_string(currentTrack);
                }
                auto music = proto::serializeMusicChanged(currentSong, currentTrack, title);
                P2PManager::get().send(std::move(music), ChannelType::Reliable);
                log::info("EditorHooks: host changed music to {} (songID={}, audioTrack={})", title, currentSong, currentTrack);
            }
        }

        auto& handler = RemoteActionHandler::get();
        if (handler.isProcessingRemote() || !handler.isInitialSyncCompleted()) return;
        if (session.isInSession() && session.getRole() == SessionManager::Role::Client &&
            !P2PManager::get().getRoomSettings().allowLevelSettings) {
            Notification::create("Host disabled guest level settings", NotificationIcon::Warning)->show();
            return;
        }

        if (session.isInSession()) {
            ActionSerializer::LevelSettingsData settings;
            if (this->m_levelSettings) {
                settings.saveString = this->m_levelSettings->getSaveString();
            }
            if (this->m_level) {
                settings.audioTrack = this->m_level->m_audioTrack;
                settings.songID = this->m_level->m_songID;
                settings.levelLength = this->m_level->m_levelLength;
            }
            auto data = proto::serializeUpdateSettings(settings);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
            log::info("EditorHooks: Broadcasted update_settings");
        }
    }

    bool init(GJGameLevel* level, bool unk) {
        if (!LevelEditorLayer::init(level, unk)) return false;

        s_startPosObjects.clear();
        s_startPosSaveStrings.clear();
        if (this->m_objects) {
            for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {
                if (obj->m_objectID == 31) {
                    s_startPosObjects.insert(obj);
                    s_startPosSaveStrings[obj] = obj->getSaveString(this);
                }
            }
        }

        // Force construction of Fields immediately so its destructor runs reliably
        m_fields->m_sessionActive = SessionManager::get().isInSession();

        // Set up the remote action handler for this editor session
        auto& handler = RemoteActionHandler::get();
        handler.clearMappings();

        SessionManager::get().onSessionStarted([this]() {
            auto& session = SessionManager::get();
            m_fields->m_forceIntegrityCheck = true;
            if (this->m_objects) {
                auto& handler = RemoteActionHandler::get();
                int index = 0;
                for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {
                    if (obj && handler.getUUIDForObject(obj).empty()) {
                        auto uuid = "lvl_obj_" + std::to_string(index);
                        handler.registerObject(uuid, obj);
                    }
                    index++;
                }
            }
        });

        auto& session = SessionManager::get();
        if (session.isInSession()) {
            bool hasPending = handler.hasPendingSync();

            if (!hasPending) {
                auto const& expected = handler.getExpectedUuids();
                if (!expected.empty()) {
                    if (this->m_objects) {
                        registerObjectsWithUuids(this, expected);
                    }
                    handler.clearExpectedUuids();
                } else if (this->m_objects) {
                    int index = 0;
                    for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {
                        if (obj && handler.getUUIDForObject(obj).empty()) {
                            handler.registerObject("lvl_obj_" + std::to_string(index), obj);
                        }
                        index++;
                    }
                }
            } else {
                handler.clearExpectedUuids();
            }

            handler.setInitialSyncCompleted(true);

            m_fields->m_externalCompatLiveUuids.clear();
            if (this->m_objects) {
                for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {
                    if (!obj) continue;
                    auto uuid = handler.getUUIDForObject(obj);
                    if (!uuid.empty()) {
                        m_fields->m_externalCompatLiveUuids.insert(uuid);
                    }
                }
            }

            if (session.getRole() == SessionManager::Role::Host) {
                for (auto const& player : session.getPlayers()) {
                    if (player.id != session.getLocalPlayerId()) {
                        sendChunkedSync(this, player.id);
                        log::info("EditorHooks: Sent chunked sync_level to existing player {}", player.id);
                    }
                }
            }
        }

        // Initial level transfer is request-driven after ProtocolHello.
        // This avoids a first-join race between peer callbacks and bootstrap sync.


        if (handler.hasPendingSync()) {
            handler.setEditorForInit(this);
            handler.applyPendingSync();
            handler.setEditorForInit(nullptr);
        }

        auto* helper = UpdateHelperNode::create([this](float dt) {
            this->networkUpdate(dt);
        }, 0.05f);
        if (helper) {
            helper->setID("network-update-helper"_spr);
            this->addChild(helper);
        }

        // Add session status indicator
        auto* status = SessionStatusNode::create();
        status->setID("session-status"_spr);
        this->addChild(status, 1000);

        // Add cursor node to the object layer so it scales/pans correctly
        auto* cursorNode = CursorNode::create();
        cursorNode->setID("cursor-node"_spr);
        this->m_objectLayer->addChild(cursorNode, 999);

        return true;
    }

    void onExit() {
        LevelEditorLayer::onExit();
        
        auto& session = SessionManager::get();
        if (session.isInSession()) {
            if (session.getRole() == SessionManager::Role::Client) {
                // Prevent a guest-selected editor preview from leaking into the
                // normal Geometry Dash level/menu screens after leaving MP.
                if (auto* audio = FMODAudioEngine::sharedEngine()) {
                    audio->stopAllMusic(true);
                }
            }
            session.leaveSession();
            log::info("EditorHooks: Left session automatically on editor exit");
        }
        session.clearCallbacks();
        
        s_startPosObjects.clear();
        s_startPosSaveStrings.clear();
    }


    // Intercept object creation — UUID assignment and sync is handled by addToSection hook
    GameObject* createObject(int objectID, cocos2d::CCPoint position, bool noUndo) {
        auto& session = SessionManager::get();
        if (session.isInSession() && session.getRole() == SessionManager::Role::Client &&
            !RemoteActionHandler::get().isProcessingRemote() && !P2PManager::get().getRoomSettings().allowBuild) {
            Notification::create("Host disabled guest building", NotificationIcon::Warning)->show();
            return nullptr;
        }
        auto* obj = LevelEditorLayer::createObject(objectID, position, noUndo);
        // addToSection is called internally by LevelEditorLayer::createObject,
        // which handles UUID assignment and placement sync.
        // We do NOT sync here to avoid sending duplicate placement messages.
        return obj;
    }

    // Intercept object removal to sync deletion
    void removeObject(GameObject* obj, bool undo) {
        auto& permissionSession = SessionManager::get();
        if (obj && permissionSession.isInSession() && permissionSession.getRole() == SessionManager::Role::Client &&
            !RemoteActionHandler::get().isProcessingRemote() && !P2PManager::get().getRoomSettings().allowDelete) {
            Notification::create("Host disabled guest deletion", NotificationIcon::Warning)->show();
            return;
        }
        if (!obj) {
            LevelEditorLayer::removeObject(obj, undo);
            return;
        }

        if (obj->m_objectID == 31) {
            s_startPosObjects.erase(obj);
            s_startPosSaveStrings.erase(obj);
        }

        // Prevent premature deallocation during cleanup — the object may only be kept alive
        // by CCArrays (e.g., m_selectedObjects, m_touchingRings) that we're removing from.
        obj->retain();

        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

            // Clean up game state last activated portal references to prevent Use-After-Free crashes during playtesting/editing
            if (m_gameState.m_lastActivatedPortal1 == obj) {
                m_gameState.m_lastActivatedPortal1 = nullptr;
            }
            if (m_gameState.m_lastActivatedPortal2 == obj) {
                m_gameState.m_lastActivatedPortal2 = nullptr;
            }
            if (this->m_player1) {
                if (this->m_player1->m_lastActivatedPortal == obj) {
                    this->m_player1->m_lastActivatedPortal = nullptr;
                }
                if (this->m_player1->m_touchingRings && this->m_player1->m_touchingRings->containsObject(obj)) {
                    this->m_player1->m_touchingRings->removeObject(obj);
                }
            }
            if (this->m_player2) {
                if (this->m_player2->m_lastActivatedPortal == obj) {
                    this->m_player2->m_lastActivatedPortal = nullptr;
                }
                if (this->m_player2->m_touchingRings && this->m_player2->m_touchingRings->containsObject(obj)) {
                    this->m_player2->m_touchingRings->removeObject(obj);
                }
            }
            if (this->m_endPortal == obj) {
                this->m_endPortal = nullptr;
            }
            if (this->m_player1CollisionBlock == obj) {
                this->m_player1CollisionBlock = nullptr;
            }
            if (this->m_player2CollisionBlock == obj) {
                this->m_player2CollisionBlock = nullptr;
            }
            if (this->m_startPosObject == obj) {
                this->m_startPosObject = nullptr;
            }
            if (this->m_copyStateObject == obj) {
                this->m_copyStateObject = nullptr;
            }
            if (this->m_editorUI) {
                if (this->m_editorUI->m_selectedObject == obj) {
                    this->m_editorUI->m_selectedObject = nullptr;
                }
                if (this->m_editorUI->m_snapObject == obj) {
                    this->m_editorUI->m_snapObject = nullptr;
                }
                if (this->m_editorUI->m_selectedObjects && this->m_editorUI->m_selectedObjects->containsObject(obj)) {
                    this->m_editorUI->m_selectedObjects->removeObject(obj);
                }
            }

        bool inUndoRedo = m_fields->m_inUndoRedo;
        bool shouldBroadcastDelete = session.isInSession()
            && !handler.isProcessingRemote() && !inUndoRedo && obj;

        if (shouldBroadcastDelete) {
            auto uuid = handler.getUUIDForObject(obj);
            if (!uuid.empty()) {
                auto const& locks = handler.getObjectLocks();
                auto it = locks.find(uuid);
                if (it != locks.end() && it->second.playerId != session.getLocalPlayerId()) {
                    log::info("EditorHooks: Blocked removal of locked object (uuid={})", uuid);
                    obj->release();
                    return;
                }
                std::vector<std::string> uuids = {uuid};

                auto data = proto::serializeDeleteObjects(uuids);
                P2PManager::get().send(std::move(data), ChannelType::Reliable);
                handler.unregisterObject(uuid);
                log::debug("EditorHooks: Deleted object(s) (uuid={})", uuid);
            }
        }

        if (obj) {
            auto uuid = handler.getUUIDForObject(obj);
            if (!uuid.empty()) {
                handler.unregisterObject(uuid);
            }
            handler.getTrackedSelections().erase(obj);
        }

        LevelEditorLayer::removeObject(obj, undo);

        obj->release();
    }

    void handleAction(bool undo, cocos2d::CCArray* undoObjects) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (!session.isInSession() || handler.isProcessingRemote() || !undoObjects || undoObjects->count() == 0) {
            LevelEditorLayer::handleAction(undo, undoObjects);
            return;
        }

        std::unordered_set<GameObject*> affectedObjects;
        auto* lastItem = static_cast<UndoObject*>(undoObjects->lastObject());
        if (lastItem) {
            if (lastItem->m_objects) {
                for (auto* gObj : CCArrayExt<GameObject*>(lastItem->m_objects)) {
                    affectedObjects.insert(gObj);
                }
            }
            if (lastItem->m_objectCopy && lastItem->m_objectCopy->m_object) {
                affectedObjects.insert(lastItem->m_objectCopy->m_object);
            }
        }

        for (auto* gObj : affectedObjects) {
            if (!gObj) continue;
            auto uuid = handler.getUUIDForObject(gObj);
            if (!uuid.empty()) {
                auto const& locks = handler.getObjectLocks();
                auto it = locks.find(uuid);
                if (it != locks.end() && it->second.playerId != session.getLocalPlayerId()) {
                    log::info("EditorHooks: Blocked undo/redo of locked object");
                    return;
                }
            }
        }

        std::unordered_map<GameObject*, cocos2d::CCPoint> positionsBefore;
        std::unordered_map<GameObject*, std::string> saveStringsBefore;
        std::unordered_set<GameObject*> existedBefore;

        for (auto* obj : affectedObjects) {
            if (!obj) continue;
            if (this->m_objects && this->m_objects->containsObject(obj)) {
                existedBefore.insert(obj);
                positionsBefore[obj] = obj->getPosition();
                saveStringsBefore[obj] = objectLayerSyncState(obj, this);
            }
        }

        m_fields->m_inUndoRedo = true;
        LevelEditorLayer::handleAction(undo, undoObjects);

        std::vector<ActionSerializer::ObjectData> placedObjects;
        std::vector<std::string> deletedUuids;
        std::vector<ActionSerializer::MoveData> movedObjects;
        std::vector<ActionSerializer::ObjectData> updatedObjects;

        for (auto* obj : affectedObjects) {
            if (!obj) continue;
            
            bool existed_before = existedBefore.find(obj) != existedBefore.end();
            bool existed_after = this->m_objects && this->m_objects->containsObject(obj);
            
            if (existed_before && !existed_after) {
                std::string uuid = handler.getUUIDForObject(obj);
                if (!uuid.empty()) {
                    deletedUuids.push_back(uuid);
                    handler.unregisterObject(uuid);
                }
            } 
            else if (!existed_before && existed_after) {
                std::string uuid = handler.getUUIDForObject(obj);
                if (uuid.empty()) {
                    uuid = RemoteActionHandler::generateUUID();
                    handler.registerObject(uuid, obj);
                }
                placedObjects.push_back(ActionSerializer::extractObjectData(obj, uuid));
            } 
            else if (existed_before && existed_after) {
                std::string uuid = handler.getUUIDForObject(obj);
                if (uuid.empty()) {
                    uuid = RemoteActionHandler::generateUUID();
                    handler.registerObject(uuid, obj);
                }
                
                std::string currentSave = objectLayerSyncState(obj, this);
                if (saveStringsBefore[obj] != currentSave) {
                    updatedObjects.push_back(ActionSerializer::extractObjectData(obj, uuid));
                } else {
                    cocos2d::CCPoint oldPos = positionsBefore[obj];
                    float dx = obj->getPositionX() - oldPos.x;
                    float dy = obj->getPositionY() - oldPos.y;
                    if (dx != 0.f || dy != 0.f) {
                        ActionSerializer::MoveData md;
                        md.uuid = uuid;
                        md.dx = dx;
                        md.dy = dy;
                        movedObjects.push_back(md);
                    }
                }
            }
        }
        if (!placedObjects.empty()) {
            auto data = proto::serializePlaceObjects(placedObjects);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
            log::info("EditorHooks: Synced redo placement of {} objects", placedObjects.size());
        }
        if (!deletedUuids.empty()) {
            auto data = proto::serializeDeleteObjects(deletedUuids);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
            log::info("EditorHooks: Synced undo deletion of {} objects", deletedUuids.size());
        }
        if (!movedObjects.empty()) {
            auto data = proto::serializeMoveObjects(movedObjects);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
        }
        if (!updatedObjects.empty()) {
            auto data = proto::serializeUpdateObjects(updatedObjects);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
        }
        
        m_fields->m_inUndoRedo = false;
    }

    void networkUpdate(float dt) {
        auto& session = SessionManager::get();
        if (!session.isInSession()) return;

        auto& handler = RemoteActionHandler::get();
        bool isPlaytesting = this->m_playbackMode != PlaybackMode::Not;
        
        if (isPlaytesting && !m_fields->m_wasPlaytesting) {
            MessageBatcher::get().flush();
            handler.flushPendingPlacements();
            if (auto* ui = this->m_editorUI) {
                ui->deselectAll();
            }
        } else if (!isPlaytesting && m_fields->m_wasPlaytesting) {
            handler.flushPlaytestQueue();
        }
        m_fields->m_wasPlaytesting = isPlaytesting;

        // Dispatch queued network messages
        P2PManager::get().dispatchMessages();

        handler.updateLocks(dt);
        MessageBatcher::get().update(dt);

        // Flush any batched placements (copy/paste/duplicate) as a single message.
        handler.flushPendingPlacements();

        // v0.5.2 safety: a full snapshot received while playtesting is kept
        // pending. Applying it while PlayerObject is traversing collision objects
        // can invalidate CCNodes and crash inside collidedWithObjectInternal.
        if (
            this->m_playbackMode == PlaybackMode::Not &&
            handler.hasPendingSync() &&
            handler.isInitialSyncCompleted() &&
            !handler.isProcessingRemote()
        ) {
            log::info("EditorHooks: applying deferred SyncLevel after playtest ended");
            handler.applyPendingSync();
        }

        // Periodic integrity verification. The host is authoritative; clients
        // send a stable UUID/saveString digest and receive targeted repair only
        // when the state differs. Reconnect forces an immediate digest.
        m_fields->m_integrityCheckTimer += dt;
        std::size_t liveObjectCount = this->m_objects ? this->m_objects->count() : 0;
        float integrityInterval = sync::AdaptiveSyncPolicy::integrityIntervalSeconds(liveObjectCount);
        bool periodicIntegrityDue =
            sync::AdaptiveSyncPolicy::periodicIntegrityEnabled(liveObjectCount) &&
            m_fields->m_integrityCheckTimer >= integrityInterval;
        if (
            session.getRole() == SessionManager::Role::Client &&
            handler.isInitialSyncCompleted() &&
            !handler.isProcessingRemote() &&
            (m_fields->m_forceIntegrityCheck || periodicIntegrityDue)
        ) {
            m_fields->m_integrityCheckTimer = 0.f;
            m_fields->m_forceIntegrityCheck = false;
            handler.sendLevelDigestTo(0);
        }

        // Compatibility fallback for third-party editor mods (Layout Generator,
        // Object Workshop-style bulk tools, etc.) that may bypass create/remove hooks.
        m_fields->m_externalCompatScanTimer += dt;
        if (
            m_fields->m_externalCompatScanTimer >=
                sync::AdaptiveSyncPolicy::externalCompatibilityScanIntervalSeconds(liveObjectCount) &&
            !isPlaytesting &&
            handler.isInitialSyncCompleted() &&
            !handler.isProcessingRemote()
        ) {
            m_fields->m_externalCompatScanTimer = 0.f;

            std::unordered_set<std::string> currentUuids;
            std::vector<ActionSerializer::ObjectData> externalPlacements;
            std::vector<std::string> externalDeletes;

            if (this->m_objects) {
                currentUuids.reserve(this->m_objects->count());
                for (auto* obj : CCArrayExt<GameObject*>(this->m_objects)) {
                    if (!obj) continue;

                    auto uuid = handler.getUUIDForObject(obj);
                    if (uuid.empty()) {
                        uuid = RemoteActionHandler::generateUUID();
                        handler.registerObject(uuid, obj);
                        externalPlacements.push_back(ActionSerializer::extractObjectData(obj, uuid));
                    }

                    currentUuids.insert(uuid);
                }
            }

            for (auto const& uuid : m_fields->m_externalCompatLiveUuids) {
                if (currentUuids.contains(uuid)) continue;

                // If the mapping is already gone, our normal remove hook handled it.
                // If it still exists, a third-party mod removed the object behind us.
                if (handler.getObjectByUUID(uuid) != nullptr) {
                    externalDeletes.push_back(uuid);
                    handler.unregisterObject(uuid);
                }
            }

            if (!externalPlacements.empty()) {
                auto data = proto::serializePlaceObjects(externalPlacements);
                P2PManager::get().send(std::move(data), ChannelType::Reliable);
                log::info(
                    "EditorHooks: compatibility scan synced {} externally-created objects",
                    externalPlacements.size()
                );
            }

            if (!externalDeletes.empty()) {
                auto data = proto::serializeDeleteObjects(externalDeletes);
                P2PManager::get().send(std::move(data), ChannelType::Reliable);
                log::info(
                    "EditorHooks: compatibility scan synced {} externally-deleted objects",
                    externalDeletes.size()
                );
            }

            m_fields->m_externalCompatLiveUuids = std::move(currentUuids);
        }

        m_fields->m_syncMetricsTimer += dt;
        if (m_fields->m_syncMetricsTimer >= 5.f) {
            m_fields->m_syncMetricsTimer = 0.f;
            auto& metrics = sync::SyncMetrics::get();
            metrics.setReliableQueueDepth(P2PManager::get().getTotalReliableQueueDepth());
            auto sample = metrics.sample();
            log::info(
                "SYNC PERF objects/s={} bytes/s={} reliableQueue={} objectsTotal={} bytesTotal={}",
                sample.objectsPerSecond, sample.bytesPerSecond, sample.reliableQueueDepth,
                sample.totalObjectsSerialized, sample.totalBytesQueued
            );
        }

        // Send cursor position periodically
        m_fields->m_cursorSendTimer += dt;
        if (m_fields->m_cursorSendTimer >= 0.033f) {  // 30 Hz cursor updates
            m_fields->m_cursorSendTimer = 0.f;
            
            if (this->m_objectLayer) {
                cocos2d::CCPoint levelPos;
                std::string statusStr = "";

                if (this->m_playbackMode != PlaybackMode::Not && this->m_player1) {
                    levelPos = this->m_player1->getPosition();
                    
                    auto* gm = GameManager::get();
                    int iconType = 0; // Cube
                    if (this->m_player1->m_isShip) {
                        iconType = this->m_player1->m_isPlatformer ? 8 : 1; // 8 = Jetpack, 1 = Ship
                    } else if (this->m_player1->m_isBall) {
                        iconType = 2;
                    } else if (this->m_player1->m_isBird) {
                        iconType = 3;
                    } else if (this->m_player1->m_isDart) {
                        iconType = 4;
                    } else if (this->m_player1->m_isRobot) {
                        iconType = 5;
                    } else if (this->m_player1->m_isSpider) {
                        iconType = 6;
                    } else if (this->m_player1->m_isSwing) {
                        iconType = 7;
                    }

                    auto col1 = gm->colorForIdx(gm->getPlayerColor());
                    auto col2 = gm->colorForIdx(gm->getPlayerColor2());
                    bool glowEnabled = gm->getPlayerGlow();
                    auto colGlow = gm->colorForIdx(gm->getPlayerGlowColor());

                    std::stringstream ss;
                    ss << "pt:1:" 
                       << iconType << ":" 
                       << this->m_player1->getRotation() << ":" 
                       << (this->m_player1->m_isUpsideDown ? 1 : 0) << ":"
                       << gm->getPlayerFrame() << ":"
                       << gm->getPlayerShip() << ":"
                       << gm->getPlayerBall() << ":"
                       << gm->getPlayerBird() << ":"
                       << gm->getPlayerDart() << ":"
                       << gm->getPlayerRobot() << ":"
                       << gm->getPlayerSpider() << ":"
                       << gm->getPlayerSwing() << ":"
                       << static_cast<int>(col1.r) << ":" << static_cast<int>(col1.g) << ":" << static_cast<int>(col1.b) << ":"
                       << static_cast<int>(col2.r) << ":" << static_cast<int>(col2.g) << ":" << static_cast<int>(col2.b) << ":"
                       << (glowEnabled ? 1 : 0) << ":"
                       << static_cast<int>(colGlow.r) << ":" << static_cast<int>(colGlow.g) << ":" << static_cast<int>(colGlow.b) << ":"
                       << (this->m_player1->m_vehicleSize < 1.0f ? 1 : 0);
                       
                    if (this->m_player2 && this->m_gameState.m_isDualMode) {
                        int p2IconType = 0;
                        if (this->m_player2->m_isShip) p2IconType = this->m_player2->m_isPlatformer ? 8 : 1;
                        else if (this->m_player2->m_isBall) p2IconType = 2;
                        else if (this->m_player2->m_isBird) p2IconType = 3;
                        else if (this->m_player2->m_isDart) p2IconType = 4;
                        else if (this->m_player2->m_isRobot) p2IconType = 5;
                        else if (this->m_player2->m_isSpider) p2IconType = 6;
                        else if (this->m_player2->m_isSwing) p2IconType = 7;
                        
                        auto p2Pos = this->m_player2->getPosition();
                        ss << ":1:"
                           << p2Pos.x << ":" << p2Pos.y << ":"
                           << this->m_player2->getRotation() << ":"
                           << (this->m_player2->m_isUpsideDown ? 1 : 0) << ":"
                           << (this->m_player2->m_vehicleSize < 1.0f ? 1 : 0) << ":"
                           << p2IconType;
                    } else {
                        ss << ":0:0:0:0:0:0:0";
                    }
                    statusStr = ss.str();
                } else {
#ifdef GEODE_IS_MOBILE
                    if (s_isTouching) {
                        levelPos = this->m_objectLayer->convertToNodeSpace(s_lastTouchPos);
                        m_fields->m_lastSentLevelPos = levelPos;
                    } else {
                        levelPos = m_fields->m_lastSentLevelPos;
                    }
#else
                    auto mousePos = geode::cocos::getMousePos();
                    levelPos = this->m_objectLayer->convertToNodeSpace(mousePos);
#endif
                    
                    if (auto* ui = this->m_editorUI) {
                        int mode = ui->m_selectedMode;
                        int swipe = ui->m_swipeEnabled ? 1 : 0;
                        int objectId = 0;
                        if (mode == 2) { // Build mode
                            objectId = s_selectedObjectID;
                        } else if (mode == 3) { // Edit mode
                            if (ui->m_selectedObject) {
                                objectId = ui->m_selectedObject->m_objectID;
                            } else if (ui->m_selectedObjects && ui->m_selectedObjects->count() > 0) {
                                if (auto* first = typeinfo_cast<GameObject*>(ui->m_selectedObjects->objectAtIndex(0))) {
                                    objectId = first->m_objectID;
                                }
                            }
                        }
                        statusStr = std::to_string(mode) + ":" + std::to_string(swipe) + ":" + std::to_string(objectId);
                    }
                }
                
                int currentSongId = 0;
                int currentAudioTrack = 0;
                if (this->m_level) {
                    currentSongId = this->m_level->m_songID;
                    currentAudioTrack = this->m_level->m_audioTrack;
                }
                std::string currentMusicTitle;
                if (currentSongId > 0) {
                    if (auto* song = LevelTools::getSongObject(currentSongId)) {
                        std::string songName = song->m_songName.c_str();
                        std::string artistName = song->m_artistName.c_str();
                        if (!songName.empty()) {
                            currentMusicTitle = artistName.empty() ? songName : artistName + " - " + songName;
                        }
                    }
                    if (currentMusicTitle.empty()) currentMusicTitle = "Song ID " + std::to_string(currentSongId);
                } else {
                    currentMusicTitle = LevelTools::getAudioTitle(currentAudioTrack);
                    if (currentMusicTitle.empty()) currentMusicTitle = "Official song " + std::to_string(currentAudioTrack);
                }
                for (char& ch : currentMusicTitle) {
                    if (ch == '\n' || ch == '\r') ch = ' ';
                }
                statusStr += ":music:" + std::to_string(currentSongId) + ":" +
                    std::to_string(currentAudioTrack) + ":" + currentMusicTitle;

                auto data = proto::serializeCursorUpdate(levelPos.x, levelPos.y, statusStr);
                P2PManager::get().send(std::move(data), ChannelType::Unreliable);
            }
        }
    }
};

// ============================================================
// EditorUI — Hook object movement/transform to sync
// ============================================================

namespace {
    // Intercepts transform actions and broadcasts deltas.
    // Not hooking EditorUI::transformObjects() directly to avoid stale-cache clobber on deselect.
    void syncTransformedObjects(cocos2d::CCArray* objects,
                                std::function<void()> applyBase) {
        if (s_inTransformSync) {
            applyBase();
            return;
        }

        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        struct ObjState {
            std::string uuid;
            GameObject* obj;
            cocos2d::CCPoint oldPos;
        };
        std::vector<ObjState> selected;

        if (session.isInSession() && !handler.isProcessingRemote() && objects) {
            for (auto* obj : CCArrayExt<GameObject*>(objects)) {
                if (!obj) continue;
                if (handler.isObjectPendingPlacement(obj)) {
                    handler.flushPendingPlacements();
                }
                auto uuid = handler.getUUIDForObject(obj);
                if (!uuid.empty()) {
                    selected.push_back({uuid, obj, obj->getPosition()});
                }
            }
        }

        s_inTransformSync = true;
        applyBase();
        s_inTransformSync = false;

        if (selected.empty()) return;

        std::vector<ActionSerializer::TransformData> transforms;
        std::vector<ActionSerializer::MoveData> moves;

        for (auto& state : selected) {
            ActionSerializer::TransformData td;
            td.uuid = state.uuid;
            td.rotation = state.obj->getRotation();
            td.scaleX = state.obj->getScaleX();
            td.scaleY = state.obj->getScaleY();
            td.flipX = state.obj->isFlipX();
            td.flipY = state.obj->isFlipY();
            transforms.push_back(td);

            cocos2d::CCPoint newPos = state.obj->getPosition();
            float dx = newPos.x - state.oldPos.x;
            float dy = newPos.y - state.oldPos.y;
            if (dx != 0.f || dy != 0.f) {
                ActionSerializer::MoveData md;
                md.uuid = state.uuid;
                md.dx = dx;
                md.dy = dy;
                moves.push_back(md);
            }
        }

        // Queue updates to prevent network flooding during continuous dragging.
        for (auto const& t : transforms) {
            MessageBatcher::get().queueTransform(t.uuid, t);
        }
        for (auto const& m : moves) {
            MessageBatcher::get().queueMove(m.uuid, m.dx, m.dy);
        }

        // Update baselines to prevent redundant syncs in syncDeselections.
        auto& tracked = handler.getTrackedSelections();
        auto* editor = LevelEditorLayer::get();
        if (editor) {
            for (auto& state : selected) {
                auto tIt = tracked.find(state.obj);
                if (tIt != tracked.end()) {
                    tIt->second = objectLayerSyncState(state.obj, editor);
                }
            }
        }
    }
}

class $modify(MPEditorUI, EditorUI) {
    struct Fields {
        float m_lockRefreshTimer = 0.f;
    };

    void onCreateObject(int id) {
        EditorUI::onCreateObject(id);
        s_selectedObjectID = id;
    }

    cocos2d::CCArray* pasteObjects(gd::string str, bool withColor, bool noUndo) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (session.isInSession() && session.getRole() == SessionManager::Role::Client &&
            !handler.isProcessingRemote() && !P2PManager::get().getRoomSettings().allowWorkshop) {
            Notification::create("Host disabled Object Workshop / bulk paste", NotificationIcon::Warning)->show();
            return nullptr;
        }

        bool shouldBulkSync = session.isInSession()
            && !handler.isProcessingRemote()
            && handler.isInitialSyncCompleted();

        if (!shouldBulkSync) {
            return EditorUI::pasteObjects(str, withColor, noUndo);
        }

        s_inBulkPasteSync = true;
        auto* pasted = EditorUI::pasteObjects(str, withColor, noUndo);
        s_inBulkPasteSync = false;

        if (!pasted || pasted->count() == 0) return pasted;

        // Assign UUIDs in the exact order returned by the native paste operation.
        // The receiver performs the same paste and binds these UUIDs by the same
        // returned-array order, avoiding lossy per-object reconstruction.
        std::vector<std::string> uuids;
        uuids.reserve(pasted->count());
        bool haveAnchor = false;
        float pasteAnchorX = 0.f;
        float pasteAnchorY = 0.f;
        for (auto* obj : CCArrayExt<GameObject*>(pasted)) {
            if (!obj) continue;
            if (!haveAnchor) {
                pasteAnchorX = obj->getPositionX();
                pasteAnchorY = obj->getPositionY();
                haveAnchor = true;
            }
            auto uuid = handler.getUUIDForObject(obj);
            if (uuid.empty()) {
                uuid = RemoteActionHandler::generateUUID();
                handler.registerObject(uuid, obj);
            }
            uuids.push_back(encodeLayerTaggedUuid(uuid, obj->m_editorLayer, obj->m_editorLayer2));
            MessageBatcher::get().removePending(uuid);
        }

        static uint32_t s_nextBulkPasteId = 1;
        uint32_t pasteId = s_nextBulkPasteId++;
        if (pasteId == 0) pasteId = s_nextBulkPasteId++;

        std::string raw = std::string(str);
        constexpr size_t kRawBytesPerChunk = 12000;
        constexpr size_t kUuidsPerChunk = 200;
        size_t dataChunks = std::max<size_t>(1, (raw.size() + kRawBytesPerChunk - 1) / kRawBytesPerChunk);
        size_t uuidChunks = std::max<size_t>(1, (uuids.size() + kUuidsPerChunk - 1) / kUuidsPerChunk);
        uint32_t totalChunks = static_cast<uint32_t>(std::max(dataChunks, uuidChunks));

        auto start = proto::serializeBulkPasteStart(
            pasteId, totalChunks, static_cast<uint32_t>(uuids.size()), withColor, noUndo,
            pasteAnchorX, pasteAnchorY
        );
        P2PManager::get().send(std::move(start), ChannelType::Reliable);

        for (uint32_t i = 0; i < totalChunks; ++i) {
            size_t dataOffset = static_cast<size_t>(i) * kRawBytesPerChunk;
            size_t uuidOffset = static_cast<size_t>(i) * kUuidsPerChunk;
            std::string dataChunk;
            std::vector<std::string> uuidChunk;

            if (dataOffset < raw.size()) {
                dataChunk = raw.substr(dataOffset, std::min(kRawBytesPerChunk, raw.size() - dataOffset));
            }
            if (uuidOffset < uuids.size()) {
                size_t count = std::min(kUuidsPerChunk, uuids.size() - uuidOffset);
                uuidChunk.insert(uuidChunk.end(), uuids.begin() + uuidOffset, uuids.begin() + uuidOffset + count);
            }

            auto chunk = proto::serializeBulkPasteChunk(pasteId, i, dataChunk, uuidChunk);
            P2PManager::get().send(std::move(chunk), ChannelType::Reliable);
        }

        auto end = proto::serializeBulkPasteEnd(pasteId);
        P2PManager::get().send(std::move(end), ChannelType::Reliable);

        log::info(
            "EditorHooks: RAW bulk paste #{} synced {} objects, {} bytes in {} chunks",
            pasteId, uuids.size(), raw.size(), totalChunks
        );
        return pasted;
    }

    bool ccTouchBegan(cocos2d::CCTouch* touch, cocos2d::CCEvent* event) {
        bool res = EditorUI::ccTouchBegan(touch, event);
        if (touch) {
            s_lastTouchPos = touch->getLocation();
            s_isTouching = true;
        }
        return res;
    }

    void ccTouchMoved(cocos2d::CCTouch* touch, cocos2d::CCEvent* event) {
        EditorUI::ccTouchMoved(touch, event);
        if (touch) {
            s_lastTouchPos = touch->getLocation();
            s_isTouching = true;
        }
    }

    void ccTouchEnded(cocos2d::CCTouch* touch, cocos2d::CCEvent* event) {
        EditorUI::ccTouchEnded(touch, event);
        s_isTouching = false;
        if (SessionManager::get().isInSession()) {
            MessageBatcher::get().flush();
        }
    }

    void ccTouchCancelled(cocos2d::CCTouch* touch, cocos2d::CCEvent* event) {
        EditorUI::ccTouchCancelled(touch, event);
        s_isTouching = false;
        if (SessionManager::get().isInSession()) {
            MessageBatcher::get().flush();
        }
    }

    void selectObject(GameObject* obj, bool filter) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (session.isInSession() && !handler.isProcessingRemote() && obj) {
            auto uuid = handler.getUUIDForObject(obj);
            if (!uuid.empty()) {
                auto const& locks = handler.getObjectLocks();
                auto it = locks.find(uuid);
                if (it != locks.end() && it->second.playerId != session.getLocalPlayerId()) {
                    return;
                }
            }
        }

        EditorUI::selectObject(obj, filter);

        if (session.isInSession() && obj) {
            auto uuid = handler.getOrCreateUUID(obj);
            auto& tracked = handler.getTrackedSelections();
            if (tracked.find(obj) == tracked.end()) {
                if (auto* editor = LevelEditorLayer::get()) {
                    tracked[obj] = objectLayerSyncState(obj, editor);
                }
                if (!handler.isProcessingRemote()) {
                    auto data = proto::serializeLockObjects({uuid}, true);
                    P2PManager::get().send(std::move(data), ChannelType::Reliable);

                    if (handler.isObjectPendingPlacement(obj)) {
                        handler.flushPendingPlacements();
                    } else {
                        if (auto* editor = LevelEditorLayer::get()) {
                            auto objData = ActionSerializer::extractObjectData(obj, uuid);
                            auto syncData = proto::serializeUpdateObjects({objData});
                            P2PManager::get().send(std::move(syncData), ChannelType::Reliable);
                        }
                    }
                }
            }
        }
    }

    void deselectObject(GameObject* obj) {
        EditorUI::deselectObject(obj);
        
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();
        if (session.isInSession() && obj) {
            auto& tracked = handler.getTrackedSelections();
            if (!handler.isProcessingRemote()) {
                if (handler.isObjectPendingPlacement(obj)) {
                    handler.flushPendingPlacements();
                }

                auto uuid = handler.getUUIDForObject(obj);
                if (!uuid.empty()) {
                    auto tIt = tracked.find(obj);
                    if (tIt != tracked.end()) {
                        if (auto* editor = LevelEditorLayer::get()) {
                            std::string currentSave = objectLayerSyncState(obj, editor);
                            if (tIt->second != currentSave) {
                                auto objData = ActionSerializer::extractObjectData(obj, uuid);
                                auto data = proto::serializeUpdateObjects({objData});
                                P2PManager::get().send(std::move(data), ChannelType::Reliable);
                            }
                        }
                    }

                    ActionSerializer::ReconcileData rec;
                    rec.uuid = uuid;
                    rec.x = obj->getPositionX();
                    rec.y = obj->getPositionY();
                    rec.rotation = obj->getRotation();
                    rec.scaleX = obj->getScaleX();
                    rec.scaleY = obj->getScaleY();
                    rec.flipX = obj->isFlipX();
                    rec.flipY = obj->isFlipY();
                    
                    auto recData = proto::serializeReconcileObjects({rec});
                    P2PManager::get().send(std::move(recData), ChannelType::Reliable);
                    
                    MessageBatcher::get().removePending(uuid);

                    auto data = proto::serializeLockObjects({uuid}, false);
                    P2PManager::get().send(std::move(data), ChannelType::Reliable);
                }
            }
            tracked.erase(obj);
        }
    }

    void deselectAll() {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();
        if (session.isInSession()) {
            if (!handler.isProcessingRemote()) {
                auto* editor = LevelEditorLayer::get();
                std::vector<std::string> uuids;
                std::vector<ActionSerializer::ReconcileData> reconciles;
                std::vector<ActionSerializer::ObjectData> updates;
                
                auto& tracked = handler.getTrackedSelections();
                
                for (auto& [obj, savedString] : tracked) {
                    if (!editor || !editor->m_objects || !editor->m_objects->containsObject(obj)) {
                        continue;
                    }

                    if (handler.isObjectPendingPlacement(obj)) {
                        handler.flushPendingPlacements();
                    }

                    auto uuid = handler.getUUIDForObject(obj);
                    if (uuid.empty()) continue;
                    
                    uuids.push_back(uuid);
                    
                    std::string currentSave = objectLayerSyncState(obj, editor);
                    if (savedString != currentSave) {
                        updates.push_back(ActionSerializer::extractObjectData(obj, uuid));
                    }

                    ActionSerializer::ReconcileData rec;
                    rec.uuid = uuid;
                    rec.x = obj->getPositionX();
                    rec.y = obj->getPositionY();
                    rec.rotation = obj->getRotation();
                    rec.scaleX = obj->getScaleX();
                    rec.scaleY = obj->getScaleY();
                    rec.flipX = obj->isFlipX();
                    rec.flipY = obj->isFlipY();
                    reconciles.push_back(rec);
                    
                    MessageBatcher::get().removePending(uuid);
                }
                
                if (!updates.empty()) {
                    auto data = proto::serializeUpdateObjects(updates);
                    P2PManager::get().send(std::move(data), ChannelType::Reliable);
                }
                if (!reconciles.empty()) {
                    auto data = proto::serializeReconcileObjects(reconciles);
                    P2PManager::get().send(std::move(data), ChannelType::Reliable);
                }
                if (!uuids.empty()) {
                    auto data = proto::serializeLockObjects(uuids, false);
                    P2PManager::get().send(std::move(data), ChannelType::Reliable);
                }
            }
            handler.getTrackedSelections().clear();
        }
        EditorUI::deselectAll();
    }

    void onDeleteSelected(cocos2d::CCObject* sender) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (session.isInSession() && !handler.isProcessingRemote()) {
            std::vector<std::string> uuids;
            
            if (m_selectedObjects && m_selectedObjects->count() > 0) {
                for (auto* obj : CCArrayExt<GameObject*>(m_selectedObjects)) {
                    auto uuid = handler.getUUIDForObject(obj);
                    if (!uuid.empty()) {
                        uuids.push_back(uuid);
                        handler.unregisterObject(uuid);
                    }
                }
            } else if (m_selectedObject) {
                auto uuid = handler.getUUIDForObject(m_selectedObject);
                if (!uuid.empty()) {
                    uuids.push_back(uuid);
                    handler.unregisterObject(uuid);
                }
            }

            if (!uuids.empty()) {
                auto data = proto::serializeDeleteObjects(uuids);
                P2PManager::get().send(std::move(data), ChannelType::Reliable);
            }
        }

        EditorUI::onDeleteSelected(sender);
    }

    bool shouldDeleteObject(GameObject* obj) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (session.isInSession() && !handler.isProcessingRemote() && obj) {
            auto uuid = handler.getUUIDForObject(obj);
            if (!uuid.empty()) {
                auto const& locks = handler.getObjectLocks();
                auto it = locks.find(uuid);
                if (it != locks.end() && it->second.playerId != session.getLocalPlayerId()) {
                    // Locked by another player! Do not delete.
                    return false;
                }
            }
        }
        return EditorUI::shouldDeleteObject(obj);
    }

    void selectObjects(cocos2d::CCArray* objects, bool filter) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        cocos2d::CCArray* filteredObjects = objects;
        if (session.isInSession() && !handler.isProcessingRemote() && objects) {
            auto const& locks = handler.getObjectLocks();
            int localId = session.getLocalPlayerId();
            
            bool hasLocked = false;
            for (auto* obj : CCArrayExt<GameObject*>(objects)) {
                auto uuid = handler.getUUIDForObject(obj);
                if (!uuid.empty()) {
                    auto it = locks.find(uuid);
                    if (it != locks.end() && it->second.playerId != localId) {
                        hasLocked = true;
                        break;
                    }
                }
            }

            if (hasLocked) {
                filteredObjects = cocos2d::CCArray::create();
                for (auto* obj : CCArrayExt<GameObject*>(objects)) {
                    auto uuid = handler.getUUIDForObject(obj);
                    bool isLockedByOther = false;
                    if (!uuid.empty()) {
                        auto it = locks.find(uuid);
                        if (it != locks.end() && it->second.playerId != localId) {
                            isLockedByOther = true;
                        }
                    }
                    if (!isLockedByOther) {
                        filteredObjects->addObject(obj);
                    }
                }
            }
        }

        EditorUI::selectObjects(filteredObjects, filter);

        if (session.isInSession() && filteredObjects) {
            std::vector<std::string> uuids;
            auto& tracked = handler.getTrackedSelections();
            auto* editor = LevelEditorLayer::get();
            for (auto* obj : CCArrayExt<GameObject*>(filteredObjects)) {
                auto uuid = handler.getOrCreateUUID(obj);
                if (tracked.find(obj) == tracked.end()) {
                    if (editor) {
                        tracked[obj] = objectLayerSyncState(obj, editor);
                    }
                    uuids.push_back(uuid);
                }
            }
            if (!uuids.empty() && !handler.isProcessingRemote()) {
                auto data = proto::serializeLockObjects(uuids, true);
                P2PManager::get().send(std::move(data), ChannelType::Reliable);
            }
        }
    }

    bool init(LevelEditorLayer* editorLayer) {
        if (!EditorUI::init(editorLayer)) return false;

        // Add a helper node to handle syncDeselections updates safely without member function pointer layout mismatch
        auto* helper = UpdateHelperNode::create([this](float dt) {
            this->syncDeselections(dt);
        }, 0.1f);
        if (helper) {
            helper->setID("sync-deselect-helper"_spr);
            this->addChild(helper);
        }
        return true;
    }

    void syncDeselections(float dt) {
        auto* editor = LevelEditorLayer::get();
        if (!editor || !editor->m_objects || editor->m_playbackMode != PlaybackMode::Not) return;

        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();
        if (!session.isInSession() || handler.isProcessingRemote()) return;

        auto& tracked = handler.getTrackedSelections();
        auto const& locks = handler.getObjectLocks();
        int localId = session.getLocalPlayerId();

        std::vector<GameObject*> currentSelection;
        if (m_selectedObject) {
            currentSelection.push_back(m_selectedObject);
        }
        if (m_selectedObjects) {
            for (auto* obj : CCArrayExt<GameObject*>(m_selectedObjects)) {
                if (obj) currentSelection.push_back(obj);
            }
        }

        std::vector<GameObject*> toDeselect;
        std::vector<std::string> toLockUuids;

        for (auto* obj : currentSelection) {
            auto uuid = handler.getUUIDForObject(obj);
            if (uuid.empty()) {
                uuid = RemoteActionHandler::generateUUID();
                handler.registerObject(uuid, obj);
            }

            auto it = locks.find(uuid);
            if (it != locks.end() && it->second.playerId != localId) {
                toDeselect.push_back(obj);
            } else {
                if (tracked.find(obj) == tracked.end()) {
                    tracked[obj] = objectLayerSyncState(obj, editor);
                    toLockUuids.push_back(uuid);
                }
            }
        }

        for (auto* obj : toDeselect) {
            this->deselectObject(obj);
            if (m_selectedObject == obj) {
                m_selectedObject = nullptr;
            }
            if (m_selectedObjects && m_selectedObjects->containsObject(obj)) {
                m_selectedObjects->removeObject(obj);
            }
        }

        if (!toLockUuids.empty()) {
            auto data = proto::serializeLockObjects(toLockUuids, true);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
        }

        m_fields->m_lockRefreshTimer += dt;
        if (m_fields->m_lockRefreshTimer >= 1.0f) {
            m_fields->m_lockRefreshTimer = 0.f;
            std::vector<std::string> refreshUuids;
            for (auto const& [obj, _] : tracked) {
                if (editor->m_objects->containsObject(obj)) {
                    auto uuid = handler.getUUIDForObject(obj);
                    if (!uuid.empty()) {
                        refreshUuids.push_back(uuid);
                    }
                }
            }
            if (!refreshUuids.empty()) {
                auto data = proto::serializeLockObjects(refreshUuids, true);
                P2PManager::get().send(std::move(data), ChannelType::Reliable);
            }
        }

        // We run the property-diff (getSaveString) on every tracked selected
        // object every tick. This is NOT optional: transforms that don't go
        // through a touch (Q/E rotate, the rotate/scale buttons, Mirror/Flip X/Y)
        // change object properties without setting s_isTouching, so gating the
        // diff on touch (as 0.3.0 did) silently dropped those changes. The diff
        // is the universal fallback that syncs any property change regardless of
        // how it was triggered. Performance is fine because the loop only covers
        // currently-selected objects, not the whole level.
        std::vector<std::string> unlockUuids;
        std::vector<ActionSerializer::ReconcileData> reconciles;
        std::vector<ActionSerializer::ObjectData> updates;

        for (auto it = tracked.begin(); it != tracked.end(); ) {
            GameObject* obj = it->first;

            if (!editor->m_objects->containsObject(obj)) {
                it = tracked.erase(it);
                continue;
            }

            bool isSelected = (std::find(currentSelection.begin(), currentSelection.end(), obj) != currentSelection.end()) &&
                              (std::find(toDeselect.begin(), toDeselect.end(), obj) == toDeselect.end());

            if (handler.isObjectPendingPlacement(obj)) {
                handler.flushPendingPlacements();
            }
            auto uuid = handler.getUUIDForObject(obj);
            if (uuid.empty()) {
                it = tracked.erase(it);
                continue;
            }

            if (!isSelected) {
                unlockUuids.push_back(uuid);

                ActionSerializer::ReconcileData rec;
                rec.uuid = uuid;
                rec.x = obj->getPositionX();
                rec.y = obj->getPositionY();
                rec.rotation = obj->getRotation();
                rec.scaleX = obj->getScaleX();
                rec.scaleY = obj->getScaleY();
                rec.flipX = obj->isFlipX();
                rec.flipY = obj->isFlipY();
                reconciles.push_back(rec);

                std::string currentSave = objectLayerSyncState(obj, editor);
                if (ActionSerializer::hasDeepPropertyChanges(obj, it->second, currentSave)) {
                    updates.push_back(ActionSerializer::extractObjectData(obj, uuid));
                }
                
                MessageBatcher::get().removePending(uuid);

                it = tracked.erase(it);
            } else {
                std::string currentSave = objectLayerSyncState(obj, editor);
                if (ActionSerializer::hasDeepPropertyChanges(obj, it->second, currentSave)) {
                    updates.push_back(ActionSerializer::extractObjectData(obj, uuid));
                    it->second = currentSave;
                } else if (it->second != currentSave) {
                    it->second = currentSave;
                    
                    MessageBatcher::get().removePending(uuid);
                    
                    ActionSerializer::ReconcileData rec;
                    rec.uuid = uuid;
                    rec.x = obj->getPositionX();
                    rec.y = obj->getPositionY();
                    rec.rotation = obj->getRotation();
                    rec.scaleX = obj->getScaleX();
                    rec.scaleY = obj->getScaleY();
                    rec.flipX = obj->isFlipX();
                    rec.flipY = obj->isFlipY();
                    reconciles.push_back(rec);
                }
                ++it;
            }
        }

        for (auto it = s_startPosObjects.begin(); it != s_startPosObjects.end(); ) {
            GameObject* obj = *it;
            if (!editor->m_objects->containsObject(obj)) {
                s_startPosSaveStrings.erase(obj);
                it = s_startPosObjects.erase(it);
                continue;
            }
            auto uuid = handler.getUUIDForObject(obj);
            if (!uuid.empty()) {
                std::string currentSave = objectLayerSyncState(obj, editor);
                if (s_startPosSaveStrings.count(obj)) {
                    if (ActionSerializer::hasDeepPropertyChanges(obj, s_startPosSaveStrings[obj], currentSave)) {
                        updates.push_back(ActionSerializer::extractObjectData(obj, uuid));
                    }
                }
                s_startPosSaveStrings[obj] = currentSave;
            }
            ++it;
        }

        if (!unlockUuids.empty()) {
            auto data = proto::serializeLockObjects(unlockUuids, false);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
        }
        if (!reconciles.empty()) {
            auto data = proto::serializeReconcileObjects(reconciles);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
        }
        if (!updates.empty()) {
            auto data = proto::serializeUpdateObjects(updates);
            P2PManager::get().send(std::move(data), ChannelType::Reliable);
        }
    }

    void moveObject(GameObject* obj, CCPoint position) {
        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (session.isInSession() && !handler.isProcessingRemote() && obj) {
            auto uuid = handler.getUUIDForObject(obj);
            if (!uuid.empty()) {
                auto const& locks = handler.getObjectLocks();
                auto it = locks.find(uuid);
                if (it != locks.end() && it->second.playerId != session.getLocalPlayerId()) {
                    return;
                }
            }
        }

        CCPoint oldPos = obj->getPosition();

        EditorUI::moveObject(obj, position);

        if (session.isInSession() && !handler.isProcessingRemote()) {
            auto uuid = handler.getUUIDForObject(obj);
            if (handler.isObjectPendingPlacement(obj)) {
                return;
            }
            if (!uuid.empty()) {
                CCPoint newPos = obj->getPosition();
                ActionSerializer::MoveData move;
                move.uuid = uuid;
                move.dx = newPos.x - oldPos.x;
                move.dy = newPos.y - oldPos.y;

                if ((move.dx != 0.f || move.dy != 0.f) && !s_inTransformSync) {
                    MessageBatcher::get().queueMove(uuid, move.dx, move.dy);

                    auto& tracked = handler.getTrackedSelections();
                    auto tIt = tracked.find(obj);
                    if (tIt != tracked.end()) {
                        if (auto* editor = LevelEditorLayer::get()) {
                            tIt->second = obj->getSaveString(editor);
                        }
                    }
                }
            }
        }
    }

    void transformObjectCall(EditCommand command) {
        syncTransformedObjects(m_selectedObjects, [&]() {
            EditorUI::transformObjectCall(command);
        });
    }

    void rotateObjects(cocos2d::CCArray* objects, float rotation, cocos2d::CCPoint pivotPoint) {
        syncTransformedObjects(objects, [&]() {
            EditorUI::rotateObjects(objects, rotation, pivotPoint);
        });
    }

    void scaleObjects(cocos2d::CCArray* objects, float scaleX, float scaleY, cocos2d::CCPoint pivotPoint, ObjectScaleType type, bool lockMove) {
        syncTransformedObjects(objects, [&]() {
            EditorUI::scaleObjects(objects, scaleX, scaleY, pivotPoint, type, lockMove);
        });
    }

    void flipObjectsX(cocos2d::CCArray* objects) {
        syncTransformedObjects(objects, [&]() {
            EditorUI::flipObjectsX(objects);
        });
    }

    void flipObjectsY(cocos2d::CCArray* objects) {
        syncTransformedObjects(objects, [&]() {
            EditorUI::flipObjectsY(objects);
        });
    }
};

class $modify(MPBaseGameLayer, GJBaseGameLayer) {
    void addToSection(GameObject* obj) {
        GJBaseGameLayer::addToSection(obj);

        if (obj && obj->m_objectID == 31) {
            auto* editor = LevelEditorLayer::get();
            if (editor && static_cast<GJBaseGameLayer*>(editor) == this) {
                s_startPosObjects.insert(obj);
                s_startPosSaveStrings[obj] = obj->getSaveString(editor);
            }
        }

        auto& handler = RemoteActionHandler::get();
        auto& session = SessionManager::get();

        if (!session.isInSession() || handler.isProcessingRemote() || !obj) {
            return;
        }

        if (s_inBulkPasteSync) {
            return;
        }

        if (!handler.isInitialSyncCompleted()) {
            return;
        }

        auto* editor = LevelEditorLayer::get();
        if (!editor || static_cast<GJBaseGameLayer*>(editor) != this) {
            return;
        }

        auto* mpEditor = modify_cast<MPLevelEditorLayer*>(editor);
        if (!mpEditor || !session.isInSession() || mpEditor->m_fields->m_inUndoRedo) {
            return;
        }

        // If the object already has a UUID, it's already registered (e.g., via createObject)
        if (!handler.getUUIDForObject(obj).empty()) {
            return;
        }

        if (auto* tpPortal = typeinfo_cast<TeleportPortalObject*>(obj)) {
            if (tpPortal->m_isYellowPortal) {
                return;
            }
        }

        // Assign a new UUID and queue it for a batched placement flush.
        // Copy/paste/duplicate can add dozens of objects in a single frame;
        // queueing them lets us send one place_objects message (via the network
        // tick) instead of one WebSocket send per object.
        auto uuid = RemoteActionHandler::generateUUID();
        handler.registerObject(uuid, obj);
        handler.queueObjectForPlacement(uuid, obj);
    }
};

#include <Geode/modify/GJColorSetupLayer.hpp>
class $modify(MPGJColorSetupLayer, GJColorSetupLayer) {
    void syncColors() {
        auto& handler = RemoteActionHandler::get();
        if (handler.isProcessingRemote() || !handler.isInitialSyncCompleted()) return;

        auto& session = SessionManager::get();
        if (!session.isInSession()) return;
        
        auto editor = LevelEditorLayer::get();
        if (editor && editor->m_levelSettings) {
            ActionSerializer::LevelSettingsData settings;
            settings.saveString = editor->m_levelSettings->getSaveString();
            settings.audioTrack = editor->m_level->m_audioTrack;
            settings.songID = editor->m_level->m_songID;
            settings.levelLength = editor->m_level->m_levelLength;
            
            auto packet = proto::serializeUpdateSettings(settings);
            P2PManager::get().send(std::move(packet), ChannelType::Reliable);
        }
    }

    void colorSelectClosed(cocos2d::CCNode* popup) {
        GJColorSetupLayer::colorSelectClosed(popup);
        
        auto* editor = LevelEditorLayer::get();
        if (editor && editor->m_levelSettings && editor->m_levelSettings->m_effectManager) {
            auto* dict = editor->m_levelSettings->m_effectManager->m_colorActionDict;
            if (dict) {
                log::info("m_colorActionDict contains {} items.", dict->count());
                auto* keys = dict->allKeys();
                if (keys) {
                    for (int i = 0; i < keys->count(); i++) {
                        auto* keyObj = keys->objectAtIndex(i);
                        if (auto* strKey = typeinfo_cast<cocos2d::CCString*>(keyObj)) {
                            log::info("Key type: String, val: {}", strKey->getCString());
                        } else if (auto* intKey = typeinfo_cast<cocos2d::CCInteger*>(keyObj)) {
                            log::info("Key type: Int, val: {}", intKey->getValue());
                        }
                    }
                }
            }
        }
        
        syncColors();
    }

    void onClose(cocos2d::CCObject* sender) {
        GJColorSetupLayer::onClose(sender);
        syncColors();
    }
};



#include <Geode/modify/LevelSettingsLayer.hpp>
class $modify(MPLevelSettingsLayer, LevelSettingsLayer) {
    void onClose(cocos2d::CCObject* sender) {
        LevelSettingsLayer::onClose(sender);

        auto& handler = RemoteActionHandler::get();
        if (handler.isProcessingRemote() || !handler.isInitialSyncCompleted()) return;

        auto& session = SessionManager::get();
        if (!session.isInSession()) return;

        auto editor = LevelEditorLayer::get();
        if (editor && editor->m_levelSettings) {
            ActionSerializer::LevelSettingsData settings;
            settings.saveString = editor->m_levelSettings->getSaveString();
            settings.audioTrack = editor->m_level->m_audioTrack;
            settings.songID = editor->m_level->m_songID;
            settings.levelLength = editor->m_level->m_levelLength;
            
            auto packet = proto::serializeUpdateSettings(settings);
            P2PManager::get().send(std::move(packet), ChannelType::Reliable);
        }
    }
};

#include <Geode/modify/ColorSelectPopup.hpp>
class $modify(MPColorSelectPopup, ColorSelectPopup) {
    void closeColorSelect(cocos2d::CCObject* sender) {
        ColorSelectPopup::closeColorSelect(sender);

        auto& handler = RemoteActionHandler::get();
        if (handler.isProcessingRemote() || !handler.isInitialSyncCompleted()) return;

        auto& session = SessionManager::get();
        if (!session.isInSession()) return;

        auto editor = LevelEditorLayer::get();
        if (editor && editor->m_levelSettings) {
            ActionSerializer::LevelSettingsData settings;
            settings.saveString = editor->m_levelSettings->getSaveString();
            settings.audioTrack = editor->m_level->m_audioTrack;
            settings.songID = editor->m_level->m_songID;
            settings.levelLength = editor->m_level->m_levelLength;
            
            auto packet = proto::serializeUpdateSettings(settings);
            P2PManager::get().send(std::move(packet), ChannelType::Reliable);
        }
    }
};

