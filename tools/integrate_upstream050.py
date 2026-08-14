from pathlib import Path
import json
import re

ROOT = Path('.')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f'[{label}] expected block not found')
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f'[{label}] expected 1 match, got {count}')
    return out

mod_path = ROOT / 'mod.json'
mod = json.loads(mod_path.read_text(encoding='utf-8'))
mod['geode'] = '5.9.0'
mod['description'] = (
    'Fork of Multiplayer Edit by xXoanon, retaining the stable 0.5.0 editor/WebRTC '
    'lifecycle while extending synchronization, reliability, Room Settings, and '
    'selectable WebRTC/TURN/HTTP relay transports.'
)
for tag in ['utility', 'interface', 'content']:
    if tag not in mod.setdefault('tags', []):
        mod['tags'].append(tag)
settings = mod['settings']
new_settings = {}
inserted_mode = False
for key, value in settings.items():
    new_settings[key] = value
    if key == 'signaling-url':
        new_settings['connection-mode'] = {
            'type': 'string',
            'name': 'Connection Mode',
            'description': (
                'Auto prefers the stable direct/STUN WebRTC path, retries through configured TURN when available, '
                'then falls back to HTTP Relay. WebRTC disables relay fallback. TURN forces configured TURN/UDP. '
                'HTTP Relay connects through the signaling server immediately.'
            ),
            'default': 'Auto',
            'one-of': ['Auto', 'WebRTC', 'TURN', 'HTTP Relay'],
        }
        inserted_mode = True
if not inserted_mode:
    raise SystemExit('[mod.json] signaling-url setting not found')
mod['settings'] = new_settings
mod_path.write_text(json.dumps(mod, indent=4, ensure_ascii=False) + '\n', encoding='utf-8')

(ROOT / 'src/net/NetworkConfig.hpp').write_text(r'''#pragma once

#include <string>

namespace mpedit::net {

    enum class ConnectionMode {
        Auto,
        WebRTC,
        Turn,
        HttpRelay,
    };

    struct NetworkConfig {
        std::string signalingUrl;
        std::string turnHost;
        std::string turnUsername;
        std::string turnPassword;
        bool forceTurnRelay = false;
        ConnectionMode connectionMode = ConnectionMode::Auto;

        bool hasSignaling() const { return !signalingUrl.empty(); }
        bool hasTurn() const {
            return !turnHost.empty() && !turnUsername.empty() && !turnPassword.empty();
        }

        bool httpRelayImmediate() const { return connectionMode == ConnectionMode::HttpRelay; }
        bool allowsHttpRelayFallback() const {
            return connectionMode == ConnectionMode::Auto || connectionMode == ConnectionMode::HttpRelay;
        }
        bool forceTurnTransport() const {
            return forceTurnRelay || connectionMode == ConnectionMode::Turn;
        }
        bool directWebRtcOnly() const { return connectionMode == ConnectionMode::WebRTC; }
        std::string transportModeName() const;

        static ConnectionMode parseConnectionMode(std::string value);
        static NetworkConfig load();
    };

} // namespace mpedit::net
''', encoding='utf-8')

(ROOT / 'src/net/NetworkConfig.cpp').write_text(r'''#include "NetworkConfig.hpp"

#include <Geode/loader/Mod.hpp>
#include <algorithm>
#include <cctype>

using namespace geode::prelude;

namespace mpedit::net {

    ConnectionMode NetworkConfig::parseConnectionMode(std::string value) {
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        if (value == "webrtc") return ConnectionMode::WebRTC;
        if (value == "turn") return ConnectionMode::Turn;
        if (value == "http relay" || value == "http-relay" || value == "http_relay") {
            return ConnectionMode::HttpRelay;
        }
        return ConnectionMode::Auto;
    }

    std::string NetworkConfig::transportModeName() const {
        switch (connectionMode) {
            case ConnectionMode::WebRTC: return "webrtc";
            case ConnectionMode::Turn: return "turn";
            case ConnectionMode::HttpRelay: return "http-relay";
            case ConnectionMode::Auto:
            default: return "auto";
        }
    }

    NetworkConfig NetworkConfig::load() {
        auto* mod = Mod::get();

        NetworkConfig config;
        config.signalingUrl = mod->getSettingValue<std::string>("signaling-url");
        while (config.signalingUrl.size() > 1 && config.signalingUrl.back() == '/') {
            config.signalingUrl.pop_back();
        }
        config.turnHost = mod->getSettingValue<std::string>("turn-host");
        config.turnUsername = mod->getSettingValue<std::string>("turn-username");
        config.turnPassword = mod->getSettingValue<std::string>("turn-password");
        config.forceTurnRelay = mod->getSettingValue<bool>("force-turn-relay");
        config.connectionMode = parseConnectionMode(
            mod->getSettingValue<std::string>("connection-mode")
        );
        return config;
    }

} // namespace mpedit::net
''', encoding='utf-8')

p2p_path = ROOT / 'src/P2PManager.cpp'
p2p = p2p_path.read_text(encoding='utf-8')

p2p = regex_once(
    p2p,
    r'    rtc::Configuration P2PManager::makeRtcConfig\(bool forceRelay\) \{.*?\n    \}\n\n    std::string P2PManager::getSignalingUrl\(\) \{',
    r'''    rtc::Configuration P2PManager::makeRtcConfig(bool forceRelay) {
        rtc::Configuration config;
        auto network = net::NetworkConfig::load();

        // Keep the proven upstream 0.5.0 direct/STUN path unchanged whenever
        // WebRTC is enabled. Transport selection only layers policy on top.
        if (!network.httpRelayImmediate()) {
            config.iceServers.push_back({"stun:stun.l.google.com:19302"});
            config.iceServers.push_back({"stun:stun.cloudflare.com:3478"});
        }

        bool customTurnAvailable = network.hasTurn();
        bool allowConfiguredTurn =
            network.connectionMode == net::ConnectionMode::Auto ||
            network.connectionMode == net::ConnectionMode::Turn ||
            network.forceTurnRelay || forceRelay;

        if (customTurnAvailable && allowConfiguredTurn) {
            rtc::IceServer customTurn(
                network.turnHost, 3478, network.turnUsername, network.turnPassword,
                rtc::IceServer::RelayType::TurnUdp
            );
            config.iceServers.push_back(customTurn);
        }

        bool relayOnly = network.forceTurnTransport() || forceRelay;
        if (relayOnly && customTurnAvailable) {
            config.iceTransportPolicy = rtc::TransportPolicy::Relay;
            log::warn(
                forceRelay && !network.forceTurnTransport()
                    ? "P2PManager: stable WebRTC path failed; retrying through configured TURN/UDP"
                    : "P2PManager: TURN relay transport selected"
            );
        } else if (network.httpRelayImmediate()) {
            log::info("P2PManager: HTTP Relay transport selected; ICE will not be used");
        } else if (network.directWebRtcOnly()) {
            log::info("P2PManager: stable 0.5.0 WebRTC direct/STUN transport selected");
        } else if (customTurnAvailable) {
            log::info("P2PManager: stable 0.5.0 WebRTC direct/STUN path with TURN/UDP fallback available");
        } else {
            log::info("P2PManager: stable 0.5.0 WebRTC direct/STUN path; HTTP Relay fallback available");
        }

        return config;
    }

    std::string P2PManager::getSignalingUrl() {''',
    'makeRtcConfig',
)

p2p = replace_once(
    p2p,
    '''        req.bodyJSON(msg);\n        async::spawn(req.post(url));\n    }\n\n    void P2PManager::handleSignalingMessages''',
    '''        req.bodyJSON(msg);\n        async::spawn(\n            req.post(url),\n            [url](web::WebResponse res) {\n                if (!res.ok()) {\n                    log::warn(\n                        "P2PManager: signaling POST {} failed code={} error={}",\n                        url, res.code(), res.errorMessage()\n                    );\n                }\n            }\n        );\n    }\n\n    void P2PManager::handleSignalingMessages''',
    'signaling POST logging',
)

p2p = replace_once(
    p2p,
    '''        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);\n        req.bodyJSON(body);''',
    '''        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);\n        body["transportMode"] = net::NetworkConfig::load().transportModeName();\n        req.bodyJSON(body);''',
    'host transport advertisement',
)

p2p = replace_once(
    p2p,
    '''                    startSignalPolling(roomCode, "host", 0);\n                    startHttpRelayPolling(roomCode);''',
    '''                    startSignalPolling(roomCode, "host", 0);\n                    if (net::NetworkConfig::load().allowsHttpRelayFallback()) {\n                        startHttpRelayPolling(roomCode);\n                    }''',
    'host cold relay polling',
)

p2p = replace_once(
    p2p,
    '''                if (clientId >= 0) {\n                    log::info("P2PManager: Client {} ({}) connecting via signal poll", clientId, clientName);\n                    m_nextPlayerId = std::max(m_nextPlayerId, clientId + 1);\n                    createHostPeer(clientId, clientName);\n                }''',
    '''                if (clientId >= 0) {\n                    auto clientTransport = msg.get<std::string>("transportMode").unwrapOr("auto");\n                    auto network = net::NetworkConfig::load();\n                    log::info(\n                        "P2PManager: Client {} ({}) connecting via signal poll (transport={})",\n                        clientId, clientName, clientTransport\n                    );\n                    m_nextPlayerId = std::max(m_nextPlayerId, clientId + 1);\n\n                    bool immediateHttpRelay =\n                        network.httpRelayImmediate() || clientTransport == "http-relay";\n                    if (immediateHttpRelay) {\n                        PeerInfo peer;\n                        peer.playerId = clientId;\n                        peer.playerName = clientName;\n                        peer.colorIndex = clientId % 6;\n                        {\n                            std::lock_guard lock(m_peersMutex);\n                            m_peers[clientId] = std::move(peer);\n                        }\n                        startHttpRelayPolling(getRoomCode());\n                        activateHttpRelayForPeer(clientId);\n                    } else {\n                        createHostPeer(clientId, clientName);\n                    }\n                }''',
    'host HTTP peer selection',
)

p2p = replace_once(
    p2p,
    '''    void P2PManager::hostSession(std::string const& playerName) {\n        {''',
    '''    void P2PManager::hostSession(std::string const& playerName) {\n        auto selectedNetwork = net::NetworkConfig::load();\n        if (selectedNetwork.connectionMode == net::ConnectionMode::Turn && !selectedNetwork.hasTurn()) {\n            m_state.store(State::Error);\n            m_error = "TURN mode requires TURN host, username and password";\n            for (auto& cb : m_onError) cb(m_error);\n            return;\n        }\n        {''',
    'host TURN validation',
)

p2p = replace_once(
    p2p,
    '''    void P2PManager::joinSession(std::string const& roomCode, std::string const& playerName) {\n        {''',
    '''    void P2PManager::joinSession(std::string const& roomCode, std::string const& playerName) {\n        auto selectedNetwork = net::NetworkConfig::load();\n        if (selectedNetwork.connectionMode == net::ConnectionMode::Turn && !selectedNetwork.hasTurn()) {\n            m_state.store(State::Error);\n            m_error = "TURN mode requires TURN host, username and password";\n            for (auto& cb : m_onError) cb(m_error);\n            return;\n        }\n        {''',
    'client TURN validation',
)

p2p = replace_once(
    p2p,
    '''        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);\n        req.bodyJSON(body);''',
    '''        body["capabilities"] = static_cast<double>(net::kLocalCapabilities);\n        body["transportMode"] = net::NetworkConfig::load().transportModeName();\n        req.bodyJSON(body);''',
    'client transport advertisement',
)

p2p = replace_once(
    p2p,
    '''                    auto hostName = json.get<std::string>("hostName").unwrapOr("Host");\n                    m_signalingToken =''',
    '''                    auto hostName = json.get<std::string>("hostName").unwrapOr("Host");\n                    auto hostTransportMode = json.get<std::string>("hostTransportMode").unwrapOr("auto");\n                    m_signalingToken =''',
    'host transport response',
)

p2p = replace_once(
    p2p,
    '''                    log::info("P2PManager: Joined room {} as player {}", roomCode, m_localPlayerId);\n\n                    bool relayRetry = m_forceRelayNextJoin.exchange(false);\n                    auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig(relayRetry));''',
    '''                    log::info(\n                        "P2PManager: Joined room {} as player {} (host transport={})",\n                        roomCode, m_localPlayerId, hostTransportMode\n                    );\n\n                    auto network = net::NetworkConfig::load();\n                    bool immediateHttpRelay =\n                        network.httpRelayImmediate() || hostTransportMode == "http-relay";\n                    if (immediateHttpRelay) {\n                        PeerInfo hostPeer;\n                        hostPeer.playerId = 0;\n                        hostPeer.playerName = hostName;\n                        hostPeer.colorIndex = 0;\n                        {\n                            std::lock_guard lock(m_peersMutex);\n                            m_peers[0] = std::move(hostPeer);\n                        }\n                        startSignalPolling(roomCode, "client", m_localPlayerId);\n                        startHttpRelayPolling(roomCode);\n                        activateHttpRelayForPeer(0);\n                        return;\n                    }\n\n                    bool relayRetry = m_forceRelayNextJoin.exchange(false);\n                    auto pc = std::make_shared<rtc::PeerConnection>(makeRtcConfig(relayRetry));''',
    'client immediate HTTP relay',
)

p2p = replace_once(
    p2p,
    '''                            if (!transportReady && !relayRetry && !network.forceTurnRelay && network.hasTurn()) {''',
    '''                            if (\n                                network.connectionMode == net::ConnectionMode::Auto &&\n                                !transportReady && !relayRetry && !network.forceTurnRelay && network.hasTurn()\n                            ) {''',
    'auto TURN retry policy',
)

p2p = replace_once(
    p2p,
    '''                    startSignalPolling(roomCode, "client", m_localPlayerId);\n                    startHttpRelayPolling(roomCode);\n                    scheduleHttpRelayFallback(0);''',
    '''                    startSignalPolling(roomCode, "client", m_localPlayerId);\n                    if (network.connectionMode == net::ConnectionMode::Auto) {\n                        scheduleHttpRelayFallback(0);\n                    }''',
    'client cold relay polling',
)

p2p = replace_once(
    p2p,
    '''    void P2PManager::startHttpRelayPolling(std::string const& code) {\n        m_httpRelayPollingActive.store(true);\n        pollHttpRelayOnce(code);\n    }''',
    '''    void P2PManager::startHttpRelayPolling(std::string const& code) {\n        if (m_httpRelayPollingActive.exchange(true)) return;\n        log::info("P2PManager: Starting HTTP relay long poll");\n        pollHttpRelayOnce(code);\n    }''',
    'relay poll guard',
)

p2p = replace_once(
    p2p,
    '''        req.timeout(std::chrono::seconds(30));\n        auto url = getSignalingUrl() + "/rooms/" + code + "/relay";''',
    '''        req.timeout(std::chrono::seconds(35));\n        auto url = getSignalingUrl() + "/rooms/" + code + "/relay";''',
    'relay timeout headroom',
)
p2p = replace_once(
    p2p,
    '''                } else {\n                    log::warn("P2PManager: HTTP relay poll returned {}", res.code());\n                }\n\n                if (m_httpRelayPollingActive.load()) pollHttpRelayOnce(code);''',
    '''                } else if (res.code() == -28) {\n                    log::debug("P2PManager: HTTP relay long poll idle timeout; retrying");\n                } else {\n                    log::warn(\n                        "P2PManager: HTTP relay poll returned {} error={}",\n                        res.code(), res.errorMessage()\n                    );\n                }\n\n                if (m_httpRelayPollingActive.load()) pollHttpRelayOnce(code);''',
    'relay timeout handling',
)

p2p = replace_once(
    p2p,
    '''        auto url = getSignalingUrl() + "/rooms/" + getRoomCode() + "/relay";\n        async::spawn(req.post(url));\n    }''',
    '''        auto url = getSignalingUrl() + "/rooms/" + getRoomCode() + "/relay";\n        async::spawn(\n            req.post(url),\n            [playerId](web::WebResponse res) {\n                if (!res.ok()) {\n                    log::warn(\n                        "P2PManager: HTTP relay POST to player {} failed code={} error={}",\n                        playerId, res.code(), res.errorMessage()\n                    );\n                }\n            }\n        );\n    }''',
    'relay POST logging',
)

p2p = replace_once(
    p2p,
    '''                if (!it->second.httpRelay) {\n                    it->second.httpRelay = true;\n                    it->second.ready = true;\n                    newlyRelayed = true;\n                }''',
    '''                if (!it->second.httpRelay) {\n                    it->second.httpRelay = true;\n                    newlyRelayed = true;\n                }''',
    'relay receive readiness',
)
p2p = replace_once(
    p2p,
    '''            if (newlyRelayed) {\n                log::warn("P2PManager: peer {} switched to HTTP relay transport", fromId);\n            }\n\n            onPeerMessage(fromId, payload.data(), payload.size());''',
    '''            if (newlyRelayed) {\n                log::warn("P2PManager: peer {} switched to HTTP relay transport", fromId);\n                checkPeerReady(fromId);\n            }\n\n            onPeerMessage(fromId, payload.data(), payload.size());''',
    'relay receive ProtocolHello',
)

p2p = replace_once(
    p2p,
    '''            if (it->second.connectionAnnounced || it->second.httpRelay) return;\n            it->second.httpRelay = true;\n            it->second.ready = true;\n            activate = true;''',
    '''            if (it->second.connectionAnnounced || it->second.httpRelay) return;\n            it->second.httpRelay = true;\n            activate = true;''',
    'relay activation readiness',
)
p2p = replace_once(
    p2p,
    '''        log::warn("P2PManager: WebRTC not ready; activating HTTP relay transport for player {}", playerId);\n        auto hello = proto::serializeProtocolHello(net::kCurrentProtocol, net::kLocalCapabilities);\n        sendTo(playerId, hello, ChannelType::Reliable);''',
    '''        log::warn("P2PManager: activating HTTP relay transport for player {}", playerId);\n        startHttpRelayPolling(getRoomCode());\n        checkPeerReady(playerId);''',
    'relay activation ProtocolHello',
)

p2p = replace_once(
    p2p,
    '''    void P2PManager::scheduleHttpRelayFallback(int playerId) {\n        std::thread([this, playerId]() {''',
    '''    void P2PManager::scheduleHttpRelayFallback(int playerId) {\n        if (net::NetworkConfig::load().connectionMode != net::ConnectionMode::Auto) return;\n        std::thread([this, playerId]() {''',
    'relay fallback policy',
)

p2p_path.write_text(p2p, encoding='utf-8')

server_path = ROOT / 'server/signaling/server.ts'
server = server_path.read_text(encoding='utf-8')
server = replace_once(server, '''  relayQueue: RelayMessage[];\n};''', '''  relayQueue: RelayMessage[];\n  transportMode: string;\n  relayActive: boolean;\n};''', 'server participant transport fields')
server = replace_once(server, '''const LONG_POLL_MS = 25_000;\nconst MAX_QUEUE_MESSAGES''', '''const LONG_POLL_MS = 25_000;\nconst RELAY_LONG_POLL_MS = 20_000;\nconst MAX_QUEUE_MESSAGES''', 'relay long poll constant')
server = replace_once(
    server,
    '''function sanitizePlayerName(value: unknown): string {\n  if (typeof value !== "string") return "Player";\n  const clean = value.replace(/[\\r\\n\\t]/g, " ").trim().slice(0, MAX_PLAYER_NAME);\n  return clean || "Player";\n}\n\nfunction findParticipant''',
    '''function sanitizePlayerName(value: unknown): string {\n  if (typeof value !== "string") return "Player";\n  const clean = value.replace(/[\\r\\n\\t]/g, " ").trim().slice(0, MAX_PLAYER_NAME);\n  return clean || "Player";\n}\n\nfunction sanitizeTransportMode(value: unknown): string {\n  if (typeof value !== "string") return "auto";\n  const normalized = value.trim().toLowerCase();\n  if (["auto", "webrtc", "turn", "http-relay"].includes(normalized)) return normalized;\n  return "auto";\n}\n\nfunction findParticipant''',
    'server transport sanitizer',
)
server = replace_once(server, '''  const deadline = now() + LONG_POLL_MS;\n  while (participant.relayQueue.length === 0 && now() < deadline) {''', '''  const deadline = now() + RELAY_LONG_POLL_MS;\n  while (participant.relayQueue.length === 0 && now() < deadline) {''', 'server relay long poll')
server = replace_once(server, '''      transports: ["webrtc", "http-relay-v1"],''', '''      transports: ["webrtc", "turn", "http-relay-v1"],''', 'server transport advertisement')
server = replace_once(server, '''      queue: [],\n      relayQueue: [],\n    };\n    const room: Room = {''', '''      queue: [],\n      relayQueue: [],\n      transportMode: sanitizeTransportMode(body.transportMode),\n      relayActive: false,\n    };\n    const room: Room = {''', 'host participant mode')
server = replace_once(server, '''      relayApi: 1,\n    }, 201);''', '''      relayApi: 1,\n      hostTransportMode: host.transportMode,\n    }, 201);''', 'create transport response')
server = replace_once(server, '''        queue: [],\n        relayQueue: [],\n      };\n      room.clients.set(playerId, participant);''', '''        queue: [],\n        relayQueue: [],\n        transportMode: sanitizeTransportMode(body.transportMode),\n        relayActive: false,\n      };\n      room.clients.set(playerId, participant);''', 'client participant mode')
server = replace_once(server, '''        playerName: participant.playerName,\n        generation: room.generation,''', '''        playerName: participant.playerName,\n        transportMode: participant.transportMode,\n        generation: room.generation,''', 'client joined transport mode')
server = replace_once(server, '''        relayApi: 1,\n      });''', '''        relayApi: 1,\n        hostTransportMode: room.host.transportMode,\n      });''', 'join transport response')
server = replace_once(server, '''      const isHost = sender.token === room.host.token;\n      if (isHost) {''', '''      if (!sender.relayActive) {\n        sender.relayActive = true;\n        console.log(`[relay] room=${roomCode} player=${sender.playerId} transport=${sender.transportMode}`);\n      }\n\n      const isHost = sender.token === room.host.token;\n      if (isHost) {''', 'relay activation logging')
server_path.write_text(server, encoding='utf-8')

workflow = r'''name: Build Upstream 0.5.0 Integration

on:
  push:
    branches:
      - v053-upstream050-integration
    paths-ignore:
      - 'tools/integration-smoke.trigger'

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify integration invariants
        run: |
          python3 tools/verify_upstream050_integration.py
          git diff --check
      - name: Typecheck signaling server
        uses: denoland/setup-deno@v2
        with:
          deno-version: v2.x
      - run: deno check server/signaling/server.ts

  build:
    needs: verify
    strategy:
      fail-fast: false
      matrix:
        include:
          - name: Windows64
            os: windows-latest
            target: Win64
          - name: Android64
            os: ubuntu-latest
            target: Android64
    name: ${{ matrix.name }}
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - name: Build
        id: build
        uses: geode-sdk/build-geode-mod@main
        with:
          sdk: 5.9.0
          target: ${{ matrix.target }}
          build-config: Release
          android-min-sdk: 23
          configure-args: -DCMAKE_POLICY_VERSION_MINIMUM=3.5
          combine: true

  package:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Combine Win64 + Android64
        id: combine
        uses: geode-sdk/build-geode-mod/combine@main
      - uses: actions/upload-artifact@v4
        with:
          name: lichigmdj.multiplayereditx-0.5.3-upstream050-integration
          path: ${{ steps.combine.outputs.build-output }}
'''
(ROOT / '.github/workflows/integration-build.yml').write_text(workflow, encoding='utf-8')

verify = r'''from pathlib import Path
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
'''
(ROOT / 'tools/verify_upstream050_integration.py').write_text(verify, encoding='utf-8')

print('integration patch applied')
