# SPDX-FileCopyrightText: 2026 WSHAPER <42714629+WSHAPER@users.noreply.github.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pins-file contract, pinned hermetically (no marp, no Chromium).

The provenance format of ``tests/golden_render_hashes.txt`` and the
comparability rules it encodes are proven here in the DEFAULT gate
suite: the first CI battery run failed every pin comparison because
the provenance captured the marp version but not the host platform,
and no hermetic test existed to catch the gap, so the contract was
only ever exercised in the lane that needs the toolchain. A
provenance regression now fails ``pytest -q`` everywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import golden_hashes as gh

PLATFORM_SHAPE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")


def test_platform_id_is_a_stable_distro_arch_id() -> None:
    live = gh.platform_id()
    assert PLATFORM_SHAPE.fullmatch(live), (
        f"platform id {live!r} is not a distro-arch pair; the pins file "
        "provenance would be unparseable or ambiguous."
    )
    assert gh.platform_id() == live  # stable within a run


def test_platform_id_normalizes_arch_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """x86_64/AMD64 collapse to amd64; a Linux without a parsable
    /etc/os-release keeps the bare system name instead of crashing the
    skip decision; non-Linux systems are identified by name+arch."""

    def linux(distro_id: str, machine: str) -> None:
        monkeypatch.setattr(gh.platform, "system", lambda: "Linux")
        monkeypatch.setattr(gh.platform, "machine", lambda: machine)
        monkeypatch.setattr(
            gh.platform, "freedesktop_os_release", lambda: {"ID": distro_id}
        )

    def no_os_release() -> dict[str, str]:
        raise OSError("no os-release")

    linux("debian", "x86_64")
    assert gh.platform_id() == "debian-amd64"
    linux("ubuntu", "AMD64")
    assert gh.platform_id() == "ubuntu-amd64"
    monkeypatch.setattr(gh.platform, "freedesktop_os_release", no_os_release)
    assert gh.platform_id() == "linux-amd64"
    monkeypatch.setattr(gh.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(gh.platform, "machine", lambda: "arm64")
    assert gh.platform_id() == "darwin-arm64"


def test_committed_hashes_file_carries_full_provenance() -> None:
    """The committed file must record marp AND platform: a missing
    platform line is exactly the state that failed every pin on the
    first CI run (same marp version, different font stack)."""
    pins, provenance = gh.parse_pins(gh.HASHES_FILE.read_text(encoding="utf-8"))
    assert provenance["marp"], "pins without marp provenance compare blindly"
    recorded = provenance["platform"]
    assert recorded is not None, (
        "pins without platform provenance compare across incompatible "
        f"font stacks; regenerate with {gh.UPDATE_ENV}=1 on the "
        "reference platform."
    )
    assert PLATFORM_SHAPE.fullmatch(recorded), recorded
    assert set(pins) == {
        (deck, fmt) for deck in gh.GOLDEN_DECKS for fmt in gh.FORMATS
    }, "the pin matrix must cover every canonical deck in every format"
    for key, digest in pins.items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (
            f"{key}: {digest!r} is not a sha256 hex pin"
        )


def test_write_and_parse_round_trip(tmp_path: Path) -> None:
    """The writer and the parser agree on the format, so the update
    path regenerates a file the gate reads back identically."""
    keys = [(deck, fmt) for deck in gh.GOLDEN_DECKS for fmt in gh.FORMATS]
    pins = {key: f"{i:064x}" for i, key in enumerate(keys)}
    target = tmp_path / "hashes.txt"
    gh.write_pins(target, pins, "marp v9.9.9", "debian-amd64")
    reparsed, provenance = gh.parse_pins(target.read_text(encoding="utf-8"))
    assert reparsed == pins
    assert provenance == {"marp": "marp v9.9.9", "platform": "debian-amd64"}


def test_parse_reads_provenance_and_tolerates_legacy_header() -> None:
    """A header without a platform line (every file generated before
    this field existed) parses with platform None, never crashes, and
    pin rows ignore comment noise."""
    legacy = (
        "# Golden-render SHA-256 pins ...\n"
        "# marp: @marp-team/marp-cli v4.5.1 (w/ core v4.4.0)\n"
        "# platform: debian-amd64\n"
        "# some other comment mentioning platform: in prose\n"
        "deck.md html " + "a" * 64 + "\n"
    )
    pins, provenance = gh.parse_pins(legacy)
    assert pins == {("deck", "html"): "a" * 64}
    assert provenance == {
        "marp": "@marp-team/marp-cli v4.5.1 (w/ core v4.4.0)",
        "platform": "debian-amd64",
    }
    without_platform = legacy.replace("# platform: debian-amd64\n", "")
    _, legacy_provenance = gh.parse_pins(without_platform)
    assert legacy_provenance["platform"] is None
    assert legacy_provenance["marp"] is not None


def test_skip_reason_when_marp_differs() -> None:
    reason = gh.provenance_skip_reason(
        "marp v4.5.1", "debian-amd64", "marp v4.2.3", "debian-amd64"
    )
    assert reason is not None
    assert "marp v4.2.3" in reason and "marp v4.5.1" in reason
    assert "Byte-identity still gated" in reason
    assert gh.UPDATE_ENV in reason


def test_skip_reason_when_platform_differs() -> None:
    """The CI shape: identical marp versions, different font stack."""
    reason = gh.provenance_skip_reason(
        "marp v4.5.1", "debian-amd64", "marp v4.5.1", "ubuntu-amd64"
    )
    assert reason is not None
    assert "ubuntu-amd64" in reason and "debian-amd64" in reason
    assert "Byte-identity still gated" in reason
    assert "platform-bound" in reason
    assert gh.UPDATE_ENV in reason


def test_skip_reason_when_platform_not_recorded() -> None:
    reason = gh.provenance_skip_reason(
        "marp v4.5.1", None, "marp v4.5.1", "debian-amd64"
    )
    assert reason is not None
    assert "platform provenance" in reason
    assert gh.UPDATE_ENV in reason


def test_no_skip_when_provenance_matches() -> None:
    """Both fields equal: the pin comparison must RUN (None reason),
    so the stability pin stays active on the reference platform."""
    reason = gh.provenance_skip_reason(
        "marp v4.5.1", "debian-amd64", "marp v4.5.1", "debian-amd64"
    )
    assert reason is None
