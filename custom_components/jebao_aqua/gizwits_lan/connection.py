import asyncio
from collections.abc import Awaitable, Callable
import logging
import time

logger = logging.getLogger(__name__)


class Connection:
    """Manages all connection-related tasks for a device."""

    def __init__(
        self,
        connect_func: Callable[[], Awaitable[bool]],
        disconnect_func: Callable[[], Awaitable[None]],
        ping_func: Callable[[], Awaitable[bool]],
        ready_check: Callable[[], bool],
        device_id: str,  # Add device identifier
        retry_interval: float = 2.0,
        min_retry_interval: float = 2.0,
        max_retry_interval: float = 300.0,
        ping_interval: float = 4.0,
        ping_timeout: float = 10.0,
    ):
        """Args:
        connect_func: Protocol-specific connection logic
        disconnect_func: Protocol-specific cleanup
        ping_func: Protocol-specific keepalive check
        ready_check: Quick health check
        device_id: String to identify device in logs (e.g. IP address)
        retry_interval: Time between connection attempts
        min_retry_interval: Minimum time between connection attempts
        max_retry_interval: Maximum time between connection attempts
        ping_interval: Time between pings
        ping_timeout: Maximum time to wait for pong

        """
        self._connect_func = connect_func
        self._disconnect_func = disconnect_func
        self._ping_func = ping_func
        self._ready_check = ready_check
        self._retry_interval = retry_interval
        self._min_retry_interval = min_retry_interval
        self._max_retry_interval = max_retry_interval
        self._current_retry_interval = retry_interval
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._device_id = device_id

        self._connection_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._should_run = False
        self._lock = asyncio.Lock()
        self._last_success = 0.0
        self._last_pong = 0.0
        self._was_ready = False  # Track state changes
        self._callbacks = set()  # Add callback storage

    @property
    def connected(self) -> bool:
        """Return True if actively trying to maintain connection."""
        return self._should_run

    @property
    def ready(self) -> bool:
        """Return True if connection is established and healthy."""
        return self._ready_check()

    def add_callback(self, callback: Callable[[bool], None]) -> None:
        """Add a callback to be notified of connection state changes."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[bool], None]) -> None:
        """Remove a previously registered callback."""
        self._callbacks.discard(callback)

    def _notify_callbacks(self, is_connected: bool) -> None:
        """Notify all callbacks of connection state change."""
        for callback in self._callbacks:
            try:
                callback(is_connected)
            except Exception as e:
                logger.error(
                    "[%s] Error in connection callback: %s", self._device_id, e
                )

    async def start(self):
        """Start connection management."""
        async with self._lock:
            if self._should_run:
                return
            self._should_run = True

            # Start main connection management
            if not self._connection_task:
                self._connection_task = asyncio.create_task(self._connection_loop())

            # Keepalive task is now started by connection loop when ready

    async def stop(self):
        """Stop all connection tasks and disconnect."""
        async with self._lock:
            self._should_run = False

            # Cancel all tasks
            for task in (self._connection_task, self._keepalive_task):
                if task:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            self._connection_task = None
            self._keepalive_task = None

            # Final cleanup
            await self._disconnect_func()
            self._notify_callbacks(False)  # Notify on final disconnect

    async def _connection_loop(self):
        """Main connection management loop with exponential backoff."""
        while self._should_run:
            try:
                is_ready = self._ready_check()

                # State change detection
                if is_ready != self._was_ready:
                    if not is_ready:
                        logger.info("[%s] Connection lost", self._device_id)
                        await self._disconnect_func()
                        self._notify_callbacks(False)
                    self._was_ready = is_ready

                # Connection management
                if not is_ready:
                    logger.info("[%s] Attempting connection...", self._device_id)
                    if await self._connect_func():
                        self._last_success = time.time()
                        self._current_retry_interval = self._retry_interval

                        # Start keepalive when connection established
                        if not self._keepalive_task or self._keepalive_task.done():
                            self._keepalive_task = asyncio.create_task(
                                self._keepalive_loop()
                            )

                        # Notify successful connection
                        self._was_ready = True  # Must set before callback
                        self._notify_callbacks(True)
                        continue

                    # Connection failed
                    logger.warning(
                        "[%s] Connection failed, retrying in %.1f seconds",
                        self._device_id,
                        self._current_retry_interval,
                    )
                    await asyncio.sleep(self._current_retry_interval)
                    self._current_retry_interval = min(
                        self._current_retry_interval * 2, self._max_retry_interval
                    )
                else:
                    await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(
                    "[%s] Error in connection loop: %s", self._device_id, e
                )
                if self._was_ready:
                    self._was_ready = False
                    self._notify_callbacks(False)
                await asyncio.sleep(self._min_retry_interval)

        # Clean up on exit
        if self._was_ready:
            await self._disconnect_func()
            self._notify_callbacks(False)

    async def _keepalive_loop(self):
        """Keepalive management loop."""
        while self._should_run:
            try:
                if self._ready_check():
                    # Only ping if connection is healthy
                    logger.debug("[%s] Sending keepalive ping", self._device_id)
                    if await self._ping_func():
                        logger.debug("[%s] Keepalive ping successful", self._device_id)
                        await asyncio.sleep(self._ping_interval)
                        continue

                    # Ping failed - trigger reconnect by marking not ready
                    logger.warning("[%s] Keepalive ping failed", self._device_id)

                # Not connected or ping failed, just wait
                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("[%s] Error in keepalive loop: %s", self._device_id, e)
                await asyncio.sleep(1.0)
