#!/usr/bin/env python3
"""Play a game through the public HTTP API using random legal moves."""

from __future__ import annotations

import argparse
import json
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def api_request(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {"error": {"message": str(exc)}}
        raise RuntimeError(f"API returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach API: {exc.reason}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--seed", type=int, help="Optional reproducible game seed")
    parser.add_argument("--max-steps", type=int, default=200, help="Stop after this many moves")
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds between moves")
    parser.add_argument("--game-id", help="Control an existing game instead of creating one")
    parser.add_argument("--seed-rng", type=int, help="Seed the script's move selector")
    args = parser.parse_args()
    if args.max_steps < 0 or args.delay < 0:
        parser.error("--max-steps and --delay must be non-negative")

    if args.game_id:
        state = api_request(args.url, f"/api/games/{args.game_id}")
        game_id = args.game_id
    else:
        body = {"mode": "external"}
        if args.seed is not None:
            body["seed"] = args.seed
        created = api_request(args.url, "/api/games", body)
        state = created["state"]
        game_id = state["id"]
        print(f"Created game {game_id} (seed {created['seed']})")

    rng = random.Random(args.seed_rng)
    completed = 0
    while completed < args.max_steps and state["status"] == "ongoing":
        legal = state["legal_moves"]
        if not legal:
            break
        direction = rng.choice(legal)
        result = api_request(args.url, f"/api/games/{game_id}/moves", {
            "direction": direction,
            "expected_revision": state["revision"],
            "source": "external",
        })
        state = result["state"]
        completed += 1
        print(f"{completed:3} {direction:5} score={state['score']:5} max={state['max_tile']:4} rev={state['revision']}")
        if args.delay:
            time.sleep(args.delay)
    print(f"Stopped after {completed} moves: {state['status']}, score {state['score']}, max tile {state['max_tile']}")
    print(f"Watch the same game at the app's game URL: {game_id}")


if __name__ == "__main__":
    main()
