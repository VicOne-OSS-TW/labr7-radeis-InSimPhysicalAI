# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.1] - 2026-08-07

### Added
- **Usage telemetry** (on by default, opt-out) - an install ping sent once per
  version on the first launch after install or upgrade, carrying the Radeis
  version, Isaac Sim version (coarse), OS family, and an ephemeral session id;
  plus a run-test funnel recording whether a run started, completed, or got
  stuck, with a coarse stage name when stuck. No persistent device or user
  identifier is created or stored: the session id lives in memory for one Isaac
  Sim run and is discarded on exit, and the only thing written to disk is the
  last version already reported. No scene, model, or file content is ever sent.
  Turn it off with `RADEIS_TELEMETRY=0` or `telemetry_enabled = false` in
  `extension.toml`; opt-out returns before any network call. See TELEMETRY.md
  for the exact fields sent and never sent.
- New adversarial samples for additional patch approaches under
  `data/test_samples/traffic/`.

### Changed
- **Sign boards with no attack variant now show the baseline sign** instead of
  flat grey, so the patrol loop reads as complete rather than half-built.
- A sign that ships no attack variants now reports **NO DATA** instead of an
  unearned ROBUST verdict.

### Fixed
- **Attack stations are now selected by role rather than by station index.**
  Previously every station after the baseline was scored as an attack, so a
  board with no attack variant was compared against the baseline and polluted
  the switch rate, per-station severity, the average confidence drop, and the
  overall verdict. Reported numbers are unchanged for signs that fill every
  attack slot.
- Two broken sample paths in `data/test_samples/index.json` that silently left
  a station untextured.
- `traffic/stop` renamed to `traffic/stop_2`.

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
