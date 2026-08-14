type SignalMessage = Record<string, unknown>;

type RelayMessage = {
  fromPlayerId: number;
  channel: "reliable" | "unreliable";
  payload: string;
};

type Participant = {
  playerId: number;
  playerName: string;
  token: string;
  joinedAt: number;
  lastSeenAt: number;
  queue: SignalMessage[];
  relayQueue: RelayMessage[];
  transportMode: string;
  relayActive: boolean;
};

type Room = {
  roomId: string;
  roomCode: string;
  createdAt: number;
  lastActivityAt: number;
  generation: number;
  nextPlayerId: number;
  roomName: string;
  description: string;
  playerLimit: number;
  isPrivate: boolean;
  password: string;
  host: Participant;
  clients: Map<number, Participant>;
};

type RateBucket = {
  windowStart: number;
  count: number;
};

const PORT = 8000;
const ROOM_TTL_MS = 2 * 60 * 60 * 1000;
const LONG_POLL_MS = 25_000;
const RELAY_LONG_POLL_MS = 20_000;
const MAX_QUEUE_MESSAGES = 128;
const MAX_RELAY_QUEUE_MESSAGES = 512;
const MAX_RELAY_PAYLOAD_HEX = 96 * 1024;
const MAX_PLAYER_NAME = 32;
const MAX_BODY_BYTES = 128 * 1024;
const MAX_SDP_BYTES = 64 * 1024;
const MAX_CANDIDATE_BYTES = 4 * 1024;
const CREATE_LIMIT_PER_MINUTE = 6;
const JOIN_LIMIT_PER_MINUTE = 40;

const rooms = new Map<string, Room>();
const rateBuckets = new Map<string, RateBucket>();

function now(): number {
  return Date.now();
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function randomHex(bytes: number): string {
  const data = new Uint8Array(bytes);
  crypto.getRandomValues(data);
  return [...data].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function randomRoomCode(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return [...bytes].map((value) => alphabet[value % alphabet.length]).join("");
}

function clientAddress(req: Request): string {
  return req.headers.get("x-real-ip")
    ?? req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
    ?? "unknown";
}

function consumeRateLimit(key: string, limit: number): boolean {
  const current = now();
  const bucket = rateBuckets.get(key);
  if (!bucket || current - bucket.windowStart >= 60_000) {
    rateBuckets.set(key, { windowStart: current, count: 1 });
    return true;
  }
  if (bucket.count >= limit) return false;
  bucket.count += 1;
  return true;
}

async function readJson(req: Request): Promise<Record<string, unknown> | null> {
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (declared > MAX_BODY_BYTES) return null;

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function bearerToken(req: Request): string {
  const value = req.headers.get("authorization") ?? "";
  return value.startsWith("Bearer ") ? value.slice(7).trim() : "";
}

function sanitizePlayerName(value: unknown): string {
  if (typeof value !== "string") return "Player";
  const clean = value.replace(/[\r\n\t]/g, " ").trim().slice(0, MAX_PLAYER_NAME);
  return clean || "Player";
}

function sanitizeTransportMode(value: unknown): string {
  if (typeof value !== "string") return "auto";
  const normalized = value.trim().toLowerCase();
  if (["auto", "webrtc", "turn", "http-relay"].includes(normalized)) return normalized;
  return "auto";
}

function sanitizeRoomText(value: unknown, maxLength: number, fallback = ""): string {
  if (typeof value !== "string") return fallback;
  const clean = value.replace(/[\r\n\t]/g, " ").trim().slice(0, maxLength);
  return clean || fallback;
}

function sanitizePlayerLimit(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 8;
  return Math.max(2, Math.min(16, Math.trunc(numeric)));
}

function sanitizePassword(value: unknown): string {
  return typeof value === "string" ? value.slice(0, 48) : "";
}

function findParticipant(room: Room, token: string): Participant | null {
  if (!token) return null;
  if (room.host.token === token) return room.host;
  for (const participant of room.clients.values()) {
    if (participant.token === token) return participant;
  }
  return null;
}

function touch(room: Room, participant?: Participant | null): void {
  const current = now();
  room.lastActivityAt = current;
  if (participant) participant.lastSeenAt = current;
}

function enqueue(participant: Participant, message: SignalMessage): void {
  participant.queue.push(message);
  if (participant.queue.length > MAX_QUEUE_MESSAGES) {
    participant.queue.splice(0, participant.queue.length - MAX_QUEUE_MESSAGES);
  }
}

function enqueueRelay(participant: Participant, message: RelayMessage): void {
  participant.relayQueue.push(message);
  if (participant.relayQueue.length > MAX_RELAY_QUEUE_MESSAGES) {
    participant.relayQueue.splice(0, participant.relayQueue.length - MAX_RELAY_QUEUE_MESSAGES);
  }
}

async function longPollRelay(participant: Participant): Promise<Response> {
  const deadline = now() + RELAY_LONG_POLL_MS;
  while (participant.relayQueue.length === 0 && now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const messages = participant.relayQueue.splice(0, participant.relayQueue.length);
  return json(messages);
}

function removeExpiredRooms(): void {
  const cutoff = now() - ROOM_TTL_MS;
  for (const [code, room] of rooms) {
    if (room.lastActivityAt < cutoff) rooms.delete(code);
  }

  const rateCutoff = now() - 5 * 60_000;
  for (const [key, bucket] of rateBuckets) {
    if (bucket.windowStart < rateCutoff) rateBuckets.delete(key);
  }
}

function validateSignal(message: Record<string, unknown>): string | null {
  const type = typeof message.type === "string" ? message.type : "";
  if (!["offer", "answer", "candidate"].includes(type)) return "unsupported signal type";

  if ((type === "offer" || type === "answer")) {
    const sdp = typeof message.sdp === "string" ? message.sdp : "";
    if (!sdp || new TextEncoder().encode(sdp).byteLength > MAX_SDP_BYTES) {
      return "invalid SDP";
    }
  }

  if (type === "candidate") {
    const candidate = typeof message.candidate === "string" ? message.candidate : "";
    const mid = typeof message.mid === "string" ? message.mid : "";
    if (!candidate || new TextEncoder().encode(candidate).byteLength > MAX_CANDIDATE_BYTES) {
      return "invalid ICE candidate";
    }
    // sdpMid can legitimately be empty for some libdatachannel/WebRTC paths.
    // Validate its size when present, but never reject an otherwise valid ICE
    // candidate solely because MID is empty.
    if (new TextEncoder().encode(mid).byteLength > 256) {
      return "invalid ICE candidate mid";
    }
  }
  return null;
}

function electMigrationHost(room: Room): Participant | null {
  const candidates = [...room.clients.values()].sort((a, b) => a.playerId - b.playerId);
  return candidates[0] ?? null;
}

function promoteHost(room: Room, winner: Participant): void {
  room.clients.delete(winner.playerId);
  room.generation += 1;
  room.host = {
    ...winner,
    playerId: 0,
    queue: [],
    lastSeenAt: now(),
  };
  room.nextPlayerId = 1;

  // All remaining clients reconnect through /join. Their old records are retained
  // temporarily only so their existing session token can authenticate /migrate.
  for (const client of room.clients.values()) {
    client.queue = [];
    client.relayQueue = [];
  }
  touch(room, room.host);
}

async function longPoll(participant: Participant): Promise<Response> {
  const deadline = now() + LONG_POLL_MS;
  while (participant.queue.length === 0 && now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const messages = participant.queue.splice(0, participant.queue.length);
  return json(messages);
}

async function handle(req: Request): Promise<Response> {
  removeExpiredRooms();

  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const parts = path.split("/").filter(Boolean);

  if (req.method === "GET" && path === "/") {
    return json({
      ok: true,
      service: "Multiplayer Edit X signaling",
      apiVersion: 2,
      rooms: rooms.size,
      transports: ["webrtc", "turn", "http-relay-v1"],
    });
  }

  if (req.method === "GET" && path === "/rooms") {
    const publicRooms = [...rooms.values()]
      .filter((room) => !room.isPrivate)
      .sort((a, b) => b.lastActivityAt - a.lastActivityAt)
      .slice(0, 100)
      .map((room) => ({
        roomCode: room.roomCode,
        roomName: room.roomName,
        description: room.description,
        hostName: room.host.playerName,
        playerCount: room.clients.size + 1,
        playerLimit: room.playerLimit,
        hasPassword: room.password.length > 0,
        transportMode: room.host.transportMode,
        createdAt: room.createdAt,
      }));
    return json(publicRooms);
  }

  if (req.method === "POST" && path === "/rooms") {
    const ip = clientAddress(req);
    if (!consumeRateLimit(`create:${ip}`, CREATE_LIMIT_PER_MINUTE)) {
      return json({ error: "rate limit exceeded" }, 429);
    }

    const body = await readJson(req);
    if (!body) return json({ error: "invalid request body" }, 400);

    let roomCode = randomRoomCode();
    while (rooms.has(roomCode)) roomCode = randomRoomCode();

    const current = now();
    const host: Participant = {
      playerId: 0,
      playerName: sanitizePlayerName(body.playerName),
      token: randomHex(32),
      joinedAt: current,
      lastSeenAt: current,
      queue: [],
      relayQueue: [],
      transportMode: sanitizeTransportMode(body.transportMode),
      relayActive: false,
    };
    const room: Room = {
      roomId: randomHex(16),
      roomCode,
      createdAt: current,
      lastActivityAt: current,
      generation: 1,
      nextPlayerId: 1,
      roomName: sanitizeRoomText(body.roomName, 32, `${host.playerName}'s Room`),
      description: sanitizeRoomText(body.description, 64),
      playerLimit: sanitizePlayerLimit(body.playerLimit),
      isPrivate: body.isPrivate === true,
      password: sanitizePassword(body.password),
      host,
      clients: new Map(),
    };
    rooms.set(roomCode, room);

    return json({
      roomCode,
      roomId: room.roomId,
      playerId: 0,
      sessionToken: host.token,
      generation: room.generation,
      signalingApi: 2,
      relayApi: 1,
      hostTransportMode: host.transportMode,
      roomName: room.roomName,
      isPrivate: room.isPrivate,
      hasPassword: room.password.length > 0,
      playerLimit: room.playerLimit,
    }, 201);
  }

  if (parts.length >= 2 && parts[0] === "rooms") {
    const roomCode = parts[1].toUpperCase();
    const room = rooms.get(roomCode);
    if (!room) return json({ error: "room not found" }, 404);

    if (req.method === "POST" && parts.length === 3 && parts[2] === "join") {
      const ip = clientAddress(req);
      if (!consumeRateLimit(`join:${ip}`, JOIN_LIMIT_PER_MINUTE)) {
        return json({ error: "rate limit exceeded" }, 429);
      }

      const body = await readJson(req);
      if (!body) return json({ error: "invalid request body" }, 400);

      if (room.password.length > 0 && sanitizePassword(body.password) !== room.password) {
        return json({ error: "invalid room password", passwordRequired: true }, 403);
      }

      const previousToken = bearerToken(req);
      const previous = findParticipant(room, previousToken);
      if (previous && previous.token !== room.host.token) {
        room.clients.delete(previous.playerId);
      }

      // Directory-level capacity is enforced before signaling/WebRTC setup.
      // Protocol Room Settings still apply host-side permissions after handshake.
      if (room.clients.size + 1 >= room.playerLimit) {
        return json({ error: "room capacity reached" }, 429);
      }

      const playerId = room.nextPlayerId++;
      const current = now();
      const participant: Participant = {
        playerId,
        playerName: sanitizePlayerName(body.playerName),
        token: randomHex(32),
        joinedAt: current,
        lastSeenAt: current,
        queue: [],
        relayQueue: [],
        transportMode: sanitizeTransportMode(body.transportMode),
        relayActive: false,
      };
      room.clients.set(playerId, participant);
      touch(room, participant);

      enqueue(room.host, {
        type: "client_joined",
        playerId,
        playerName: participant.playerName,
        transportMode: participant.transportMode,
        generation: room.generation,
      });

      return json({
        playerId,
        hostName: room.host.playerName,
        hostPlayerId: 0,
        sessionToken: participant.token,
        generation: room.generation,
        signalingApi: 2,
        relayApi: 1,
        hostTransportMode: room.host.transportMode,
        roomName: room.roomName,
        hasPassword: room.password.length > 0,
        playerLimit: room.playerLimit,
      });
    }

    if (req.method === "POST" && parts.length === 3 && parts[2] === "migrate") {
      const migrationBody = await readJson(req);
      if (!migrationBody) return json({ error: "invalid request body" }, 400);
      const token = bearerToken(req);
      const requester = findParticipant(room, token);
      if (!requester) return json({ error: "unauthorized" }, 401);

      const requestedGeneration = Number(migrationBody.generation ?? room.generation);

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
      });
    }

    if (req.method === "GET" && parts.length === 3 && parts[2] === "relay") {
      const token = bearerToken(req);
      const participant = findParticipant(room, token);
      if (!participant) return json({ error: "unauthorized" }, 401);
      touch(room, participant);
      return await longPollRelay(participant);
    }

    if (req.method === "POST" && parts.length === 3 && parts[2] === "relay") {
      const token = bearerToken(req);
      const sender = findParticipant(room, token);
      if (!sender) return json({ error: "unauthorized" }, 401);

      const body = await readJson(req);
      if (!body) return json({ error: "invalid request body" }, 400);
      const payload = typeof body.payload === "string" ? body.payload : "";
      const channel = body.channel === "unreliable" ? "unreliable" : "reliable";
      if (!payload || payload.length > MAX_RELAY_PAYLOAD_HEX || (payload.length % 2) !== 0 || !/^[0-9a-fA-F]+$/.test(payload)) {
        return json({ error: "invalid relay payload" }, 400);
      }

      if (!sender.relayActive) {
        sender.relayActive = true;
        console.log(`[relay] room=${roomCode} player=${sender.playerId} transport=${sender.transportMode}`);
      }

      const isHost = sender.token === room.host.token;
      if (isHost) {
        const targetId = Number(body.targetPlayerId ?? -1);
        const target = room.clients.get(targetId);
        if (!target) return json({ error: "target client not found" }, 404);
        enqueueRelay(target, { fromPlayerId: 0, channel, payload });
      } else {
        enqueueRelay(room.host, { fromPlayerId: sender.playerId, channel, payload });
      }

      touch(room, sender);
      return json({ ok: true });
    }

    if (req.method === "GET" && parts.length === 3 && parts[2] === "signal") {
      const token = bearerToken(req);
      const participant = findParticipant(room, token);
      if (!participant) return json({ error: "unauthorized" }, 401);

      // The bearer token is the authoritative signaling identity. Do not reject
      // an authenticated long-poll solely because the client's cached role is
      // stale during host migration or reconnect; that created false 403 loops.
      // Routing still uses the participant queue bound to this token.
      touch(room, participant);
      return await longPoll(participant);
    }

    if (req.method === "POST" && parts.length === 3 && parts[2] === "signal") {
      const token = bearerToken(req);
      const sender = findParticipant(room, token);
      if (!sender) return json({ error: "unauthorized" }, 401);

      const message = await readJson(req);
      if (!message) return json({ error: "invalid request body" }, 400);
      const validationError = validateSignal(message);
      if (validationError) return json({ error: validationError }, 400);

      const isHost = sender.token === room.host.token;

      if (isHost) {
        const targetId = Number(message.targetPlayerId ?? -1);
        const target = room.clients.get(targetId);
        if (!target) return json({ error: "target client not found" }, 404);
        enqueue(target, { ...message, generation: room.generation });
      } else {
        const { targetPlayerId: _ignoredTarget, ...forwarded } = message;
        const normalized: SignalMessage = {
          ...forwarded,
          playerId: sender.playerId,
          generation: room.generation,
        };
        enqueue(room.host, normalized);
      }

      touch(room, sender);
      return json({ ok: true });
    }

    if (req.method === "DELETE" && parts.length === 2) {
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
    }
  }

  return json({ error: "not found" }, 404);
}

Deno.serve({ hostname: "127.0.0.1", port: PORT }, async (req) => {
  try {
    return await handle(req);
  } catch (error) {
    console.error("signaling request failed", error);
    return json({ error: "internal server error" }, 500);
  }
});
