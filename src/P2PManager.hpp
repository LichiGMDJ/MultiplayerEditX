#pragma once

#include "BinaryProtocol.hpp"
#include "net/ProtocolCapabilities.hpp"
#include <Geode/utils/web.hpp>
#include <Geode/utils/async.hpp>
#include <string>
#include <functional>
#include <unordered_map>
#include <mutex>
#include <queue>
#include <vector>
#include <memory>
#include <atomic>
#include <unordered_set>
#include <deque>
#include <cstdint>

namespace rtc {
    class PeerConnection;
    class DataChannel;
    struct Configuration;
}

namespace mpedit {

    enum class ChannelType {
        Reliable,    // ordered, reliable — edits, sync, locks
        Unreliable   // unordered, maxRetransmits=0 — cursors, move batches
    };

    /**
     * Manages peer-to-peer connections via WebRTC data channels.
     *
     * Star topology: Host connects to all clients. Clients connect only to host.
     * Host relays messages between clients.
     */
    class P2PManager {
    public:
        enum class State {
            Disconnected,
            Connecting,     // signaling / ICE negotiation in progress
            Connected,      // at least one peer connected (host) or connected to host (client)
            Reconnecting,   // lost connection, trying to re-establish
            Error
        };

        enum class Role {
            None,
            Host,
            Client
        };

        using MessageCallback = std::function<void(int playerId, proto::Reader& reader)>;

        static P2PManager& get();


        void hostSession(std::string const& playerName);
        void joinSession(std::string const& roomCode, std::string const& playerName);
        void leaveSession();


        State getState() const;
        Role getRole() const;
        bool isConnected() const;
        std::string getRoomCode() const;
        int getLocalPlayerId() const;
        std::string getError() const;
        bool isPeerReconnect(int playerId);
        bool supportsCapability(int playerId, net::Capability capability);
        std::size_t getTotalReliableQueueDepth();
        uint32_t getGlobalRevision() const { return m_globalRevision.load(); }
        int getLastGlobalAuthor() const { return m_lastGlobalAuthor.load(); }
        struct RoomSettings {
            uint32_t maxPlayers = 8;
            bool allowBuild = true;
            bool allowDelete = true;
            bool allowWorkshop = true;
            bool allowLevelSettings = true;
            bool autoRepair = true;
            bool locked = false;
        };

        RoomSettings getRoomSettings() const;
        void setRoomSettings(RoomSettings const& settings);
        void kickPlayer(int playerId);



        void send(std::vector<uint8_t> const& data, ChannelType channel = ChannelType::Reliable);
        void send(std::vector<uint8_t>&& data, ChannelType channel = ChannelType::Reliable);

        void sendTo(int playerId, std::vector<uint8_t> const& data, ChannelType channel = ChannelType::Reliable);

        void broadcast(std::vector<uint8_t> const& data, ChannelType channel = ChannelType::Reliable, int excludePlayerId = -1);



        void on(proto::Opcode opcode, MessageCallback callback);
        void clearHandlers();

        void dispatchMessages();


        using SessionStartedCb = std::function<void(std::string const& roomCode, int localPlayerId)>;
        using PeerConnectedCb  = std::function<void(int playerId, std::string const& name, int colorIndex)>;
        using PeerDisconnectedCb = std::function<void(int playerId)>;
        using ErrorCb = std::function<void(std::string const& error)>;

        void onSessionStarted(SessionStartedCb cb);
        void onPeerConnected(PeerConnectedCb cb);
        void onPeerDisconnected(PeerDisconnectedCb cb);
        void onError(ErrorCb cb);
        void clearCallbacks();


        static std::string getSignalingUrl();

    private:
        P2PManager();
        ~P2PManager();

        P2PManager(P2PManager const&) = delete;
        P2PManager& operator=(P2PManager const&) = delete;


        struct PendingMessage {
            std::vector<uint8_t> data;
            ChannelType channel;
        };

        struct PendingCandidate {
            std::string candidate;
            std::string mid;
        };

        struct PeerInfo {
            std::shared_ptr<rtc::PeerConnection> pc;
            std::shared_ptr<rtc::DataChannel> reliable;
            std::shared_ptr<rtc::DataChannel> unreliable;
            int playerId = -1;
            std::string playerName;
            int colorIndex = 0;
            bool ready = false; // both channels open
            bool protocolVerified = false;
            uint32_t protocolVersion = 0;
            uint64_t capabilities = 0;
            std::vector<std::vector<uint8_t>> preHandshakeMessages;
            std::vector<PendingMessage> pendingMessages;
            std::vector<std::vector<uint8_t>> bulkReliableQueue;

            struct PendingAck {
                std::vector<uint8_t> envelope;
                uint64_t lastSentMs = 0;
                uint32_t attempts = 0;
                bool queued = true;
            };
            uint32_t nextReliableSequence = 1;
            std::unordered_map<uint32_t, PendingAck> pendingReliableAcks;
            std::unordered_set<uint32_t> receivedReliableSequences;
            std::deque<uint32_t> receivedReliableOrder;
            bool reconnecting = false;
            bool connectionAnnounced = false;
            std::vector<PendingCandidate> pendingCandidates;
        };

        rtc::Configuration makeRtcConfig(bool forceRelay = false);
        void createHostPeer(int clientPlayerId, std::string const& clientName);

        void signalingCreateRoom(std::string const& playerName);
        void signalingJoinRoom(std::string const& roomCode, std::string const& playerName);
        void startSignalPolling(std::string const& code, std::string const& role, int playerId);
        void pollSignalOnce(std::string const& code, std::string const& role, int playerId);
        void stopSignalPolling();
        void sendSignalingMessage(std::string const& roomCode, matjson::Value const& msg);
        void handleSignalingMessages(matjson::Value const& messages);

        void onPeerMessage(int fromPlayerId, const uint8_t* data, size_t len);
        void onPeerDisconnected(int playerId, bool unexpected);

        void relayMessage(int fromPlayerId, const uint8_t* data, size_t len, ChannelType channel);
        void flushBulkReliableQueues();
        void requestHostMigration();
        void becomeMigratedHost(std::string const& token, uint32_t generation);
        void scheduleClientReconnect();
        void finalizePeerHandshake(int playerId);
        void checkPeerReady(int playerId);


        std::atomic<State> m_state{State::Disconnected};
        Role m_role = Role::None;
        std::string m_roomCode;
        int m_localPlayerId = -1;
        std::string m_localPlayerName;
        std::string m_error;
        mutable std::mutex m_stateMutex;


        std::unordered_map<int, PeerInfo> m_peers;
        std::mutex m_peersMutex;
        int m_nextPlayerId = 1; // host assigns IDs (host = 0)
        std::unordered_map<std::string, uint64_t> m_recentDisconnectedNames;
        std::atomic<bool> m_reconnectScheduled{false};
        std::atomic<bool> m_forceRelayNextJoin{false};
        int m_reconnectAttempts = 0;
        std::atomic<uint32_t> m_globalRevision{0};
        std::atomic<int> m_lastGlobalAuthor{0};
        std::unordered_set<std::string> m_kickedNames;
        RoomSettings m_roomSettings;
        mutable std::mutex m_roomSettingsMutex;


        struct QueuedMessage {
            int fromPlayerId;
            std::vector<uint8_t> data;
        };
        std::queue<QueuedMessage> m_incoming;
        std::mutex m_incomingMutex;
        bool m_dispatching = false;


        std::unordered_map<uint8_t, std::vector<MessageCallback>> m_handlers;


        std::vector<SessionStartedCb> m_onSessionStarted;
        std::vector<PeerConnectedCb> m_onPeerConnected;
        std::vector<PeerDisconnectedCb> m_onPeerDisconnected;
        std::vector<ErrorCb> m_onError;


        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalingListener;  // room create/join
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_signalPollListener; // long-poll loop
        geode::async::TaskHolder<geode::utils::web::WebResponse> m_migrationListener;
        std::atomic<bool> m_signalingActive{false};
        std::atomic<bool> m_hostMigrationAvailable{false};
        std::string m_signalingRoomId;   // server-side room ID
        std::string m_signalingToken;
        uint32_t m_signalingGeneration = 0;
        uint32_t m_signalingApi = 1;


    };

} // namespace mpedit
