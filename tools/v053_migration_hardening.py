from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    return text.replace(old, new, 1)


# Clients authenticate rejoin attempts so the signaling server can retire their
# stale participant record instead of accumulating duplicate migration candidates.
p2p_path = Path("src/P2PManager.cpp")
p2p = p2p_path.read_text(encoding="utf-8")
join_start = p2p.index("    void P2PManager::signalingJoinRoom(")
join_end = p2p.index("    void P2PManager::createHostPeer(", join_start)
join = p2p[join_start:join_end]
join = once(
    join,
    '''        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");''',
    '''        auto req = web::WebRequest();
        req.header("Content-Type", "application/json");
        if (!m_signalingToken.empty()) {
            req.header("Authorization", "Bearer " + m_signalingToken);
        }''',
    "authenticated rejoin",
)
p2p = p2p[:join_start] + join + p2p[join_end:]
p2p_path.write_text(p2p, encoding="utf-8")


server_path = Path("server/signaling/server.ts")
server = server_path.read_text(encoding="utf-8")
server = server.replace("  migratedFromHost: boolean;\n", "", 1)
server = server.replace("  room.migratedFromHost = true;\n", "", 1)
server = server.replace("      migratedFromHost: false,\n", "", 1)

# Rejoin: remove the authenticated stale identity before issuing the new player ID.
server = once(
    server,
    '''      const body = await readJson(req);
      if (!body) return json({ error: "invalid request body" }, 400);

      const playerId = room.nextPlayerId++;''',
    '''      const body = await readJson(req);
      if (!body) return json({ error: "invalid request body" }, 400);

      const previousToken = bearerToken(req);
      const previous = findParticipant(room, previousToken);
      if (previous && previous.token !== room.host.token) {
        room.clients.delete(previous.playerId);
      }

      // Hard server-side safety cap. Room Settings may enforce a lower limit.
      if (room.clients.size >= 31) {
        return json({ error: "room capacity reached" }, 429);
      }

      const playerId = room.nextPlayerId++;''',
    "authenticated rejoin cleanup",
)

old_migrate = '''      // If the requester is already the current host, migration has completed.
      if (requester.token === room.host.token && requester.playerId === 0 && room.migratedFromHost) {
        touch(room, requester);
        return json({
          role: "host",
          playerId: 0,
          sessionToken: room.host.token,
          generation: room.generation,
        });
      }

      if (!room.migratedFromHost) {
        const winner = electMigrationHost(room);
        if (!winner) {
          rooms.delete(roomCode);
          return json({ error: "no migration candidate" }, 410);
        }
        promoteHost(room, winner);
      }

      const current = findParticipant(room, token);
      if (current && current.token === room.host.token) {
        return json({
          role: "host",
          playerId: 0,
          sessionToken: room.host.token,
          generation: room.generation,
        });
      }

      return json({
        role: "client",
        generation: room.generation,
        retryAfterMs: 350,
      });'''
new_migrate = '''      const requestedGeneration = Number(bodyGeneration(req));

      // A request from an earlier generation is observing a migration that has
      // already completed. Never elect twice for the same host failure.
      if (Number.isFinite(requestedGeneration) && requestedGeneration < room.generation) {
        touch(room, requester);
        const isCurrentHost = requester.token === room.host.token;
        return json({
          role: isCurrentHost ? "host" : "client",
          playerId: isCurrentHost ? 0 : requester.playerId,
          sessionToken: isCurrentHost ? room.host.token : requester.token,
          generation: room.generation,
          retryAfterMs: isCurrentHost ? 0 : 350,
        });
      }

      // The current host may query migration status after graceful promotion.
      if (requester.token === room.host.token && requester.playerId === 0) {
        touch(room, requester);
        return json({
          role: "host",
          playerId: 0,
          sessionToken: room.host.token,
          generation: room.generation,
        });
      }

      // Exactly one request for the current generation performs the election.
      const winner = electMigrationHost(room);
      if (!winner) {
        rooms.delete(roomCode);
        return json({ error: "no migration candidate" }, 410);
      }
      promoteHost(room, winner);

      const current = findParticipant(room, token);
      const isCurrentHost = current?.token === room.host.token;
      return json({
        role: isCurrentHost ? "host" : "client",
        playerId: isCurrentHost ? 0 : current?.playerId,
        sessionToken: isCurrentHost ? room.host.token : current?.token,
        generation: room.generation,
        retryAfterMs: isCurrentHost ? 0 : 350,
      });'''

# Migration body must be parsed once so the client generation can gate election.
server = once(
    server,
    '''    if (req.method === "POST" && parts.length === 3 && parts[2] === "migrate") {
      const token = bearerToken(req);
      const requester = findParticipant(room, token);''',
    '''    if (req.method === "POST" && parts.length === 3 && parts[2] === "migrate") {
      const migrationBody = await readJson(req);
      if (!migrationBody) return json({ error: "invalid request body" }, 400);
      const token = bearerToken(req);
      const requester = findParticipant(room, token);''',
    "migration request body",
)
new_migrate = new_migrate.replace("Number(bodyGeneration(req))", "Number(migrationBody.generation ?? room.generation)")
server = once(server, old_migrate, new_migrate, "generation-based migration")

# Remove an unused local from signal routing.
server = server.replace("      const type = message.type as string;\n", "", 1)
server_path.write_text(server, encoding="utf-8")

print("hardened repeatable host migration and authenticated reconnect identity")
