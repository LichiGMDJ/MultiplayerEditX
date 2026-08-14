from pathlib import Path
import json

mod = json.loads(Path('mod.json').read_text(encoding='utf-8'))
assert mod['geode'] == '5.9.0'
assert mod['id'] == 'lichigmdj.multiplayereditx'
assert mod['version'] == '0.5.3'
mode = mod['settings']['connection-mode']
assert mode['one-of'] == ['Auto', 'WebRTC', 'TURN', 'HTTP Relay']

p2p = Path('src/P2PManager.cpp').read_text(encoding='utf-8')
network = Path('src/net/NetworkConfig.hpp').read_text(encoding='utf-8')
hooks = Path('src/EditorHooks.cpp').read_text(encoding='utf-8')
remote = Path('src/RemoteActionHandler.cpp').read_text(encoding='utf-8')
proto = Path('src/net/ProtocolCapabilities.hpp').read_text(encoding='utf-8')
server = Path('server/signaling/server.ts').read_text(encoding='utf-8')

for token in ['ConnectionMode::Auto', 'ConnectionMode::WebRTC', 'ConnectionMode::Turn', 'ConnectionMode::HttpRelay']:
    assert token in network
assert 'stable 0.5.0 WebRTC direct/STUN' in p2p
assert 'checkPeerReady(fromId);' in p2p
assert 'checkPeerReady(playerId);' in p2p
assert 'HTTP relay long poll idle timeout; retrying' in p2p
assert 'signaling POST {} failed' in p2p
assert 'hostTransportMode' in p2p
assert 'transportMode' in server
assert 'RELAY_LONG_POLL_MS = 20_000' in server

assert 'kCurrentProtocol = 8' in proto
for token in ['ReliableAcks', 'EditorLayers', 'RawBulkPaste', 'RoomSettings', 'GlobalRevision', 'TargetedRepair', 'AdaptiveSync', 'HostMigration', 'SecureSignaling']:
    assert token in proto
for token in ['ReliableEnvelope', 'GlobalRevision', 'RoomSettingsChanged', 'requestHostMigration']:
    assert token in p2p

for token in [
    's_startPosObjects', 's_startPosSaveStrings', 'm_objectID == 31',
    'encodeLayerTaggedUuid', 'objectLayerSyncState', 'serializeSyncLevelStart',
    'serializeSyncLevelChunk', 'serializeSyncLevelEnd', 'serializeBulkPasteStart',
    'serializeBulkPasteChunk', 'serializeBulkPasteEnd', 'serializePlaceObjects',
    'serializeDeleteObjects', 'serializeMoveObjects', 'serializeUpdateObjects',
    'serializeReconcileObjects', 'AdaptiveSyncPolicy', 'SYNC PERF',
]:
    assert token in hooks, token
for token in ['decodeLayerTaggedUuid', 'applyEditorLayers', 'applyPendingSync', 'InitialSyncRequest']:
    assert token in remote, token

print('upstream 0.5.0 integration invariants verified')
