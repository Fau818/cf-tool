"""cf listen: problems from the Competitive Companion browser extension, so
the samples arrive without cf-tool fetching a Codeforces page.

The extension sends each problem as JSON (a POST to localhost) to a fixed
list of ports (its src/hosts/hosts.ts); cf takes one of them. A contest
comes as a batch: one POST per problem, each knowing the batch's size. Only
the extension is listened to: a request from a web page (it carries an
Origin) or one that isn't JSON is turned away, and so is a page that isn't
a Codeforces problem.
"""

from __future__ import annotations

import json
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from cf_tool import ui
from cf_tool.errors import CFError
from cf_tool.workspace import (
    ProblemInfo,
    Target,
    load_info,
    parse_target,
    problem_folder,
    read_spec,
    save_info,
    save_samples,
)

DEFAULT_PORT = 4244  # NOTE: Hightail's, a tool gone quiet; the extension still sends there
REQUEST_TIMEOUT = 5.0  # seconds a connection gets to send its problem
MAX_BODY = 16 * 1024 * 1024  # bytes
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://", "safari-web-extension://")

# what to do with a problem once its folder is written: (folder, target, info)
OnProblem = Callable[[Path, Target, ProblemInfo], None]


def save_problem(data: dict, root: Path) -> tuple[Path, Target, ProblemInfo, int]:
    """Write a received problem's tests and info into its folder under root,
    as cf get would; returns (its folder, the problem, its info, the number
    of tests). Raises CFError for what isn't a Codeforces problem."""
    url = str(data.get("url", ""))
    host = urlparse(url).hostname or ""
    if host != "codeforces.com" and not host.endswith(".codeforces.com"):
        raise CFError(f"Not a Codeforces problem: {url or data.get('name', '?')}")
    parsed = read_spec(url)
    if not parsed or not parsed.get("problem"):
        raise CFError(f"Not a Codeforces problem's page: {url}")
    target = parse_target([url])
    folder = problem_folder(root, target)
    tests = [
        (str(test.get("input", "")), str(test.get("output", "")))
        for test in data.get("tests", [])
        if isinstance(test, dict)
    ]
    save_samples(folder, tests)
    limit, memory = data.get("timeLimit"), data.get("memoryLimit")
    known = load_info(folder)  # NOTE: cf get read more from the statement than the extension sends
    info = ProblemInfo(
        name=str(data.get("name", "")),
        url=url,
        time_limit=limit / 1000 if isinstance(limit, (int, float)) else None,  # NOTE: sent in ms
        memory_limit=int(memory) if isinstance(memory, (int, float)) else None,
        interactive=bool(data.get("interactive", False)),
    )
    if known is not None:
        info.ignore_case, info.epsilon = known.ignore_case, known.epsilon
        info.any_answer = known.any_answer
        info.interactive = info.interactive or known.interactive
        if len(known.cases) == len(tests):
            info.cases = known.cases
    save_info(folder, info)
    return folder, target, info, len(tests)


class _Server(HTTPServer):
    def server_bind(self) -> None:
        # NOTE: HTTPServer's own also looks up this host's name, which can take
        # \     half a minute on macOS; the name isn't needed here
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Handler(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT  # NOTE: a connection that sends nothing can't hold up the next

    def do_POST(self) -> None:
        length = self.headers.get("Content-Length") or "0"
        if not length.isdigit() or int(length) > MAX_BODY:
            self._answer(413)
            return
        body = self.rfile.read(int(length))  # NOTE: read first: an unread body resets the answer
        origin = self.headers.get("Origin")
        if origin is not None and not origin.startswith(EXTENSION_ORIGINS):
            self._answer(403)  # NOTE: a web page (or a sandboxed one: "null"), not the extension
            return
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._answer(415)  # NOTE: a page can't send JSON here without asking first
            return
        self._answer(200)
        self.server.received.append(body)  # type: ignore[attr-defined]

    def _answer(self, status: int) -> None:
        self.send_response(status)
        self.end_headers()

    def log_message(self, format, *args) -> None:  # noqa: A002 (the base class's name)
        pass  # NOTE: no request log on the terminal


def listen(
    root: Path,
    on_problem: OnProblem | None = None,
    port: int = DEFAULT_PORT,
    keep: bool = False,
    ready: Callable[[int], None] | None = None,
) -> None:
    """Receive problems on localhost:port, save each under root and pass it
    to on_problem (the starter code); returns once a whole batch (a contest,
    or a single problem) arrived, unless keep. ready(port) is called once
    listening."""
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
                if _receive(body, root, on_problem, batches) and not keep:
                    return
            server.received.clear()  # type: ignore[attr-defined]


def _receive(
    body: bytes, root: Path, on_problem: OnProblem | None, batches: dict[str, set[str]]
) -> bool:
    """Save one received problem and say so; returns whether its batch is now complete."""
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        folder, target, info, count = save_problem(data, root)
    except (ValueError, TypeError, AttributeError) as e:
        ui.red(f"Received something that isn't a problem ({e})")
        return False
    except CFError as e:
        ui.red(str(e))
        return False
    if on_problem is not None:
        on_problem(folder, target, info)
    noun = "test" if count == 1 else "tests"
    ui.line((f"{target.label}", "bold green"), (f"  {info.name}  {count} {noun} in {folder}", ""))
    batch = data.get("batch") if isinstance(data.get("batch"), dict) else {}
    seen = batches.setdefault(str(batch.get("id", "")), set())
    seen.add(str(data.get("url", "")))
    size = batch.get("size") if isinstance(batch.get("size"), int) else 1
    if len(seen) >= size:
        if size > 1:
            ui.green(f"All {size} problems are here")
        return True
    return False
