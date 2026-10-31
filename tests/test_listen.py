"""cf listen: saving what Competitive Companion sends, and the server itself."""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from cf_tool import listen
from cf_tool.errors import CFError
from cf_tool.workspace import Target, load_info, tests_of

# what the extension sends for one problem (its README's example, shortened)
PROBLEM = {
    "name": "G. Castle Defense",
    "group": "Codeforces - Educational Codeforces Round 40 (Rated for Div. 2)",
    "url": "https://codeforces.com/problemset/problem/954/G",
    "interactive": False,
    "memoryLimit": 256,
    "timeLimit": 1500,
    "tests": [
        {"input": "5 0 6\n5 4 3 4 9\n", "output": "5\n"},
        {"input": "4 2 0\n1 2 3 4\n", "output": "6\n"},
    ],
    "testType": "single",
    "batch": {"id": "123e67c8-03c6-44a4-a3f9-5918533f9fb2", "size": 1},
}


def test_save_problem(tmp_path):
    folder, target, info, count = listen.save_problem(PROBLEM, tmp_path)
    assert folder == tmp_path / "954" / "g"  # NOTE: where cf get 954G puts it
    assert (target, count) == (Target("contest", "954", "G"), 2)
    assert [t.name for t in tests_of(folder)] == ["1", "2"]
    assert (folder / "tests" / "2.ans").read_text() == "6\n"
    saved = load_info(folder)
    assert (saved.name, saved.time_limit, saved.memory_limit, saved.interactive) == (
        "G. Castle Defense",
        1.5,
        256,
        False,
    )


def test_save_a_gym_problem(tmp_path):
    gym = dict(PROBLEM, url="https://codeforces.com/gym/104234/problem/C")
    folder, *_ = listen.save_problem(gym, tmp_path)
    assert folder == tmp_path / "104234" / "c"


@pytest.mark.parametrize(
    "url",
    [
        "https://atcoder.jp/contests/abc300/tasks/abc300_a",
        "https://codeforces.com/blog/entry/1",  # NOTE: Codeforces, but no problem
    ],
)
def test_what_isnt_a_problem_is_turned_down(tmp_path, url):
    with pytest.raises(CFError, match="Not a Codeforces problem"):
        listen.save_problem(dict(PROBLEM, url=url), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_contest_batch_completes(tmp_path, capsys):
    batches = {}
    contest = {"id": "b1", "size": 2}
    first = dict(PROBLEM, url="https://codeforces.com/contest/954/problem/A", batch=contest)
    second = dict(PROBLEM, url="https://codeforces.com/contest/954/problem/B", batch=contest)
    started = []
    on_problem = lambda folder, target, info: started.append(target.label)  # noqa: E731
    assert not listen._receive(json.dumps(first).encode(), tmp_path, on_problem, batches)
    assert not listen._receive(json.dumps(first).encode(), tmp_path, on_problem, batches)
    assert listen._receive(json.dumps(second).encode(), tmp_path, on_problem, batches)
    out = capsys.readouterr().out
    assert "954A" in out and "All 2 problems are here" in out
    assert started == ["954A", "954A", "954B"]


def test_garbage_is_reported(tmp_path, capsys):
    assert not listen._receive(b"not json", tmp_path, None, {})
    assert not listen._receive(b"[1, 2]", tmp_path, None, {})
    assert "isn't a problem" in capsys.readouterr().out


def serve(tmp_path, **options):
    ready = threading.Event()
    bound = []

    def on_ready(port):
        bound.append(port)
        ready.set()

    worker = threading.Thread(
        target=listen.listen,
        args=(tmp_path,),
        kwargs={"port": 0, "ready": on_ready, **options},
        daemon=True,  # NOTE: should the test fail, a waiting server mustn't keep pytest running
    )
    worker.start()
    assert ready.wait(10)
    return worker, bound[0]


def post(port, body: bytes, headers=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_server(tmp_path):
    worker, port = serve(tmp_path)
    assert post(port, json.dumps(PROBLEM).encode()) == 200
    worker.join(10)
    assert not worker.is_alive()  # NOTE: a whole batch arrived, so it stopped
    assert (tmp_path / "954" / "g" / "tests" / "1.in").is_file()


def test_web_pages_are_turned_away(tmp_path):
    worker, port = serve(tmp_path, keep=True)
    body = json.dumps(PROBLEM).encode()
    assert post(port, body, {"Origin": "https://evil.example"}) == 403
    assert post(port, body, {"Content-Type": "text/plain"}) == 415
    assert post(port, body, {"Origin": "chrome-extension://abc"}) == 200  # NOTE: the extension
    deadline = time.monotonic() + 5
    while not (tmp_path / "954").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (tmp_path / "954" / "g").is_dir()


def test_a_silent_connection_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(listen._Handler, "timeout", 0.5)
    worker, port = serve(tmp_path)
    silent = socket.create_connection(("127.0.0.1", port))
    silent.sendall(b"POST / HTTP/1.1\r\nContent-Length: 100\r\n")  # NOTE: and nothing more
    try:
        assert post(port, json.dumps(PROBLEM).encode()) == 200
    finally:
        silent.close()
    worker.join(10)
    assert not worker.is_alive()


def test_a_taken_port(tmp_path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        with pytest.raises(CFError, match="try another with --port"):
            listen.listen(tmp_path, port=taken.getsockname()[1])


def test_the_server_starts_without_looking_up_the_host_name(monkeypatch):
    def slow(*args):
        time.sleep(30)  # NOTE: what the lookup can cost on a Mac

    monkeypatch.setattr(socket, "getfqdn", slow)
    started = time.monotonic()
    server = listen._Server(("127.0.0.1", 0), listen._Handler)
    server.server_close()
    assert time.monotonic() - started < 5
