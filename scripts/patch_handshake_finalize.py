from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: expected source block was not found; refusing to patch")
    return text.replace(old, new, 1)


hpp_path = Path("src/P2PManager.hpp")
hpp = hpp_path.read_text(encoding="utf-8")

hpp = replace_once(
    hpp,
    '''            bool reconnecting = false;''',
    '''            bool reconnecting = false;
            bool connectionAnnounced = false;''',
    "peer handshake announcement state",
)

hpp = replace_once(
    hpp,
    '''        void scheduleClientReconnect();
        void checkPeerReady(int playerId);''',
    '''        void scheduleClientReconnect();
        void finalizePeerHandshake(int playerId);
        void checkPeerReady(int playerId);''',
    "handshake finalize declaration",
)

hpp_path.write_text(hpp, encoding="utf-8")


cpp_path = Path("src/P2PManager.cpp")
cpp = cpp_path.read_text(encoding="utf-8")

# Protocol verification is the actual session-ready boundary. Finalize callbacks
# only after the remote hello has been accepted.
cpp = replace_once(
    cpp,
    '''            log::info(
                "P2PManager: protocol v{} verified for player {} (replaying {} buffered packets)",
                hello.protocolVersion,
                fromPlayerId,
                buffered.size()
            );

            for (auto const& packet : buffered) {''',
    '''            log::info(
                "P2PManager: protocol v{} verified for player {} (replaying {} buffered packets)",
                hello.protocolVersion,
                fromPlayerId,
                buffered.size()
            );

            // Data channels being open is not enough to expose the peer to the
            // editor. Only a mutually compatible protocol handshake may release
            // pending editor traffic and fire Session/Peer callbacks.
            finalizePeerHandshake(fromPlayerId);

            for (auto const& packet : buffered) {''',
    "finalize only after protocol hello",
)

new_functions = '''    void P2PManager::finalizePeerHandshake(int playerId) {
        int pid = -1;
        std::string name;
        int colorIdx = 0;
        std::vector<PendingMessage> pending;

        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) return;

            auto& peer = it->second;
            if (!peer.ready || !peer.protocolVerified || peer.connectionAnnounced) return;

            peer.connectionAnnounced = true;
            pid = peer.playerId;
            name = peer.playerName;
            colorIdx = peer.colorIndex;
            pending = std::move(peer.pendingMessages);
            peer.pendingMessages.clear();
        }

        log::info(
            "P2PManager: protocol handshake complete for player {}; releasing {} pending messages",
            pid,
            pending.size()
        );

        // Release packets only after protocol compatibility is known.
        for (auto& msg : pending) {
            sendTo(pid, msg.data, msg.channel);
        }

        if (m_role == Role::Client && pid == 0) {
            m_state.store(State::Connected);
            m_reconnectAttempts = 0;
            m_reconnectScheduled.store(false);
            stopSignalPolling();
        }

        queueInMainThread([this, pid, name, colorIdx]() {
            if (m_role == Role::Client && pid == 0) {
                auto roomCode = getRoomCode();
                for (auto& cb : m_onSessionStarted) {
                    cb(roomCode, m_localPlayerId);
                }
            }

            for (auto& cb : m_onPeerConnected) {
                cb(pid, name, colorIdx);
            }

            if (m_role == Role::Host) {
                auto msg = proto::serializePlayerJoined(pid, name, colorIdx);
                broadcast(msg, ChannelType::Reliable, pid);
            }
        });
    }

    void P2PManager::checkPeerReady(int playerId) {
        bool becameTransportReady = false;
        int pid = -1;
        std::string name;

        {
            std::lock_guard lock(m_peersMutex);
            auto it = m_peers.find(playerId);
            if (it == m_peers.end()) return;

            auto& peer = it->second;
            bool reliableOpen = peer.reliable && peer.reliable->isOpen();
            bool unreliableOpen = peer.unreliable && peer.unreliable->isOpen();

            if (reliableOpen && unreliableOpen && !peer.ready) {
                peer.ready = true;
                pid = peer.playerId;
                name = peer.playerName;
                becameTransportReady = true;
                log::info(
                    "P2PManager: transport ready for player {} ({}); waiting for protocol handshake",
                    pid,
                    name
                );
            }
        }

        if (!becameTransportReady) return;

        // Hello is deliberately immediate/control traffic and is never put into
        // the editor reliable FIFO. The peer is not announced yet.
        auto hello = proto::serializeProtocolHello(kProtocolVersion);
        sendTo(pid, hello, ChannelType::Reliable);
    }


'''

# Previous reliability/reconnect patches legitimately edit checkPeerReady(), so
# do not require an exact copy of its body. Replace the function by its stable
# declaration boundary instead. This still refuses to patch if either boundary
# is missing or appears in an unexpected order.
start_marker = "    void P2PManager::checkPeerReady(int playerId) {"
end_marker = "    void P2PManager::leaveSession() {"
start = cpp.find(start_marker)
end = cpp.find(end_marker, start + len(start_marker)) if start != -1 else -1
if start == -1 or end == -1 or end <= start:
    raise SystemExit("protocol-gated peer finalization: checkPeerReady/leaveSession boundaries not found; refusing to patch")

cpp = cpp[:start] + new_functions + cpp[end:]

cpp_path.write_text(cpp, encoding="utf-8")
print("Patched transport-ready vs protocol-ready state machine")
