# ✅ GOOD - Async with graceful shutdown
async def main():
    shutdown_event = asyncio.Event()
    # ... setup ...
    await shutdown_event.wait()
