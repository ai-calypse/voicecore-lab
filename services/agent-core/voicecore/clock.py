"""The one clock of the process: the event loop's monotonic time, so looptime can fake it in tests."""
import asyncio


def now_us() -> int:
    return int(asyncio.get_running_loop().time() * 1e6)
