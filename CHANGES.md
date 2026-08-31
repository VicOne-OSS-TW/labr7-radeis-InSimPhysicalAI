# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.2] - 2026-08-31

### Changed - BREAKING
- **The extension id is now `vicone.labr7.radeis`** (was `labr7.radeis.redteam`), and the
  Python package moved with it (`labr7/radeis/redteam/` -> `vicone/labr7/radeis/`). Isaac Sim
  treats this as a different extension: after upgrading, the old entry disappears from the
  Extension Manager and the new one has to be enabled once. Nothing you have configured is
  lost - the runtime state directory (`~/.labr7/`: sidecar config, tray state, logs) and the
  wizard's `sidecar_config.json` are deliberately unchanged. Settings keys move with the id,
  so `exts."labr7.radeis.redteam".*` in a local `extension.toml` override becomes
  `exts."vicone.labr7.radeis".*`.

### Added
- **Get in Touch** form (the panel's `Contact` button) - optional feedback plus opt-in lead capture. All fields optional; the "OK to email me" checkbox defaults unchecked and the form submits without it. Fields survive closing and reopening the window; they clear only after a confirmed send.
- `feedback_opened` events-tab count, fired once per form open, carrying no form content and a deliberately blank session id so it cannot be correlated with a feedback submission.
- The run report now states what ARAM currently measures, immediately under the divergence
  table: the station region is a fixed central area of the FPV frame rather than a projection
  of the sign's real position, so the number is a heuristic rather than a measurement of sign
  fixation.

### Changed
- The onboarding intro card is no longer a floating window. It renders inside the main panel
  as an overlay layer, so it can no longer end up behind the panel. (#57)
- The Setup Wizard's environment button under Advanced now always reads **Reinstall Env**. It
  is the fallback for an install that did not complete correctly, never the first-run action -
  that is **Install & Start Server** - so the label no longer toggles. Its enabled state now
  has a single owner and is correctly disabled while an install or a server spawn is running. (#58)
- **Get in Touch** and **Contact Us** now open in the same place and carry the same
  `LABR7 - RADEIS` eyebrow, instead of drifting apart with different wordmarks.
- `TELEMETRY.md` sections 1, 2, 4 and 7 and `docs/README.md` now describe the feedback tier as active rather than a later release, document `use_case`, and state the withdrawal/deletion channel.
- `TELEMETRY.md` now ships inside the release ZIP (`docs/TELEMETRY.md`) and is linked from the extension README.

### Fixed
- **Severity could only ever be 0.0 or 1.0.** The trajectory term was not gated on mode, and
  in VLM mode `traj` is a single robot base pose compared between two *different* stations -
  so it measured the distance between two sign boards, cleared its threshold every time, and
  added a constant +0.5. That pushed `0.6 + 0.5` past the clip before the attention and
  logit-margin terms were added, making both inert: every station whose action flipped scored
  exactly 1.0, and the MEDIUM band was unreachable. The term is now fenced inside VLA mode,
  where a trajectory actually means something. Severity again varies with ARAM and margin
  (measured: 1 distinct value before, 396 after). (#60)
- `TELEMETRY.md` no longer claims funnel events leave the version/OS columns blank.

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
