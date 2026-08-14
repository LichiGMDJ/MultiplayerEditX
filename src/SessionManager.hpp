#pragma once

#include <string>
#include <vector>
#include <functional>

namespace mpedit {

    struct PlayerInfo {
        int id = -1;
        std::string name;
        int colorIndex = 0;
        float cursorX = 0.f;
        float cursorY = 0.f;
        std::string status;
    };

    class SessionManager {
    public:
        enum class Role {
            None,
            Host,
            Client
        };

        static SessionManager& get();

        // Session lifecycle
        void hostSession(
            std::string const& playerName,
            std::string const& roomName = "",
            std::string const& description = "",
            int playerLimit = 8,
            bool isPrivate = false,
            std::string const& password = ""
        );
        void joinSession(
            std::string const& roomCode,
            std::string const& playerName,
            std::string const& password = ""
        );
        void leaveSession();

        // State queries
        bool isInSession() const;
        Role getRole() const;
        std::string getRoomCode() const;
        int getLocalPlayerId() const;
        std::string getLocalPlayerName() const;

        // Player management
        std::vector<PlayerInfo> const& getPlayers() const;
        PlayerInfo const* getPlayer(int id) const;
        void updatePlayerCursor(int playerId, float x, float y, std::string const& status);

        // Register callbacks for session events
        using SessionCallback = std::function<void()>;
        using PlayerCallback = std::function<void(PlayerInfo const&)>;
        using ErrorCallback = std::function<void(std::string const&)>;

        void onSessionStarted(SessionCallback cb);
        void onSessionEnded(SessionCallback cb);
        void onPlayerJoined(PlayerCallback cb);
        void onPlayerLeft(PlayerCallback cb);
        void onError(ErrorCallback cb);
        void clearCallbacks();
        void clearPopupCallbacks();

    private:
        SessionManager() = default;
        ~SessionManager() = default;

        SessionManager(SessionManager const&) = delete;
        SessionManager& operator=(SessionManager const&) = delete;

        void setupNetworkHandlers();
        void clearNetworkHandlers();

        Role m_role = Role::None;
        std::string m_roomCode;
        int m_localPlayerId = -1;
        std::string m_localPlayerName;
        std::vector<PlayerInfo> m_players;

        // Event callbacks
        std::vector<SessionCallback> m_onSessionStarted;
        std::vector<SessionCallback> m_onSessionEnded;
        std::vector<PlayerCallback> m_onPlayerJoined;
        std::vector<PlayerCallback> m_onPlayerLeft;
        std::vector<ErrorCallback> m_onError;
    };

} // namespace mpedit
