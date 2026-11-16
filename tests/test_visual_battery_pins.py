# SPDX-FileCopyrightText: 2026 WSHAPER <42714629+WSHAPER@users.noreply.github.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The visual-baseline metadata contract, pinned hermetically (no marp,
no Chromium).

The first CI battery run failed the pixel comparison with ~8000 diff
pixels while every version pin matched, because the metadata recorded
the marp and Chromium identities but not the host platform: the runner
and the reference machine render the same deck with different font
antialiasing. The platform provenance of
``tests/battery/baselines/metadata.json``, the skip rule that consumes
it, and the update path that records it are proven here in the DEFAULT
gate suite, so a provenance regression fails ``pytest -q`` everywhere,
not only in the battery lane that needs the toolchain. The same
hermetic-contract shape is used by ``tests/test_golden_hashes.py`` for
the golden-render pins.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from tests import golden_hashes as gh
from tests import visual_battery as vb

PLATFORM_SHAPE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
UPDATE_CMD = "scripts/battery_update.py --baselines"


def test_platform_identifier_is_shared_with_golden_pins() -> None:
    """One identifier for every platform-bound battery datum: the visual
    metadata must not grow a divergent platform spelling, or skips would
    fire between two data files generated on the same host."""
    assert vb.platform_id is gh.platform_id


def test_committed_metadata_carries_platform_provenance() -> None:
    """The committed metadata must record the platform its PNGs were
    rendered on: a missing platform field is exactly the state that
    failed the first CI battery run (matching versions, different font
    stack), because the comparison would run against pixels it can never
    match."""
    metadata = vb.read_metadata()
    render_pins = metadata.get("render")
    assert isinstance(render_pins, dict), (
        f"metadata.json carries no render pins; regenerate with {UPDATE_CMD}."
    )
    recorded = render_pins.get("platform")
    assert isinstance(recorded, str) and PLATFORM_SHAPE.fullmatch(recorded), (
        f"render pins carry no parseable platform ({recorded!r}); the "
        "baseline comparison cannot decide comparability. Regenerate "
        f"with {UPDATE_CMD} on the reference platform."
    )


def test_skip_reason_when_platform_differs() -> None:
    """The CI shape: identical version pins, different font stack."""
    reason = vb.platform_skip_reason("debian-amd64", "ubuntu-amd64")
    assert reason is not None
    assert "ubuntu-amd64" in reason and "debian-amd64" in reason
    assert "Determinism still gated" in reason
    assert "platform-bound" in reason
    assert UPDATE_CMD in reason


def test_skip_reason_when_platform_not_recorded() -> None:
    """Legacy metadata (generated before the field existed) skips with
    its own actionable reason instead of comparing blindly."""
    reason = vb.platform_skip_reason(None, "debian-amd64")
    assert reason is not None
    assert "predates platform provenance" in reason
    assert UPDATE_CMD in reason


def test_no_skip_when_platform_matches() -> None:
    """Same platform: the baseline comparison must RUN (None reason), so
    the pixel pin stays active on the reference platform."""
    reason = vb.platform_skip_reason("debian-amd64", "debian-amd64")
    assert reason is None


def test_update_baselines_records_current_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The explicit update path pins the platform it regenerates on, so
    a git diff of metadata.json always tells which host produced the
    PNGs. Pinned hermetically by stubbing the render and the version
    probes: the battery data directory and every toolchain call are
    redirected, nothing here needs marp or Chromium."""
    baseline_dir = tmp_path / "baselines"
    monkeypatch.setattr(vb, "BASELINE_DIR", baseline_dir)
    monkeypatch.setattr(vb, "METADATA_FILE", baseline_dir / "metadata.json")
    fake_slides = [b"fake-png-one", b"fake-png-two"]
    monkeypatch.setattr(vb, "render_slides", lambda markdown, workdir: fake_slides)
    monkeypatch.setattr(vb, "marp_version", lambda: "marp vTEST")
    monkeypatch.setattr(vb, "chrome_version", lambda: "chromium vTEST")
    monkeypatch.setattr(vb, "platform_id", lambda: "ubuntu-amd64")

    names = vb.update_baselines(tmp_path / "work")

    assert names == ["visual.001.png", "visual.002.png"]
    assert (baseline_dir / "visual.001.png").read_bytes() == b"fake-png-one"
    metadata = vb.read_metadata()
    render_pins = metadata.get("render")
    assert isinstance(render_pins, dict)
    assert render_pins.get("platform") == "ubuntu-amd64"
    assert render_pins.get("marp_cli_version") == "marp vTEST"
    slides = metadata.get("slides")
    assert isinstance(slides, dict)
    assert slides["1"]["sha256"] == hashlib.sha256(b"fake-png-one").hexdigest()
