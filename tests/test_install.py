"""flame_hook/install.sh, run against a temp install folder."""
import os
import subprocess

import pytest

from conftest import ROOT

SCRIPT = os.path.join(ROOT, "flame_hook", "install.sh")


def run(install_dir):
    env = dict(os.environ, OPENCLIP_INSTALL_DIR=str(install_dir))
    return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)


def test_installs_hook(tmp_path):
    dest = tmp_path / "openclip_editor"
    (dest / "__pycache__").mkdir(parents=True)
    result = run(dest)
    assert result.returncode == 0, result.stderr
    installed = dest / "openclip_editor.py"
    assert installed.read_bytes() == open(os.path.join(ROOT, "flame_hook",
                                                       "openclip_editor.py"), "rb").read()
    assert oct(installed.stat().st_mode & 0o777) == "0o644"
    assert not (dest / "__pycache__").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_unwritable_target_explains_sudo(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        result = run(locked / "openclip_editor")
    finally:
        locked.chmod(0o755)
    assert result.returncode != 0
    assert "sudo" in result.stdout + result.stderr
