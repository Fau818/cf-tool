"""`cf listen`: receive problems from the Competitive Companion browser
extension, so samples arrive without cf fetching a Codeforces page.

The extension sends each problem as JSON (POST /) to localhost on a fixed
list of ports (its src/hosts/hosts.ts); cf takes one of them. A contest
comes as a batch: one POST per problem, each knowing the batch's size."""

from __future__ import annotations

import json
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from cf_tool import templates, ui
from cf_tool.args import Info, parse_args
from cf_tool.config import Config
from cf_tool.errors import CFError
from cf_tool.problem import ProblemInfo

DEFAULT_PORT = 4244  # NOTE: Hightail's, a tool gone quiet; the extension still sends there


def save_problem(data: dict, cfg: Config, cwd: Path) -> tuple[Info, int]:
    """Write a received problem's samples and info into its folder, as cf
    parse would; returns (where it went, the number of samples)."""
    url = str(data.get("url", ""))
    host = urlparse(url).hostname or ""
    if host != "codeforces.com" and not host.endswith(".codeforces.com"):
        raise CFError(f"Not a Codeforces problem: {url or data.get('name', '?')}")
    info = parse_args([url], cwd, cfg)
    folder = info.path()
    folder.mkdir(parents=True, exist_ok=True)
    tests = [t for t in data.get("tests", []) if isinstance(t, dict)]
    for i, test in enumerate(tests, start=1):
        (folder / f"in{i}.txt").write_text(str(test.get("input", "")), encoding="utf-8", newline="")
        (folder / f"ans{i}.txt").write_text(
            str(test.get("output", "")), encoding="utf-8", newline=""
        )
    limit = data.get("timeLimit")
    memory = data.get("memoryLimit")
    ProblemInfo(
        name=str(data.get("name", "")),
        url=url,
        time_limit=limit / 1000 if isinstance(limit, (int, float)) else None,  # NOTE: sent in ms
        memory_limit=int(memory) if isinstance(memory, (int, float)) else None,
        interactive=bool(data.get("interactive", False)),
    ).save(folder)
    return info, len(tests)


class _Server(HTTPServer):
    def server_bind(self) -> None:
        # NOTE: HTTPServer's own also looks up this host's name, which can take
        # \     half a minute on macOS; the name isn't needed here
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.end_headers()
        self.server.received.append(body)  # type: ignore[attr-defined]

    def log_message(self, format, *args) -> None:  # noqa: A002 (the base class's name)
        pass  # NOTE: no request log on the terminal


def listen(
    cfg: Config,
    cwd: Path,
    handle: str,
    port: int = DEFAULT_PORT,
    keep: bool = False,
    ready: Callable[[int], None] | None = None,
) -> None:
    """Receive problems on localhost:port and save each; returns once a
    whole batch (a contest, or a single problem) arrived, unless keep.
    ready(port) is called once listening."""
    code = templates.default_code(cfg, handle) if cfg.gen_after_parse else None
    try:
        server = _Server(("127.0.0.1", port), _Handler)
    except OSError as e:
        raise CFError(
            f"Cannot listen on port {port} ({e.strerror or e}): try another with --port"
        ) from e
    server.received = []  # type: ignore[attr-defined]
    batches: dict[str, set[str]] = {}
    with server:
        ui.cyan(
            f"Listening on port {server.server_port}: click Competitive Companion's button "
            "on a problem or contest page (Ctrl-C stops)"
        )
        if ready is not None:
            ready(server.server_port)
        while True:
            server.handle_request()
            for body in server.received:  # type: ignore[attr-defined]
                done = _receive(body, cfg, cwd, code, batches)
                if done and not keep:
                    return
            server.received.clear()  # type: ignore[attr-defined]


def _receive(
    body: bytes, cfg: Config, cwd: Path, code: tuple[str, str] | None, batches: dict[str, set[str]]
) -> bool:
    """Save one received problem and say so; returns whether its batch is now complete."""
    try:
        data = json.loads(body)
        info, count = save_problem(data, cfg, cwd)
    except (ValueError, TypeError, AttributeError) as e:
        ui.red(f"Received something that isn't a problem ({e})")
        return False
    except CFError as e:
        ui.red(str(e))
        return False
    if code is not None:
        templates.generate_file(code[0], info.path(), code[1])
    noun = "sample" if count == 1 else "samples"
    ui.line(
        (f"Parsed {info.contest_id}{info.problem_id.upper()} with {count} {noun}", "green"),
        (f" into {info.path()}", ""),
    )
    batch = data.get("batch") if isinstance(data.get("batch"), dict) else {}
    seen = batches.setdefault(str(batch.get("id", "")), set())
    seen.add(str(data.get("url", "")))
    size = batch.get("size") if isinstance(batch.get("size"), int) else 1
    if len(seen) >= size:
        if size > 1:
            ui.green(f"All {size} problems are here")
        return True
    return False
