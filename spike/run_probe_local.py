"""
Local end-to-end invocation of the probe agent through the real ADK Runner —
closes Gate 0 (agent runs locally, reaches Gemini 3.x, tool-calls work) BEFORE
we spend anything on an Agent Engine deploy. Mirrors the Runner/session pattern
in csf_coordinator/coordinator.py.

Usage: poetry run python spike/run_probe_local.py
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

# Load the probe's own .env (Vertex backend, global location for Gemini 3.x),
# same as `adk run` would.
_ENV = Path(__file__).resolve().parent / "probe_agent" / ".env"
for line in _ENV.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from spike.probe_agent.agent import root_agent  # noqa: E402

APP = "probe-spike"
USER = "gate0"


async def main() -> None:
    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name=APP, session_service=session_service)
    sid = "gate0-session"
    await session_service.create_session(app_name=APP, user_id=USER, session_id=sid)

    said_anything = False
    async for event in runner.run_async(
        user_id=USER,
        session_id=sid,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text="Run a check with marker 'gate0-live'.")],
        ),
    ):
        if event.content and event.content.parts:
            text = "".join(p.text for p in event.content.parts if p.text)
            if text:
                said_anything = True
                print(f"[{event.author}] {text}")

    print("\nGATE 0 LOCAL RESULT:", "PASS — model responded" if said_anything else "FAIL — no model output")


if __name__ == "__main__":
    asyncio.run(main())
