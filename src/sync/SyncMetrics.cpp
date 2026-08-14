#include "SyncMetrics.hpp"

#include <chrono>

namespace mpedit::sync {

    namespace {
        uint64_t nowMs() {
            return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now().time_since_epoch()
            ).count());
        }
    }

    SyncMetrics& SyncMetrics::get() {
        static SyncMetrics instance;
        return instance;
    }

    void SyncMetrics::recordSerializedObjects(std::size_t count) {
        m_totalObjectsSerialized.fetch_add(static_cast<uint64_t>(count), std::memory_order_relaxed);
    }

    void SyncMetrics::recordOutboundBytes(std::size_t bytes) {
        m_totalBytesQueued.fetch_add(static_cast<uint64_t>(bytes), std::memory_order_relaxed);
    }

    void SyncMetrics::setReliableQueueDepth(std::size_t depth) {
        m_reliableQueueDepth.store(depth, std::memory_order_relaxed);
    }

    SyncMetricsSnapshot SyncMetrics::sample() {
        std::lock_guard lock(m_sampleMutex);

        auto currentMs = nowMs();
        auto objects = m_totalObjectsSerialized.load(std::memory_order_relaxed);
        auto bytes = m_totalBytesQueued.load(std::memory_order_relaxed);

        SyncMetricsSnapshot snapshot;
        snapshot.reliableQueueDepth = m_reliableQueueDepth.load(std::memory_order_relaxed);
        snapshot.totalObjectsSerialized = objects;
        snapshot.totalBytesQueued = bytes;

        if (m_lastSampleMs != 0 && currentMs > m_lastSampleMs) {
            double seconds = static_cast<double>(currentMs - m_lastSampleMs) / 1000.0;
            snapshot.objectsPerSecond = static_cast<double>(objects - m_lastObjects) / seconds;
            snapshot.bytesPerSecond = static_cast<double>(bytes - m_lastBytes) / seconds;
        }

        m_lastSampleMs = currentMs;
        m_lastObjects = objects;
        m_lastBytes = bytes;
        return snapshot;
    }

} // namespace mpedit::sync
