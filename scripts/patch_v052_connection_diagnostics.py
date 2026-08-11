from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.2 connection diagnostics: {label}: expected source block not found")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Final Room Settings Max Players polish.
# ButtonSprite has a larger visual minimum than the requested width, so the
# previous 42-unit separation could still make +/- appear glued together.
# Give the two controls a fixed, symmetric 68-unit center separation.
# -----------------------------------------------------------------------------
room_path = Path("src/ui/RoomSettingsPopup.cpp")
room = room_path.read_text(encoding="utf-8")
room = replace_once(
    room,
    '''    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), 30.f);
    minus->setPosition({center.width + 20.f, topY});
    menu->addChild(minus);

    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), 30.f);
    plus->setPosition({center.width + 62.f, topY});''',
    '''    constexpr float maxButtonWidth = 28.f;
    constexpr float maxPairCenterX = 276.f;
    constexpr float maxButtonHalfGap = 34.f;

    auto* minus = makeButton("-", this, menu_selector(RoomSettingsPopup::onMaxMinus), maxButtonWidth);
    minus->setPosition({maxPairCenterX - maxButtonHalfGap, topY});
    menu->addChild(minus);

    auto* plus = makeButton("+", this, menu_selector(RoomSettingsPopup::onMaxPlus), maxButtonWidth);
    plus->setPosition({maxPairCenterX + maxButtonHalfGap, topY});''',
    "Max Players final symmetric spacing",
)
room_path.write_text(room, encoding="utf-8")


# -----------------------------------------------------------------------------
# MultiplayerPopup connection diagnostics.
# -----------------------------------------------------------------------------
hpp_path = Path("src/ui/MultiplayerPopup.hpp")
hpp = hpp_path.read_text(encoding="utf-8")
hpp = replace_once(
    hpp,
    '''        cocos2d::CCMenu* m_sessionMenu = nullptr;
        cocos2d::CCNode* m_contentNode = nullptr;''',
    '''        cocos2d::CCMenu* m_sessionMenu = nullptr;
        cocos2d::CCNode* m_contentNode = nullptr;

        // v0.5.2 connection diagnostics. This is UI-only state and does not
        // affect signaling/WebRTC behavior or the wire protocol.
        bool m_connectionPending = false;
        float m_connectionElapsed = 0.f;
        int m_lastConnectionStage = -1;''',
    "popup diagnostic fields",
)
hpp_path.write_text(hpp, encoding="utf-8")

cpp_path = Path("src/ui/MultiplayerPopup.cpp")
cpp = cpp_path.read_text(encoding="utf-8")

cpp = replace_once(
    cpp,
    '''        if (m_statusLabel) {
            m_statusLabel->setString("Joining...");
            m_statusLabel->setColor({255, 255, 100});
        }

        auto& session = SessionManager::get();''',
    '''        m_connectionPending = true;
        m_connectionElapsed = 0.f;
        m_lastConnectionStage = -1;
        if (m_statusLabel) {
            m_statusLabel->setString("Stage 1/4: Contacting signaling server...");
            m_statusLabel->setColor({255, 255, 100});
        }

        auto& session = SessionManager::get();''',
    "join diagnostics start",
)

cpp = replace_once(
    cpp,
    '''        session.onSessionStarted([this]() {
            createLoadingView("Waiting for level sync from host...");
        });''',
    '''        session.onSessionStarted([this]() {
            createLoadingView("Stage 2/4: Negotiating WebRTC / ICE...");
            m_connectionPending = true;
            m_lastConnectionStage = 2;
        });''',
    "client session-start diagnostics",
)

# Reset diagnostics on error before rebuilding the normal connect view.
cpp = replace_once(
    cpp,
    '''            this->clearContentNode();
            this->createConnectView();
            
            if (m_statusLabel) {''',
    '''            m_connectionPending = false;
            m_connectionElapsed = 0.f;
            m_lastConnectionStage = -1;
            this->clearContentNode();
            this->createConnectView();
            
            if (m_statusLabel) {''',
    "connection diagnostics reset on error",
)

cpp = replace_once(
    cpp,
    '''    void MultiplayerPopup::onLeave(CCObject*) {
        auto& session = SessionManager::get();''',
    '''    void MultiplayerPopup::onLeave(CCObject*) {
        m_connectionPending = false;
        m_connectionElapsed = 0.f;
        m_lastConnectionStage = -1;
        auto& session = SessionManager::get();''',
    "connection diagnostics reset on leave",
)

cpp = replace_once(
    cpp,
    '''    void MultiplayerPopup::pollNetwork(float dt) {
        P2PManager::get().dispatchMessages();
    }''',
    '''    void MultiplayerPopup::pollNetwork(float dt) {
        auto& net = P2PManager::get();
        net.dispatchMessages();

        if (!m_connectionPending || !m_statusLabel) return;

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
        m_statusLabel->setScale(text.find('\\n') == std::string::npos ? 0.55f : 0.44f);
    }''',
    "pollNetwork staged diagnostics",
)

cpp_path.write_text(cpp, encoding="utf-8")

checks = [
    (room_path, "maxButtonHalfGap = 34.f"),
    (hpp_path, "m_connectionElapsed"),
    (cpp_path, "Stage 1/4: Signaling - joining room"),
    (cpp_path, "Stage 2/4: WebRTC - ICE / STUN / TURN negotiation"),
    (cpp_path, "Stage 3/4: P2P connected - waiting for level sync"),
    (cpp_path, "Taking unusually long - check TURN password / network"),
    (cpp_path, "connection diagnostic stage="),
]
for path, marker in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.2 connection diagnostics self-check failed: {path}: {marker}")

print("Patched v0.5.2 final UX: staged connection diagnostics + symmetric Max Players buttons")
