from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"v0.5.2 UI lifetime: {label}: expected source block not found")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# MultiplayerPopup: never touch popup UI after dispatchMessages().
#
# dispatchMessages() may synchronously invoke session/protocol callbacks. Those
# callbacks are allowed to rebuild or close MultiplayerPopup. The connection
# diagnostics patch previously dispatched first and then dereferenced `this`
# and m_statusLabel, which made a join-time use-after-free possible.
#
# Make dispatch the final operation of the timer tick. If a callback destroys
# the popup, the function returns without any later UI access.
# -----------------------------------------------------------------------------
popup_path = Path("src/ui/MultiplayerPopup.cpp")
popup = popup_path.read_text(encoding="utf-8")

popup = replace_once(
    popup,
    '''    void MultiplayerPopup::pollNetwork(float dt) {
        auto& net = P2PManager::get();
        net.dispatchMessages();

        if (!m_connectionPending || !m_statusLabel) return;''',
    '''    void MultiplayerPopup::pollNetwork(float dt) {
        auto& net = P2PManager::get();

        // IMPORTANT: dispatchMessages() can synchronously rebuild/close this
        // popup through session callbacks. Do all optional UI work BEFORE the
        // dispatch and never dereference `this` after it.
        if (!m_connectionPending || !m_statusLabel) {
            net.dispatchMessages();
            return;
        }''',
    "dispatch-before-UI hazard",
)

popup = replace_once(
    popup,
    '''        m_statusLabel->setString(text.c_str());
        m_statusLabel->setColor(color);
        m_statusLabel->setScale(text.find('\\n') == std::string::npos ? 0.55f : 0.44f);
    }''',
    '''        m_statusLabel->setString(text.c_str());
        m_statusLabel->setColor(color);
        m_statusLabel->setScale(text.find('\\n') == std::string::npos ? 0.55f : 0.44f);

        // Must stay last: callbacks reached from here may destroy this popup.
        net.dispatchMessages();
    }''',
    "dispatch as final popup operation",
)

popup_path.write_text(popup, encoding="utf-8")


# -----------------------------------------------------------------------------
# SessionStatusNode: scheduled UI should not mutate labels while its node is no
# longer running during editor/scene teardown. This is a second guard for the
# same crash signature (CCLabelBMFont::setColor on the main scheduler thread).
# -----------------------------------------------------------------------------
status_path = Path("src/ui/SessionStatusNode.cpp")
status = status_path.read_text(encoding="utf-8")
status = replace_once(
    status,
    '''    void SessionStatusNode::update(float dt) {
        auto& session = SessionManager::get();''',
    '''    void SessionStatusNode::update(float dt) {
        // Scene/editor teardown can race the scheduler by one tick. Never touch
        // the child label once this node has left the running scene.
        if (!this->isRunning() || !m_statusLabel) return;

        auto& session = SessionManager::get();''',
    "SessionStatusNode teardown guard",
)
status_path.write_text(status, encoding="utf-8")


checks = [
    (popup_path, "Do all optional UI work BEFORE the"),
    (popup_path, "Must stay last: callbacks reached from here may destroy this popup"),
    (status_path, "if (!this->isRunning() || !m_statusLabel) return;"),
]
for path, marker in checks:
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"v0.5.2 UI lifetime self-check failed: {path}: {marker}")

print("Patched v0.5.2 UI lifetime: no post-dispatch popup access + status teardown guard")
