"""cf listen: saving what Competitive Companion sends, and the server itself."""

import json
import threading
import urllib.request

import pytest

from cf_tool import listen
from cf_tool.config import Config
from cf_tool.errors import CFError
from cf_tool.problem import ProblemInfo

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
    info, count = listen.save_problem(PROBLEM, Config(), tmp_path)
    folder = tmp_path / "cf" / "contest" / "954" / "g"  # NOTE: where cf parse 954G puts it
    assert (info.path(), count) == (folder, 2)
    assert (folder / "in1.txt").read_text() == "5 0 6\n5 4 3 4 9\n"
    assert (folder / "ans2.txt").read_text() == "6\n"
    saved = ProblemInfo.load(folder)
    assert (saved.name, saved.time_limit, saved.memory_limit, saved.interactive) == (
        "G. Castle Defense",
        1.5,
        256,
        False,
    )


def test_save_a_gym_problem(tmp_path):
    gym = dict(PROBLEM, url="https://codeforces.com/gym/104234/problem/C")
    info, _ = listen.save_problem(gym, Config(), tmp_path)
    assert info.path() == tmp_path / "cf" / "gym" / "104234" / "c"


def test_other_judges_are_turned_down(tmp_path):
    with pytest.raises(CFError, match="Not a Codeforces problem"):
        listen.save_problem(
            dict(PROBLEM, url="https://atcoder.jp/contests/abc300/tasks/abc300_a"),
            Config(),
            tmp_path,
        )


def test_a_contest_batch_completes(tmp_path, capsys):
    batches = {}
    contest = {"id": "b1", "size": 2}
    first = dict(PROBLEM, url="https://codeforces.com/contest/954/problem/A", batch=contest)
    second = dict(PROBLEM, url="https://codeforces.com/contest/954/problem/B", batch=contest)
    assert not listen._receive(json.dumps(first).encode(), Config(), tmp_path, None, batches)
    assert not listen._receive(
        json.dumps(first).encode(), Config(), tmp_path, None, batches
    )  # NOTE: again
    assert listen._receive(json.dumps(second).encode(), Config(), tmp_path, None, batches)
    out = capsys.readouterr().out
    assert "Parsed 954A with 2 samples" in out and "All 2 problems are here" in out


def test_garbage_is_reported(tmp_path, capsys):
    assert not listen._receive(b"not json", Config(), tmp_path, None, {})
    assert "isn't a problem" in capsys.readouterr().out


def test_the_server(tmp_path):
    ready = threading.Event()
    bound = []

    def on_ready(port):
        bound.append(port)
        ready.set()

    worker = threading.Thread(
        target=listen.listen, args=(Config(), tmp_path, ""), kwargs={"port": 0, "ready": on_ready}
    )
    worker.start()
    assert ready.wait(10)
    request = urllib.request.Request(
        f"http://127.0.0.1:{bound[0]}/", data=json.dumps(PROBLEM).encode(), method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
    worker.join(10)
    assert not worker.is_alive()  # NOTE: a whole batch arrived, so it stopped
    assert (tmp_path / "cf" / "contest" / "954" / "g" / "in1.txt").is_file()


def test_a_taken_port(tmp_path):
    import socket

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        with pytest.raises(CFError, match="try another with --port"):
            listen.listen(Config(), tmp_path, "", port=taken.getsockname()[1])
