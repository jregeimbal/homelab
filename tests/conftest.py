"""Pytest bootstrap for tests of scripts/manifest-contract-test.py.

The script file's name contains dashes (manifest-contract-test.py), which are
not valid in a module identifier, so it cannot be imported by name.  Insert the
repo root into sys.path (so the `scripts` directory resolves as a namespace
package) and register the script under the conventional name
`scripts.manifest_contract_test` via importlib.
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_SCRIPT = os.path.join(ROOT, "scripts", "manifest-contract-test.py")
if os.path.exists(_SCRIPT):
    import scripts  # namespace package rooted at the repo root

    _name = "scripts.manifest_contract_test"
    if _name not in sys.modules:
        _spec = importlib.util.spec_from_file_location(_name, _SCRIPT)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
    setattr(scripts, "manifest_contract_test", sys.modules[_name])

_SCRIPT_UC = os.path.join(ROOT, "scripts", "upstream-changelog.py")
if os.path.exists(_SCRIPT_UC):
    import scripts  # namespace package rooted at the repo root

    _name_uc = "scripts.upstream_changelog"
    if _name_uc not in sys.modules:
        _spec_uc = importlib.util.spec_from_file_location(_name_uc, _SCRIPT_UC)
        _mod_uc = importlib.util.module_from_spec(_spec_uc)
        sys.modules[_name_uc] = _mod_uc
        _spec_uc.loader.exec_module(_mod_uc)
    setattr(scripts, "upstream_changelog", sys.modules[_name_uc])