import os
from pathlib import Path

from shared.dev_env import load_devenv


def test_load_devenv_with_default_path(tmp_path, monkeypatch):
    env_file = tmp_path / ".devenv"
    env_file.write_text(
        """
        # comment line
        FOO=bar
        QUOTED="baz"
        SPACED = spaced value
        
        INVALID_LINE
        
        # another comment
        """.strip()
    )

    # Ensure variables are not preset
    for key in ["FOO", "QUOTED", "SPACED"]:
        monkeypatch.delenv(key, raising=False)

    load_devenv(default_path=env_file)

    assert os.environ.get("FOO") == "bar"
    assert os.environ.get("QUOTED") == "baz"
    assert os.environ.get("SPACED") == "spaced value"


def test_load_devenv_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".devenv"
    env_file.write_text("FOO=from-file\n")

    monkeypatch.setenv("FOO", "preset")
    load_devenv(default_path=env_file)
    assert os.environ.get("FOO") == "preset"


def test_load_devenv_env_var_overrides_default(tmp_path, monkeypatch):
    default_file = tmp_path / "default.env"
    default_file.write_text("FOO=default\n")

    override_file = tmp_path / "override.env"
    override_file.write_text("FOO=override\n")

    monkeypatch.setenv("DSXCONNECTOR_ENV_FILE", str(override_file))
    # Clear any existing value
    monkeypatch.delenv("FOO", raising=False)

    load_devenv(default_path=default_file)
    assert os.environ.get("FOO") == "override"

