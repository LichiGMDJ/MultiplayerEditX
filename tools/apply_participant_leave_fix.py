from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
p2p = replace_once(
    p2p,
    '''        if (m_role == Role::Host && !m_roomCode.empty()) {
            auto url = getSignalingUrl() + "/rooms/" + m_roomCode;
            auto req = web::WebRequest();
            if (!m_signalingToken.empty()) {
                req.header("Authorization", "Bearer " + m_signalingToken);
            }
            async::spawn(req.send("DELETE", url));
        }''',
    '''        // Every participant explicitly leaves the signaling directory.
        // Previously only the host sent DELETE, so departed guests remained in
        // room.clients and could later be elected as a ghost migration host.
        if (m_role != Role::None && !m_roomCode.empty() && !m_signalingToken.empty()) {
            auto url = getSignalingUrl() + "/rooms/" + m_roomCode;
            auto req = web::WebRequest();
            req.header("Authorization", "Bearer " + m_signalingToken);
            async::spawn(req.send("DELETE", url));
        }''',
    "client signaling leave",
)
p2p_path.write_text(p2p, encoding="utf-8")

server_path = Path("server/signaling/server.ts")
server = server_path.read_text(encoding="utf-8")
server = replace_once(
    server,
    '''    if (req.method === "DELETE" && parts.length === 2) {
      const token = bearerToken(req);
      if (!token || token !== room.host.token) return json({ error: "host token required" }, 403);

      const winner = electMigrationHost(room);
      if (!winner) {
        rooms.delete(roomCode);
        return json({ ok: true, closed: true });
      }

      promoteHost(room, winner);
      return json({
        ok: true,
        closed: false,
        migrated: true,
        generation: room.generation,
      });
    }''',
    '''    if (req.method === "DELETE" && parts.length === 2) {
      const token = bearerToken(req);
      const participant = findParticipant(room, token);
      if (!participant) return json({ error: "unauthorized" }, 401);

      // Guests must be removed from the signaling roster as soon as they press
      // Leave. Otherwise a later host leave may migrate the room to a client
      // that is no longer connected, leaving a ghost public room behind.
      if (participant.token !== room.host.token) {
        room.clients.delete(participant.playerId);
        touch(room);
        return json({ ok: true, left: true });
      }

      const winner = electMigrationHost(room);
      if (!winner) {
        rooms.delete(roomCode);
        return json({ ok: true, closed: true });
      }

      promoteHost(room, winner);
      return json({
        ok: true,
        closed: false,
        migrated: true,
        generation: room.generation,
      });
    }''',
    "server participant leave",
)
server_path.write_text(server, encoding="utf-8")

assert "m_role != Role::None" in p2p
assert "room.clients.delete(participant.playerId);" in server
print("participant leave fix applied")
