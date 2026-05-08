"""AbstractProjector — interface for target-specific song-mode export.

A projector takes the inputs to a song-mode export and produces a
target-specific bundle of bytes (.ppak for EP-133; future targets get
their own implementations). Phase 1 ships exactly one implementation:
:class:`stemforge.exporters.ep133.projector.Ep133Projector`.

The interface is deliberately minimal — three method names, no signature
constraints — so it can be exactly as wide as EP-133 needs and no wider.
Each subclass fully types its own ``capabilities``, ``validate``, and
``project`` methods. Phase 2 will narrow inputs to a shared shape
(``ProjectSpec``) once the abstract scene model lands; for now each
projector takes whatever its current pipeline takes.

This is distinct from :class:`stemforge.exporters.base.AbstractExporter`,
which targets the older session-mode workflow (raw stems/slices →
per-target manifest). Song-mode (locator-driven scenes → byte bundle)
is what the projector covers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractProjector(ABC):
    """Target-specific projection from a song-mode input to bytes."""

    @abstractmethod
    def capabilities(self) -> dict:
        """Device limits and supported features.

        Returned shape is target-specific; minimum useful keys for any
        target include ``device`` (str id), the maxima the target enforces,
        and any enumerations the UI surfaces (e.g. groups, project slots).
        Used by upstream UI surfaces and pre-flight validation.
        """

    @abstractmethod
    def validate(self, *args, **kwargs) -> list[str]:
        """Pre-flight check — returns a list of human-readable warnings.

        Empty list ⇒ no warnings. Subclass-specific argument shapes;
        not constrained at the abstract layer because Phase 1 keeps each
        projector's natural input shape until the abstract scene model
        lands in Phase 2.
        """

    @abstractmethod
    def project(self, *args, **kwargs) -> bytes:
        """Build the target-specific export bundle and return its bytes.

        Raises on hard failure (missing inputs, exceeded limits, bad
        manifest, etc.). Soft warnings are surfaced via :meth:`validate`.
        """
