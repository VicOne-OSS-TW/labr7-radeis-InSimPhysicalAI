# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-07-11

First public release of **Radeis - In-Sim Physical AI Safety Validator**.

### Added
- **Adversarial test pipeline** - the robot patrols a loop of sign stations on a
  moving platform, first with a clean baseline sign, then with one adversarial
  sample per station. Four attack categories: traffic signs, ISO warning signs,
  typography, adversarial patches. Stations per run are configurable and a
  running test can be paused and resumed.
- **Scenes & robots** - Patrol Loop (grid) and Warehouse scenes; robot presets
  for Boston Dynamics Spot (walking locomotion), Unitree Go2, Agility Digit v4,
  and Fourier GR-1.
- **Inference server** - out-of-process FastAPI server hosting
  `google/gemma-4-e2b-it`; auto-spawned locally or woken on a remote GPU host
  via the launcher daemon; system-tray status app with a Stop & Quit action;
  live connection / VRAM status bar in the extension panel.
- **Setup Wizard** - guided local and remote install: Python environment setup,
  model weight download, server URL registration, and connection test.
- **AI Perception View** - live FPV feed overlaid with the model's per-patch
  attention heatmap, a 3-D per-layer attention stack, a behavior-change badge,
  and word-by-word streaming model reasoning.
- **Reports** - per-sign HTML report with action switches, logit margins,
  attention-relocation metrics (ARAM / TRAM / ADS), per-station severity, and an
  overall ROBUST / PARTIAL / VULNERABLE verdict; a run index page; per-frame
  JSON data export for downstream analysis.
- **Onboarding & help** - first-launch intro cards and a Contact Us window.

### Compatibility
- NVIDIA Isaac Sim 5.0 / 5.1 / 6.0 (API differences, such as physics-callback
  signatures and articulation teleport batching, are handled at runtime).
- Ubuntu 22.04 / 24.04; NVIDIA RTX GPU recommended.
