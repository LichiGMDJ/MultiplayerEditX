from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# Server: stop advertising a room whose host stopped touching signaling.
server_path = Path("server/signaling/server.ts")
server = server_path.read_text(encoding="utf-8")
server = replace_once(
    server,
    "const ROOM_TTL_MS = 2 * 60 * 60 * 1000;\nconst LONG_POLL_MS = 25_000;",
    '''const ROOM_TTL_MS = 2 * 60 * 60 * 1000;
// Public directory liveness is intentionally much shorter than room retention.
// A stale room can remain internally for host migration/reconnect, but must not
// be shown as joinable after the host is gone.
const HOST_DIRECTORY_STALE_MS = 45_000;
const LONG_POLL_MS = 25_000;''',
    "directory stale constant",
)
server = replace_once(
    server,
    '''function removeExpiredRooms(): void {
  const cutoff = now() - ROOM_TTL_MS;
  for (const [code, room] of rooms) {
    if (room.lastActivityAt < cutoff) rooms.delete(code);
  }

  const rateCutoff = now() - 5 * 60_000;''',
    '''function removeExpiredRooms(): void {
  const current = now();
  const cutoff = current - ROOM_TTL_MS;
  for (const [code, room] of rooms) {
    const hostStale = current - room.host.lastSeenAt > HOST_DIRECTORY_STALE_MS;
    if (room.lastActivityAt < cutoff || (hostStale && room.clients.size === 0)) {
      rooms.delete(code);
    }
  }

  const rateCutoff = current - 5 * 60_000;''',
    "expired room cleanup",
)
server = replace_once(
    server,
    '''  if (req.method === "GET" && path === "/rooms") {
    const publicRooms = [...rooms.values()]
      .filter((room) => !room.isPrivate)''',
    '''  if (req.method === "GET" && path === "/rooms") {
    const directoryNow = now();
    const publicRooms = [...rooms.values()]
      .filter((room) =>
        !room.isPrivate &&
        directoryNow - room.host.lastSeenAt <= HOST_DIRECTORY_STALE_MS
      )''',
    "public room liveness filter",
)
server_path.write_text(server, encoding="utf-8")


# Browser: refresh silently so a removed room disappears without requiring the
# user to close/reopen the popup or press Refresh manually.
header_path = Path("src/ui/RoomDiscoveryPopups.hpp")
header = header_path.read_text(encoding="utf-8")
header = replace_once(
    header,
    '''    std::size_t m_page = 0;
    geode::async::TaskHolder<geode::utils::web::WebResponse> m_request;

    bool setup();
    void fetchRooms();''',
    '''    std::size_t m_page = 0;
    geode::async::TaskHolder<geode::utils::web::WebResponse> m_request;
    bool m_fetchInFlight = false;
    float m_autoRefreshTimer = 0.f;

    bool setup();
    void update(float dt) override;
    void fetchRooms(bool showLoading = true);''',
    "browser refresh state",
)
header_path.write_text(header, encoding="utf-8")

cpp_path = Path("src/ui/RoomDiscoveryPopups.cpp")
cpp = cpp_path.read_text(encoding="utf-8")
cpp = replace_once(
    cpp,
    '''    fetchRooms();
    return true;
}

void RoomBrowserPopup::fetchRooms() {
    if (!m_body) return;
    m_rooms.clear();
    m_page = 0;
    m_body->removeAllChildren();

    auto center = m_mainLayer->getContentSize() / 2.f;
    m_statusLabel = makeLabel("Loading rooms...", 0.45f, center, m_body);''',
    '''    fetchRooms();
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
    }''',
    "periodic room refresh",
)
cpp = replace_once(
    cpp,
    '''    m_request.spawn(req.get(url), [this, url](web::WebResponse res) {
        if (!m_body) return;
        if (!res.ok()) {''',
    '''    m_request.spawn(req.get(url), [this, url, showLoading](web::WebResponse res) {
        m_fetchInFlight = false;
        if (!m_body) return;
        if (!res.ok()) {''',
    "refresh callback state",
)
cpp = replace_once(
    cpp,
    '''            m_body->removeAllChildren();
            m_statusLabel = makeLabel("Could not load rooms", 0.45f, m_mainLayer->getContentSize() / 2.f, m_body);
            m_statusLabel->setColor({255, 120, 120});
            return;''',
    '''            if (showLoading) {
                m_body->removeAllChildren();
                m_statusLabel = makeLabel("Could not load rooms", 0.45f, m_mainLayer->getContentSize() / 2.f, m_body);
                m_statusLabel->setColor({255, 120, 120});
            }
            return;''',
    "silent refresh error handling",
)
cpp = replace_once(
    cpp,
    "        for (std::size_t i = 0; i < json.size(); ++i) {",
    "        std::vector<BrowserRoomInfo> freshRooms;\n        freshRooms.reserve(json.size());\n        for (std::size_t i = 0; i < json.size(); ++i) {",
    "fresh room list",
)
cpp = replace_once(
    cpp,
    '''            if (!room.roomCode.empty()) m_rooms.push_back(std::move(room));
        }
        rebuild();''',
    '''            if (!room.roomCode.empty()) freshRooms.push_back(std::move(room));
        }
        m_rooms = std::move(freshRooms);
        rebuild();''',
    "atomic room list swap",
)
cpp_path.write_text(cpp, encoding="utf-8")

for path, tokens in {
    "server/signaling/server.ts": ["HOST_DIRECTORY_STALE_MS = 45_000", "directoryNow - room.host.lastSeenAt"],
    "src/ui/RoomDiscoveryPopups.hpp": ["m_autoRefreshTimer", "fetchRooms(bool showLoading = true)"],
    "src/ui/RoomDiscoveryPopups.cpp": ["fetchRooms(false);", "freshRooms.reserve(json.size())"],
}.items():
    text = Path(path).read_text(encoding="utf-8")
    for token in tokens:
        if token not in text:
            raise RuntimeError(f"{path}: missing {token}")

print("public room lifecycle fix applied")
