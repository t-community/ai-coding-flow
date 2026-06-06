# Root conftest: compatibility shim for py 1.4.24 + pytest 8.x.
# py 1.4.24 does not accept pathlib.Path in py.path.local(); pytest 8
# passes Path objects to legacy_path(), causing an INTERNALERROR.
# We patch py.path.local.__init__ to convert pathlib.Path → str before
# the original init logic runs.
import pathlib
import py.path


_orig_local_init = py.path.local.__init__


def _patched_local_init(self, path=None, expanduser=False):
    if isinstance(path, pathlib.Path):
        path = str(path)
    _orig_local_init(self, path=path, expanduser=expanduser)


py.path.local.__init__ = _patched_local_init
