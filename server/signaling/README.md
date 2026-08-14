# Multiplayer Edit X signaling service

Production signaling API for Multiplayer Edit X 0.5.3+.

## Design

- Long-poll HTTP signaling for SDP/ICE exchange.
- Bearer `sessionToken` authentication after room create/join.
- Cryptographically random room/session identifiers.
- Room inactivity TTL and bounded per-player signal queues.
- Per-IP create/join rate limiting.
- Request, SDP and ICE-candidate size limits.
- Server-assisted host migration while keeping the same room code.
- The service never relays editor/game data; WebRTC or TURN carries peer traffic.

The production server binds to `127.0.0.1:8000` and is intended to run behind nginx TLS.

## Run

```sh
deno run --allow-net server.ts
```

## Main endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/rooms` | Create a room and host session token |
| POST | `/rooms/:code/join` | Join and receive a client session token |
| GET | `/rooms/:code/signal` | Authenticated long poll |
| POST | `/rooms/:code/signal` | Authenticated SDP/ICE delivery |
| POST | `/rooms/:code/migrate` | Resolve/promote the next host after host loss |
| DELETE | `/rooms/:code` | Host leaves; migrates if clients remain, closes otherwise |
| GET | `/` | Health/status response |
