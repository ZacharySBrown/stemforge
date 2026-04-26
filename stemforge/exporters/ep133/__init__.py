"""EP-133 K.O. II song-mode export.

Public entry points (all imported from submodules):
- ``song_format`` (Track A): ``PpakSpec``, ``Pattern``, ``SceneSpec``, ``PadSpec``,
  ``Event`` dataclasses describing a song-mode project.
- ``ppak_writer`` (Track A): ``build_ppak(spec, reference_template)`` byte builder.
- ``song_resolver`` (Track C): ``resolve_scenes(arrangement, manifest)`` →
  list of per-locator ``Snapshot``s.
- ``song_synthesizer`` (Track C): ``synthesize(snapshots, manifest, ...)`` →
  ``PpakSpec`` ready for the writer.
"""
