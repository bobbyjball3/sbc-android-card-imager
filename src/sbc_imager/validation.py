"""Semantic validation of manifests against Cannoli and exFAT rules.

The public API is re-exported from the cohesive ``validation_*`` modules:
``Warning``, ``Destination``, ``iter_destinations``, and ``validate_manifest``.
"""

from __future__ import annotations

from sbc_imager.config import Manifest
from sbc_imager.sizes import check_image
from sbc_imager.validation_checks import (
    check_apks,
    check_artifacts,
    check_overlay,
    check_shader,
    check_sources,
)
from sbc_imager.validation_common import Warning, error
from sbc_imager.validation_destinations import Destination, iter_destinations
from sbc_imager.validation_exfat import check_destinations

__all__ = ["Destination", "Warning", "iter_destinations", "validate_manifest"]

_MIB = 1024 * 1024


def _check_nonempty_entries(manifest: Manifest, destinations: list[Destination]) -> None:
    counts = (
        ("overlay", len(manifest.overlays)),
        ("shader", len(manifest.shaders)),
        ("apk", len(manifest.apks)),
        ("artifact", len(manifest.artifacts)),
    )
    present = {(destination.kind, destination.entry_index) for destination in destinations}
    for kind, count in counts:
        for index in range(count):
            if (kind, index) not in present:
                error("empty-entry", f"{kind}[{index}] produces no destinations")


def validate_manifest(manifest: Manifest) -> list[Warning]:
    """Raise ``ConfigError`` for invalid manifests; return non-fatal warnings."""
    warnings: list[Warning] = []
    pinned_size = check_image(manifest.image)
    sources, referenced = check_sources(manifest)
    total = 0
    for index, entry in enumerate(manifest.overlays):
        total += check_overlay(entry, index, warnings)
    for index, entry in enumerate(manifest.shaders):
        total += check_shader(entry, index)
    total += check_apks(manifest)
    total += check_artifacts(manifest, warnings)

    for source_id, index in sources.items():
        if source_id not in referenced:
            warnings.append(
                Warning("unused-source", f"source[{index}] '{source_id}' is not referenced", index)
            )

    destinations = list(iter_destinations(manifest))
    _check_nonempty_entries(manifest, destinations)
    check_destinations(destinations, warnings)
    if pinned_size is not None:
        overhead = max(64 * _MIB, (total + 99) // 100)
        if total + overhead > pinned_size:
            error(
                "content-overflow",
                f"local content {total} + overhead {overhead} exceeds pinned size {pinned_size}",
            )
    return warnings
