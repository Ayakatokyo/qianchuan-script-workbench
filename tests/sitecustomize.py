"""Test-only legacy names mapped exclusively to this repository scripts."""
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).parent
_LAYOUT = json.loads((_ROOT / "module_layout.json").read_text())
_REVERSE = {Path(file).stem: name for name, file in _LAYOUT.items()}
_PACKAGES = {"short_video_foundation"}
for _name in _LAYOUT:
    _parts = _name.split(".")
    _PACKAGES.update(".".join(_parts[:i]) for i in range(2, len(_parts)))

class _AliasLoader(importlib.abc.Loader):
    def __init__(self, flat, legacy, path): self.flat, self.legacy, self.path = flat, legacy, path
    def create_module(self, spec): return sys.modules.get(self.flat) or sys.modules.get(self.legacy)
    def exec_module(self, module):
        sys.modules[self.flat] = module
        sys.modules[self.legacy] = module
        if getattr(module, "__legacy_alias_ready__", False): return
        try:
            exec(compile(self.path.read_bytes(), str(self.path), "exec"), module.__dict__)
            module.__legacy_alias_ready__ = True
        except BaseException:
            sys.modules.pop(self.flat, None)
            sys.modules.pop(self.legacy, None)
            raise
    def get_code(self, fullname): return compile(self.path.read_bytes(), str(self.path), "exec")

class _LegacyFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in _LAYOUT:
            file = _ROOT / _LAYOUT[fullname]
            return importlib.util.spec_from_file_location(fullname, file, loader=_AliasLoader(file.stem, fullname, file))
        if fullname in _REVERSE:
            legacy = _REVERSE[fullname]
            file = _ROOT / _LAYOUT[legacy]
            return importlib.util.spec_from_file_location(fullname, file, loader=_AliasLoader(fullname, legacy, file))
        if fullname in _PACKAGES:
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        return None

sys.meta_path.insert(0, _LegacyFinder())

# Tests are offline: synthetic transports may run; live sockets must not.
import socket
def _deny_network(*args, **kwargs):
    raise RuntimeError("Network disabled during the standalone offline test suite")
socket.socket.connect = _deny_network
socket.create_connection = _deny_network
