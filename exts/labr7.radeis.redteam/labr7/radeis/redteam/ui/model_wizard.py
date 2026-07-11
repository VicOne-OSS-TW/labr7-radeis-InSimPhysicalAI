"""Model Installation Wizard — public entry point.

The implementation is split into four step modules under ui/wizard/:

  wizard/choose_server.py   — Step 1: Choose installation path (Local / Remote)
  wizard/sidecar_setup.py  — Step 2: Install env (Path A) / Connect to remote (Path B)
  wizard/model_download.py — Step 3: Download model (Path A) / Load model (Path B)
  wizard/complete_test.py  — Step 4: Setup complete, server status, test inference

External callers continue to use:
  from .model_wizard import open_wizard, ModelWizard
"""
from .wizard import open_wizard, ModelWizard  # noqa: F401

__all__ = ["open_wizard", "ModelWizard"]
