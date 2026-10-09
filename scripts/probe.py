"""Dump what the Warmup API reports for the account in .env.

Usage: python scripts/probe.py            parsed rooms
       python scripts/probe.py --raw '{ user { id } }'   any GraphQL query

Needs aiohttp. Reads WARMUP_USER and WARMUP_PASSWORD from .env in the repo root.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import ssl
import sys

import aiohttp

ROOT = Path(__file__).resolve().parent.parent

# Load api.py on its own so Home Assistant does not need to be installed.
_spec = importlib.util.spec_from_file_location(
    "warmup_api", ROOT / "custom_components" / "warmup" / "api.py"
)
api = importlib.util.module_from_spec(_spec)
sys.modules["warmup_api"] = api
_spec.loader.exec_module(api)


def _env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


async def main() -> None:
    env = _env()
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    connector = aiohttp.TCPConnector(ssl=context)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = api.WarmupClient(session)
        await client.login(env["WARMUP_USER"], env["WARMUP_PASSWORD"])
        if len(sys.argv) > 2 and sys.argv[1] == "--raw":
            print(json.dumps(await client._graphql(sys.argv[2]), indent=2))
            return
        for room in (await client.get_rooms()).values():
            print(json.dumps(asdict(room), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
