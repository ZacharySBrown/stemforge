"""Helper modules for the Live-in-the-loop smoke runner.

Split out of ``live_runner.py`` so the orchestration code stays
readable and the helpers are independently testable.

Modules:
    osa: ``osascript`` subprocess wrappers (open Live, close Live, save).
    sf_remote_shim: thin adapter around ``tools/sf_remote.py`` so the
        smoke tests can fire UDP intents and dump dicts without
        re-implementing the OSC envelope.
    fixtures: discovery + status (``MISSING`` | ``PRESENT`` | ``CORRUPT``)
        for the fixture ``.als`` files. Drives the ``skip-if-no-fixture``
        decorator.
    assertions: small, focused assertion helpers used by the smoke tests
        (``assert_state``, ``assert_curation_file``, ``assert_bounce_dir``).
"""
