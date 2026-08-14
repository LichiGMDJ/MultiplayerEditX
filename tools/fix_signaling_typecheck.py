from pathlib import Path

path = Path("server/signaling/server.ts")
text = path.read_text(encoding="utf-8")
old = '''      } else {
        const normalized = { ...message, playerId: sender.playerId, generation: room.generation };
        delete normalized.targetPlayerId;
        enqueue(room.host, normalized);
      }
'''
new = '''      } else {
        const { targetPlayerId: _ignoredTarget, ...forwarded } = message;
        const normalized: SignalMessage = {
          ...forwarded,
          playerId: sender.playerId,
          generation: room.generation,
        };
        enqueue(room.host, normalized);
      }
'''
if old not in text:
    raise SystemExit("target block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
