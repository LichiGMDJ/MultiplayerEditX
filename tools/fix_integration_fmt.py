from pathlib import Path

path = Path('src/P2PManager.cpp')
text = path.read_text(encoding='utf-8')
old = '''            log::warn(\n                forceRelay && !network.forceTurnTransport()\n                    ? "P2PManager: stable WebRTC path failed; retrying through configured TURN/UDP"\n                    : "P2PManager: TURN relay transport selected"\n            );'''
new = '''            if (forceRelay && !network.forceTurnTransport()) {\n                log::warn("P2PManager: stable WebRTC path failed; retrying through configured TURN/UDP");\n            } else {\n                log::warn("P2PManager: TURN relay transport selected");\n            }'''
if old not in text:
    raise SystemExit('fmt ternary logger block not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('fmt logger compile fix applied')
