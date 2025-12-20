import uvicorn
import os
import webbrowser
from pathlib import Path
import time
import threading
import sys
import asyncio

# Set Windows event loop policy for Playwright
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def open_browser():
    # Give the server a moment to start (increased to 5 seconds to allow for browser launch)
    time.sleep(5)
    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    print(f"Opening frontend: {frontend_path}")
    webbrowser.open(frontend_path.as_uri())

def main():
    # Start browser in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Run the API
    print("Starting API server on http://localhost:8801")
    # Disable reload to ensure event loop policy is applied correctly in the main process
    uvicorn.run("api:app", host="0.0.0.0", port=8801, reload=False, loop="asyncio")

if __name__ == "__main__":
    main()
