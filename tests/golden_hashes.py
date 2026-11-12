# SPDX-FileCopyrightText: 2026 WSHAPER <42714629+WSHAPER@users.noreply.github.com>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The golden-render pins file: format, provenance, comparability rules.

Rendered bytes are platform-bound: the OS font stack sits under marp's
Chromium, so the same deck under the identical marp-cli renders to
different bytes on Debian and on Ubuntu (the first CI battery run
proved it: every pin comparison failed with matching versions). The
pins therefore carry a provenance header recording BOTH the marp that
produced them AND the host platform, and the pin comparison runs only
when both match the running environment (Playwright's rule: baselines
are per-browser AND per-platform). Byte-identity, render twice and
compare within one run, is environment-independent and always gates.

The format and the skip rules live in this plain module, not in the
battery test file, so the default hermetic suite pins the contract
(``tests/test_golden_hashes.py``) without marp or Chromium, while the
battery lane (``tests/test_golden_render.py``) renders through the
real delivery seams and applies the rules to the committed file. The
same helper-module shape is used by the visual battery
(``tests/visual_battery.py``).
"""

from __future__ import annotations

import platform
from pathlib import Path

#: The committed pins file, next to this module.
HASHES_FILE = Path(__file__).resolve().parent / "golden_render_hashes.txt"

#: Every committed canonical deck: the read-only fixtures directory.
GOLDEN_DECKS = (
    "deck",
    "deck-code-audit",
    "deck-constructs",
    "deck-directives",
    "deck-images",
)
FORMATS = ("html", "pdf", "pptx")
UPDATE_ENV = "SLIDEPREPPER_UPDATE_GOLDEN_HASHES"

#: Provenance as recorded in (and parsed from) the header: the marp
#: version line and the platform line, either None when absent.
Provenance = dict[str, str | None]


def platform_id() -> str:
    """The stable host identity rendered bytes are bound to: OS
    distribution plus machine architecture (``debian-amd64``,
    ``ubuntu-amd64``, ``darwin-arm64``).

    The distro is what moves the font stack under Chromium; the kernel
    release is deliberately excluded because an apt upgrade changes it
    without moving a single rendered byte, and machine-arch synonyms
    are normalized (x86_64/AMD64 to amd64, aarch64 to arm64) so the
    id does not wobble across OS spellings of the same silicon.
    """
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        machine = "amd64"
    elif machine in ("aarch64", "arm64"):
        machine = "arm64"
    system = platform.system().lower()
    distro = ""
    if system == "linux":
        try:
            os_release = platform.freedesktop_os_release()
        except (OSError, ValueError):
            # no parsable /etc/os-release: unknown Linux, keep the bare
            # system name rather than crashing the skip decision
            os_release = {}
        distro = str(os_release.get("ID", "")).strip().lower()
    return f"{distro or system}-{machine}"


def parse_pins(text: str) -> tuple[dict[tuple[str, str], str], Provenance]:
    """(pins, provenance) from the hashes-file text; provenance carries
    the recorded ``marp`` and ``platform`` (None when the header line
    is absent, i.e. the file predates that provenance field)."""
    pins: dict[tuple[str, str], str] = {}
    provenance: Provenance = {"marp": None, "platform": None}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            if line.startswith("# marp:"):
                provenance["marp"] = line.removeprefix("# marp:").strip()
            elif line.startswith("# platform:"):
                provenance["platform"] = line.removeprefix("# platform:").strip()
            continue
        deck_file, fmt, digest = line.split()
        pins[(deck_file.removesuffix(".md"), fmt)] = digest
    return pins, provenance


def write_pins(
    path: Path,
    pins: dict[tuple[str, str], str],
    marp_version: str | None,
    platform: str,
) -> None:
    """Rewrite the pins file: header (with the full provenance, the
    platform being where the pins are generated NOW) then the matrix
    rows in deck/format order."""
    lines = [
        "# Golden-render SHA-256 pins (Typst-style 32-byte pins; the",
        "# rendered artifacts themselves are NOT committed).",
        "#",
        "# Provenance the pins were generated under; a running marp or",
        "# host platform that differs skips the pin comparison",
        "# (byte-identity still gates):",
        f"# marp: {marp_version}",
        f"# platform: {platform}",
        "#",
        "# Update path (deliberate action, never automatic):",
        f"#   {UPDATE_ENV}=1 pytest -m battery tests/test_golden_render.py",
        "# (fails once by design: review the diff, commit this file, re-run)",
    ]
    for deck in GOLDEN_DECKS:
        lines.extend(
            f"{deck}.md {fmt} {pins[(deck, fmt)]}"
            for fmt in FORMATS
            if (deck, fmt) in pins
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def provenance_skip_reason(
    recorded_marp: str | None,
    recorded_platform: str | None,
    live_marp: str | None,
    live_platform: str,
) -> str | None:
    """Why the pin comparison cannot run in this environment, or None
    when it can (both provenance fields match). Byte-identity is not
    part of this decision: it gates in every environment, so a skip
    never weakens the determinism proof, only the cross-run stability
    pin that is only meaningful on the generating environment anyway.
    """
    if recorded_marp != live_marp:
        return (
            f"hash pin skipped: running marp '{live_marp}' != pinned "
            f"'{recorded_marp}'. Byte-identity still gated above. Re-pin "
            f"under the pinned toolchain with {UPDATE_ENV}=1 if this "
            "toolchain is the new reference."
        )
    if recorded_platform is None:
        return (
            "hash pin skipped: the hashes file predates platform "
            "provenance, so the host its pins were rendered on is "
            "unknown. Byte-identity still gated above. Regenerate with "
            f"{UPDATE_ENV}=1 on the reference platform."
        )
    if recorded_platform != live_platform:
        return (
            f"hash pin skipped: running platform '{live_platform}' != "
            f"pinned '{recorded_platform}'. Byte-identity still gated "
            "above. Rendered bytes are platform-bound (the OS font stack "
            "sits under marp's Chromium), so pins compare only on the "
            "platform that produced them; CI pin-comparison needs pins "
            f"generated on the runner, or re-pin with {UPDATE_ENV}=1 if "
            "this platform is the new reference."
        )
    return None
