"""
Market Calendar

Tracks 15-minute window resolution times and generates alerts
when approaching trading opportunities.
"""
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, List
from dataclasses import dataclass
from enum import Enum


class WindowPhase(Enum):
    """Phase of the 15-minute window."""
    IDLE = "idle"  # More than 60s away
    WATCHING = "watching"  # 60-30s away
    READY = "ready"  # 30-10s away
    EXECUTING = "executing"  # 10-2s away
    CLOSED = "closed"  # Window closed


@dataclass
class WindowEvent:
    """Event for a 15-minute window."""
    window_time: datetime  # When the window closes (e.g., 12:15:00)
    seconds_until: float  # Seconds until window close
    phase: WindowPhase  # Current phase

    @property
    def timestamp(self) -> int:
        """Unix timestamp of window close."""
        return int(self.window_time.timestamp())


class MarketCalendar:
    """
    Tracks 15-minute window times and generates alerts.

    15-minute windows close at:
    - :00, :15, :30, :45 of every hour

    Phases:
    - IDLE: >60s away from next window
    - WATCHING: 60-30s away (start watching price)
    - READY: 30-10s away (calculate position)
    - EXECUTING: 10-2s away (execute trade)
    - CLOSED: Window just closed

    Example:
        calendar = MarketCalendar()

        def on_phase_change(event: WindowEvent):
            if event.phase == WindowPhase.EXECUTING:
                print(f"Execute now! {event.seconds_until:.1f}s left")

        calendar.subscribe(on_phase_change)

        while True:
            calendar.update()
            time.sleep(1)
    """

    WINDOW_MINUTES = [0, 15, 30, 45]  # Minutes when windows close

    def __init__(self):
        # Callbacks
        self._callbacks: List[Callable[[WindowEvent], None]] = []

        # State
        self._current_phase = WindowPhase.IDLE
        self._last_window: Optional[datetime] = None
        self._next_window: Optional[datetime] = None

        # Calculate initial windows
        self._update_windows()

    def subscribe(self, callback: Callable[[WindowEvent], None]):
        """
        Subscribe to window events.

        Callback is called when phase changes.
        """
        self._callbacks.append(callback)

    def _update_windows(self):
        """Calculate next window time."""
        now = datetime.utcnow()

        # Find next window minute
        current_minute = now.minute
        current_hour = now.hour

        # Find next window in current hour
        next_minutes = [m for m in self.WINDOW_MINUTES if m > current_minute]

        if next_minutes:
            # Next window is in current hour
            next_minute = next_minutes[0]
            self._next_window = now.replace(
                minute=next_minute,
                second=0,
                microsecond=0
            )
        else:
            # Next window is in next hour
            next_hour = now + timedelta(hours=1)
            self._next_window = next_hour.replace(
                minute=0,
                second=0,
                microsecond=0
            )

        # Find last window
        past_minutes = [m for m in self.WINDOW_MINUTES if m <= current_minute]

        if past_minutes:
            # Last window was in current hour
            last_minute = past_minutes[-1]
            self._last_window = now.replace(
                minute=last_minute,
                second=0,
                microsecond=0
            )
        else:
            # Last window was in previous hour
            prev_hour = now - timedelta(hours=1)
            self._last_window = prev_hour.replace(
                minute=45,
                second=0,
                microsecond=0
            )

    def get_next_window(self) -> Optional[datetime]:
        """Get next window close time."""
        return self._next_window

    def get_last_window(self) -> Optional[datetime]:
        """Get last window close time."""
        return self._last_window

    def get_seconds_until_next(self) -> float:
        """Get seconds until next window."""
        if not self._next_window:
            return float('inf')

        now = datetime.utcnow()
        delta = (self._next_window - now).total_seconds()
        return max(0, delta)

    def get_phase(self) -> WindowPhase:
        """Get current phase."""
        seconds_until = self.get_seconds_until_next()

        if seconds_until <= 0:
            return WindowPhase.CLOSED
        elif seconds_until <= 2:
            return WindowPhase.CLOSED  # Too late
        elif seconds_until <= 10:
            return WindowPhase.EXECUTING
        elif seconds_until <= 30:
            return WindowPhase.READY
        elif seconds_until <= 60:
            return WindowPhase.WATCHING
        else:
            return WindowPhase.IDLE

    def update(self):
        """
        Update calendar state.

        Call this regularly (e.g., every second) to check for phase changes.
        """
        # Check if window closed
        seconds_until = self.get_seconds_until_next()

        if seconds_until <= 0:
            # Window closed, move to next
            self._update_windows()

        # Check for phase change
        new_phase = self.get_phase()

        if new_phase != self._current_phase:
            # Phase changed
            self._current_phase = new_phase

            # Create event
            event = WindowEvent(
                window_time=self._next_window,
                seconds_until=seconds_until,
                phase=new_phase
            )

            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(event)
                except Exception as e:
                    print(f"Error in calendar callback: {e}")

    def get_current_event(self) -> WindowEvent:
        """Get current window event."""
        return WindowEvent(
            window_time=self._next_window,
            seconds_until=self.get_seconds_until_next(),
            phase=self.get_phase()
        )

    def get_all_windows_today(self) -> List[datetime]:
        """Get all window times for today."""
        now = datetime.utcnow()
        windows = []

        for hour in range(24):
            for minute in self.WINDOW_MINUTES:
                window = now.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0
                )
                windows.append(window)

        return sorted(windows)

    def format_time_until(self, seconds: float) -> str:
        """Format seconds until in human-readable form."""
        if seconds < 0:
            return "CLOSED"
        elif seconds < 60:
            return f"{seconds:.0f}s"
        else:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"


def test_calendar():
    """Test the market calendar."""
    print("Testing Market Calendar...")
    print(f"Current time (UTC): {datetime.utcnow().strftime('%H:%M:%S')}")

    calendar = MarketCalendar()

    # Show next windows
    print(f"\nLast window: {calendar.get_last_window().strftime('%H:%M:%S')}")
    print(f"Next window: {calendar.get_next_window().strftime('%H:%M:%S')}")
    print(f"Time until: {calendar.format_time_until(calendar.get_seconds_until_next())}")

    # Show all windows today
    print("\n--- All windows today (UTC) ---")
    windows = calendar.get_all_windows_today()
    for i, w in enumerate(windows[:10]):  # Show first 10
        print(f"{i+1}. {w.strftime('%H:%M')}")

    # Subscribe to events
    def on_event(event: WindowEvent):
        print(f"\n🔔 Phase changed: {event.phase.value}")
        print(f"   Window: {event.window_time.strftime('%H:%M:%S')}")
        print(f"   Time until: {calendar.format_time_until(event.seconds_until)}")

    calendar.subscribe(on_event)

    # Simulate updates
    print("\n--- Simulating updates (10 seconds) ---")
    for i in range(10):
        calendar.update()
        event = calendar.get_current_event()
        print(f"T+{i}s: {event.phase.value:10s} | {event.seconds_until:.1f}s until {event.window_time.strftime('%H:%M')}")
        time.sleep(1)

    print("\n✅ Test complete")


if __name__ == "__main__":
    test_calendar()
