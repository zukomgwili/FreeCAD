// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <limits>
#include <mutex>

namespace Part::detail
{
/** Bounded diagnostics only: no shape, identity, cancellation or console state. */
class HasherMismatchLimiter
{
public:
    using Clock = std::chrono::steady_clock;
    enum class Boundary
    {
        SubElementType,
        HasherSelection,
        MappedNames,
        Count
    };
    struct Decision
    {
        bool publish;
        std::size_t count;
        std::size_t previousBurst;
    };

    Decision record(Boundary boundary, bool error = false, Clock::time_point now = Clock::now())
    {
        std::lock_guard<std::mutex> guard(mutex);
        auto& state = states[2 * static_cast<std::size_t>(boundary) + std::size_t(error)];
        std::size_t previous = 0;
        if (state.count && now - state.last >= std::chrono::seconds(1)) {
            if (state.count != state.published) {
                previous = state.count;
            }
            state.count = state.published = 0;
        }
        state.last = now;
        if (state.count == std::numeric_limits<std::size_t>::max()) {
            return {false, state.count, previous};
        }
        ++state.count;
        bool publish = (state.count & (state.count - 1)) == 0;
        if (publish) {
            state.published = state.count;
        }
        return {publish, state.count, previous};
    }

private:
    struct State
    {
        std::size_t count = 0;
        std::size_t published = 0;
        Clock::time_point last {};
    };
    std::mutex mutex;
    std::array<State, 2 * static_cast<std::size_t>(Boundary::Count)> states;
};
}  // namespace Part::detail
