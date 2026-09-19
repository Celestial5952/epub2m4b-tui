from __future__ import annotations

import configparser
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PACKAGING = ROOT / "packaging" / "debian"


def test_desktop_entry_exposes_terminal_application() -> None:
    desktop_path = ROOT / "resources" / "desktop" / "epub2m4b.desktop"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(desktop_path, encoding="utf-8")

    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Name"] == "EPUB2M4B Audiobook Studio"
    assert entry["Exec"] == "epub2m4b"
    assert entry["TryExec"] == "epub2m4b"
    assert entry["Icon"] == "epub2m4b"
    assert entry["Terminal"] == "true"
    assert entry["Categories"].endswith(";")


def test_debian_control_declares_runtime_dependencies() -> None:
    control = (PACKAGING / "control.in").read_text(encoding="utf-8")

    assert "Package: epub2m4b\n" in control
    assert "Architecture: @ARCHITECTURE@\n" in control
    assert "python3 (>= 3.14)" in control
    assert "ffmpeg" in control
    assert "Installed-Size: @INSTALLED_SIZE@\n" in control


def test_runtime_lock_is_exact_and_excludes_development_tools() -> None:
    lines = [
        line
        for line in (PACKAGING / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]

    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==[^=\s]+", line) for line in lines)
    assert any(line.startswith("openai==") for line in lines)
    assert any(line.startswith("textual==") for line in lines)
    assert not any(line.lower().startswith(("pytest==", "ruff==", "coverage==")) for line in lines)


def test_launcher_uses_isolated_private_runtime() -> None:
    launcher = (PACKAGING / "epub2m4b").read_text(encoding="utf-8")
    python_launcher = (PACKAGING / "launcher.py").read_text(encoding="utf-8")

    assert "/usr/bin/python3 -I /usr/lib/epub2m4b/launcher.py" in launcher
    assert "PYTHONPATH" not in launcher
    assert str(ROOT) not in launcher
    assert "sys.path.insert" in python_launcher


def test_python_launcher_finds_only_its_private_package(tmp_path: Path) -> None:
    package = tmp_path / "epub2m4b"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "def main():\n    print('private-runtime-ok')\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "launcher.py").write_bytes((PACKAGING / "launcher.py").read_bytes())

    result = subprocess.run(
        [sys.executable, "-I", str(tmp_path / "launcher.py")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "private-runtime-ok\n"
    assert result.stderr == ""


def test_build_targets_ubuntu_2604_without_packaging_user_state() -> None:
    script = (PACKAGING / "build.sh").read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert 'readonly expected_os="26.04"' in script
    assert '"${python_version}" != "3.14"' in script
    assert "dpkg-deb --root-owner-group --build" in script
    assert "/usr/lib/epub2m4b" in script
    assert 'cp -a -- "${repo_root}/.venv"' not in script
    assert ".config/epub2m4b" not in script
    assert ".cache/epub2m4b" not in script


def test_scalable_icon_is_packaged() -> None:
    icon = ROOT / "resources" / "icons" / "hicolor" / "scalable" / "apps" / "epub2m4b.svg"
    contents = icon.read_text(encoding="utf-8")

    assert contents.startswith("<?xml")
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in contents


def test_control_template_builds_a_valid_debian_archive(tmp_path: Path) -> None:
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        pytest.skip("dpkg-deb is only required on the Ubuntu packaging host")

    package_root = tmp_path / "package"
    control_directory = package_root / "DEBIAN"
    executable_directory = package_root / "usr" / "bin"
    control_directory.mkdir(parents=True)
    executable_directory.mkdir(parents=True)
    control = (PACKAGING / "control.in").read_text(encoding="utf-8")
    control = control.replace("@VERSION@", "0.1.0")
    control = control.replace("@ARCHITECTURE@", "amd64")
    control = control.replace("@INSTALLED_SIZE@", "1")
    (control_directory / "control").write_text(control, encoding="utf-8")
    packaged_launcher = executable_directory / "epub2m4b"
    packaged_launcher.write_bytes((PACKAGING / "epub2m4b").read_bytes())
    packaged_launcher.chmod(0o755)
    artifact = tmp_path / "epub2m4b_0.1.0_amd64.deb"

    build = subprocess.run(
        [dpkg_deb, "--root-owner-group", "--build", str(package_root), str(artifact)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert build.returncode == 0, build.stderr
    assert artifact.is_file()
    package_name = subprocess.run(
        [dpkg_deb, "--field", str(artifact), "Package"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert package_name.stdout.strip() == "epub2m4b"
    contents = subprocess.run(
        [dpkg_deb, "--contents", str(artifact)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "./usr/bin/epub2m4b" in contents.stdout
