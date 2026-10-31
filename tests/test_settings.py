"""config.toml: defaults, values, mistakes, changes that keep comments, and
the move from cf-tool 0.3's JSON config."""

import json

import pytest

from cf_tool import paths
from cf_tool.errors import CFError
from cf_tool.settings import DEFAULT_HOST, LanguageSettings, Settings, migrate


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path / "config")
    return tmp_path / "config"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_no_file_means_defaults(config_dir):
    settings = Settings.load()
    assert (settings.language, settings.host, settings.proxy, settings.root) == (
        "",
        DEFAULT_HOST,
        "",
        "",
    )
    assert settings.language_settings("cpp") == LanguageSettings()
    assert settings.file == config_dir / "config.toml"


def test_values(config_dir):
    write(
        config_dir / "config.toml",
        """
        language = "PY"
        root = "~/cp"
        host = "https://codeforces.com/"
        proxy = "socks5://127.0.0.1:1080"

        [cpp]
        compiler = "g++-15"
        flags = "-DLOCAL -fsanitize=address"
        submit = 89
        template = "~/cp/t.cpp"

        [hs]
        build = ["ghc", "-O2", "{src}", "-o", "{exe}"]
        run = "{exe}"
        submit = "Haskell"
        """.replace("\n        ", "\n"),
    )
    settings = Settings.load()
    assert settings.language == "py" and settings.host == DEFAULT_HOST
    assert settings.root_folder().name == "cp"
    assert settings.language_settings("cpp") == LanguageSettings(
        compiler="g++-15",
        flags=("-DLOCAL", "-fsanitize=address"),
        submit="89",
        template="~/cp/t.cpp",
    )
    hs = settings.language_settings("hs")
    assert hs.build == ("ghc", "-O2", "{src}", "-o", "{exe}") and hs.run == ("{exe}",)
    assert settings.warnings == []


def test_an_empty_build_means_nothing_to_build(config_dir):
    write(config_dir / "config.toml", '[py]\nbuild = ""\nrun = "pypy3 {src}"\n')
    conf = Settings.load().language_settings("py")
    assert conf.build == () and conf.run == ("pypy3", "{src}")


def test_unknown_keys_are_warnings(config_dir):
    write(config_dir / "config.toml", 'langauge = "cpp"\n[cpp]\ncompile = "g++"\n')
    assert Settings.load().warnings == [
        'config.toml: unknown setting "langauge"',
        'config.toml: [cpp]: unknown setting "compile"',
    ]


@pytest.mark.parametrize(
    "text,message",
    [
        ("language = \n", "isn't valid TOML"),
        ('host = "codeforces.com"\n', 'host should be like "https://codeforces.com"'),
        ("language = true\n", "language should be text"),
        ("[cpp]\nflags = 1\n", r"\[cpp\] flags should be text"),
        ("[cpp]\nrun = [1, 2]\n", "a list of words"),
    ],
)
def test_mistakes(config_dir, text, message):
    write(config_dir / "config.toml", text)
    with pytest.raises(CFError, match=message):
        Settings.load()


def test_update_creates_an_explained_file(config_dir):
    settings = Settings.load()
    settings.update("language", "py")
    text = (config_dir / "config.toml").read_text()
    assert 'language = "py"' in text and "# compiler =" in text
    assert settings.language == "py"
    assert Settings.load().language == "py"


def test_update_keeps_comments(config_dir):
    path = write(
        config_dir / "config.toml",
        '# mine\nlanguage = "cpp"  # what I use\n\n[cpp]\n# my flags\nflags = "-DLOCAL"\n',
    )
    settings = Settings.load()
    settings.update("submit", "54", table="cpp")
    settings.update("submit", "70", table="py")
    settings.update("language", "py")
    text = path.read_text()
    assert "# mine" in text and "# what I use" in text and "# my flags" in text
    assert settings.language_settings("cpp").submit == "54"
    assert settings.language_settings("py").submit == "70"
    assert Settings.load().language == "py"


def test_write_default(config_dir):
    settings = Settings(language="go")
    path = settings.write_default()
    assert 'language = "go"' in path.read_text()
    path.write_text('language = "c"\n')
    settings.write_default()  # NOTE: an existing file is the user's
    assert path.read_text() == 'language = "c"\n'


# ┌──────────────────────────────────────────────────────────┐
# │                   From cf-tool 0.3                       │
# └──────────────────────────────────────────────────────────┘

# Fau's own 0.3 config: two templates claim .cpp, the default one (cpp17) has
# no build step
OLD = {
    "template": [
        {
            "alias": "cpp",
            "lang": "89",
            "path": "/home/u/.config/cf/template.cpp",
            "suffix": ["cpp", "cc", "cxx"],
            "before_script": "g++ -std=c++23 -O2 -o $%file%$ $%full%$",
            "script": "./$%file%$",
            "after_script": "rm $%file%$",
        },
        {
            "alias": "py",
            "lang": "31",
            "path": "/home/u/.config/cf/template.py",
            "suffix": ["py"],
            "before_script": "",
            "script": "python3 $%full%$",
            "after_script": "",
        },
        {
            "alias": "cpp17",
            "lang": "54",
            "path": "/home/u/.config/cf/template.cpp",
            "suffix": ["cpp"],
            "before_script": "",
            "script": "./$%file%$",
            "after_script": "",
        },
    ],
    "default": 2,
    "gen_after_parse": False,
    "host": "https://codeforces.com",
    "proxy": "",
    "folder_name": {"root": "cf", "contest": "contest"},
}


def test_migrate_an_old_config(config_dir):
    write(config_dir / "config", json.dumps(OLD))
    notes = migrate()
    settings = Settings.load()
    assert settings.language == "cpp"
    assert settings.language_settings("cpp") == LanguageSettings(
        submit="54", template="/home/u/.config/cf/template.cpp"  # NOTE: the default, cpp17
    )
    assert settings.language_settings("py") == LanguageSettings(
        submit="31", template="/home/u/.config/cf/template.py"
    )
    assert settings.warnings == []
    text = "\n".join(notes)
    assert "Moved your settings" in text and 'language = "cpp"' in text
    assert 'scripts of "cpp17", "py"' in text
    assert 'the template "cpp" (C++ has one setting now, and "cpp17" was kept)' in text
    assert "submit = 54 (GNU G++17 7.3.0)" in text
    assert (config_dir / "config").exists()  # NOTE: left for cf-tool 0.3
    assert migrate() == []  # NOTE: once


def test_migrate_from_the_go_tool(config_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    go = {
        "template": [
            {
                "alias": "hs",
                "lang": "12",
                "path": "",
                "suffix": ["hs"],
                "before_script": "ghc -O2 $%full%$ -o $%file%$",
                "script": "./$%file%$",
                "after_script": "rm $%file%$",
            }
        ],
        "default": 0,
        "host": "https://codeforces.ml",
        "proxy": "http://127.0.0.1:2333",
    }
    write(tmp_path / ".cf" / "config", json.dumps(go))
    notes = migrate()
    settings = Settings.load()
    assert settings.language == "hs"
    assert (settings.host, settings.proxy) == ("https://codeforces.ml", "http://127.0.0.1:2333")
    hs = settings.language_settings("hs")
    assert hs.build == ("ghc", "-O2", "{src}", "-o", "{name}") and hs.run == ("./{name}",)
    assert hs.submit == "12"
    assert any("[hs]" in note for note in notes)


def test_old_folder_placeholders(config_dir):
    from cf_tool.settings import _new_placeholders

    assert _new_placeholders("$%path%$$%file%$") == "./{name}"
    assert _new_placeholders("ghc $%path%$$%full%$ -o $%file%$") == "ghc {src} -o {name}"
    assert _new_placeholders("runhaskell $%full%$") == "runhaskell {src}"


def test_a_linked_settings_file_stays_a_link(config_dir, tmp_path):
    real = tmp_path / "dotfiles" / "config.toml"
    real.parent.mkdir()
    real.write_text('language = "cpp"\n')
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").symlink_to(real)
    Settings.load().update("language", "py")
    assert (config_dir / "config.toml").is_symlink()
    assert 'language = "py"' in real.read_text()


def test_nothing_to_migrate(config_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert migrate() == []
    assert not (config_dir / "config.toml").exists()


def test_a_broken_old_config(config_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    write(config_dir / "config", "{not json")
    assert "Could not read your old settings" in migrate()[0]
    assert not (config_dir / "config.toml").exists()


def test_another_first_setting_leaves_the_language_open(config_dir):
    # NOTE: or cf get would never ask, and write C++ for a Python user
    settings = Settings.load()
    settings.update("submit", "70", table="py")
    assert Settings.load().language == ""
    assert '# language = "cpp"' in (config_dir / "config.toml").read_text()
    settings.update("language", "py")
    assert Settings.load().language == "py"
    text = (config_dir / "config.toml").read_text()
    assert text.index('language = "py"') < text.index("# [cpp]")  # NOTE: in its place


def test_custom_folder_names_are_mentioned(config_dir):
    old = dict(OLD, folder_name={"root": "codeforces", "contest": "contest"})
    write(config_dir / "config", json.dumps(old))
    assert any("your folder names" in note for note in migrate())


def test_remove_goes_back_to_the_default(config_dir):
    path = write(
        config_dir / "config.toml",
        '# mine\nproxy = "http://x:1"\n\n[cpp]\n# why\nsubmit = "54"\nflags = "-DLOCAL"\n'
        '[py]\nsubmit = "70"\n',
    )
    settings = Settings.load()
    settings.remove("submit", table="cpp")
    settings.remove("submit", table="py")  # NOTE: [py] is empty then: it goes
    settings.remove("proxy")
    settings.remove("compiler", table="rs")  # NOTE: nothing there: nothing happens
    text = path.read_text()
    assert "# mine" in text and "[py]" not in text and 'flags = "-DLOCAL"' in text
    assert settings.proxy == "" and settings.language_settings("cpp").submit == ""
    assert Settings.load().language_settings("cpp").flags == ("-DLOCAL",)
