"""The problem info file cf parse leaves for cf test."""

from cf_tool.problem import FILE_NAME, ProblemInfo


def test_save_and_load(tmp_path):
    info = ProblemInfo(
        name="A. X",
        url="https://codeforces.com/contest/1/problem/A",
        time_limit=2.5,
        memory_limit=256,
        interactive=True,
        ignore_case=True,
        epsilon=1e-6,
        cases=[None, ([0, 1], [1])],
    )
    info.save(tmp_path)
    assert ProblemInfo.load(tmp_path) == info
    assert info.sample_cases("2") == ([0, 1], [1])
    assert info.sample_cases("1") is None and info.sample_cases("3") is None


def test_load_without_a_file_or_from_a_broken_one(tmp_path):
    assert ProblemInfo.load(tmp_path) is None
    (tmp_path / FILE_NAME).write_text("{not json")
    assert ProblemInfo.load(tmp_path) is None


def test_load_ignores_odd_values(tmp_path):
    (tmp_path / FILE_NAME).write_text('{"time_limit": "1 second", "memory_limit": true}')
    assert ProblemInfo.load(tmp_path) == ProblemInfo()
