# Radeis Telemetry — Full Disclosure

This is the full disclosure for Radeis's usage telemetry, referenced from the
[extension README's "Telemetry & Privacy" section](https://github.com/VicOne-OSS-TW/labr7-radeis-InSimPhysicalAI/blob/main/exts/vicone.labr7.radeis/docs/README.md#telemetry--privacy).
(An absolute link, on purpose: this file lives at the extension root in the
repo but ships as `docs/TELEMETRY.md` inside the release ZIP — see
`build_package.sh` — so a relative link back to `docs/README.md` would
resolve correctly in only one of those two locations.)
Posture: **disclosed here, on by default, off via three switches** — not a
first-run "OK" dialog, and not click-consent.

## 1. Summary

Radeis sends three kinds of telemetry: a small, non-sensitive `install`
ping the first time you launch each version of the extension; a small
run-test funnel (`run_test_started` / `run_test_completed` /
`run_test_stuck`) while you use it; and — only if you choose to fill it
in — the opt-in **Get in Touch** form (section 4), which is the one place
anything you typed is ever sent. Together they let LabR7 see roughly how many people use
Radeis, on which version, and whether a test run makes it to a report. There
is no first-run consent dialog: the fact that telemetry exists, exactly what
it sends, and how to turn it off, are all disclosed right here. Telemetry is
on by default and can be turned off at any time using any of the three
switches in section 6, and turning it off stops all network calls before any
work happens.

## 2. Exactly what the `events` tab receives

### The `install` event

Fires **once per version** — first launch after install or upgrade, not once
per startup:

| Column | Value | Notes |
|---|---|---|
| `event` | `"install"` | fixed string |
| `ext_version` | e.g. `"0.2.1"` | Radeis version, same for everyone on that build |
| `isaac_version` | e.g. `"6.0"` | coarse Isaac Sim / Kit app version |
| `os_family` | `"windows"` / `"linux"` / `"darwin"` | OS family only — not OS build/version |
| `stage` | *(blank)* | unused on install; see the run-test funnel below |
| `feature` | *(blank)* | reserved, unused |
| `session_id` | random hex | see "`session_id`, explained" below |
| `timestamp` | server-assigned | added by the Apps Script backend on receipt |

This is deduped by a small local marker file at
`~/.labr7/telemetry_state.json` containing only
`{"last_reported_version": "<ver>"}` — no id of any kind, and this file is
never transmitted anywhere. If the `install` POST fails (offline, endpoint
down), the marker is not written, so the ping is naturally retried on the
next launch until one row lands.

### The run-test funnel

Fires while you use the extension, starting when you click **Run Test**:

| Event | When | Extra field |
|---|---|---|
| `run_test_started` | a test run begins | — |
| `run_test_completed` | a test run finishes and the report opens | — |
| `run_test_stuck` | a run stalls or fails before completing | `stage`: a coarse step name — `setup`, `sidecar`, `perception`, or `report` — never a file name, model name, or error message |

Each row carries the ephemeral `session_id`, a server `timestamp`, and the
same coarse `ext_version` / `isaac_version` / `os_family` columns as
`install` — `client.send_event` fills them from the live environment probes
whenever the caller does not pass them. No scene, model, file, or run
content is ever attached to any of them.

### The `feedback_opened` event

| Event | When | Extra field |
|---|---|---|
| `feedback_opened` | the **Get in Touch** form goes from hidden to visible | — |

Re-focusing a form that is already open does not re-fire it, and it carries
no form content of any kind — not a single character you typed, not which
fields you filled, and not whether you went on to press **Send**.

It is also **the one `events` row that carries a blank `session_id`**. It
is fired through `track_unlinked()`, which passes `omit_session_id=True` to
the transport, specifically so that an open-the-form row landing seconds
before a `feedback` row cannot be used to join the two tabs by
nearest-preceding timestamp. It still carries `ext_version`,
`isaac_version`, `os_family`, and a server `timestamp`.

### `session_id`, explained

Every row on the `events` tab except `feedback_opened` — install and
run-test alike — carries a `session_id`: a random value generated in memory
when Isaac Sim starts and
discarded when Isaac Sim closes. It is never written to disk and never
reused across launches.

What it is for: spotting an accidental double-fire within one Isaac Sim
process, and telling that an install and a test run came from the same
launch. What it cannot do: link two separate launches together. A fresh
value is generated per process and nothing persists it, so it is not a
head-count of installs and not a device id — it groups events within one
run, nothing more.

## 3. What is NOT collected

- No persistent device/user id or hardware fingerprint of any kind.
- No precise geolocation used as an identity.
- No OS build or OS version (only the coarse `windows`/`linux`/`darwin` family).
- No scene or run **content** — no file names, paths, hashes, model outputs,
  joint counts, or anything else about what you actually run in the tool.
- No mining of the non-sensitive data above to profile an individual user.

## 4. The feedback tier (active — the "Get in Touch" form)

The **Contact** button in the panel opens a **Get in Touch** form. It is
**opt-in only** — no form content leaves your machine unless you type
something and press **Send**; the only thing opening the form sends is the
contentless `feedback_opened` count described in section 2. Once you do
press Send, it sends whatever you type (name, email, org, role, a use
case you pick yourself from a fixed list, free-text feedback, and an "OK to
email me" checkbox that defaults unchecked) to a separate `feedback` tab in
a Google Sheet owned by LabR7. Every field is optional, and the form submits
with the checkbox left unticked — the checkbox is the only consent token for
outreach and is never pre-ticked. The use case is only ever what you select —
it is never inferred from your email domain, your scene, or anything you run.

The `feedback` tab is never joined to the `events` tab. A feedback
submission carries no `session_id` and no events-tab field, no form content
is ever attached to an events-tab row, and the only feedback-related thing
the `events` tab ever sees — the `feedback_opened` count — is deliberately
fired with a blank `session_id` so it cannot be correlated with a
submission by timestamp either.

**Withdrawing consent, and deletion.** Consent to be contacted is
per-submission and revocable: unticking the box on a later submission does
not retract an earlier one, so to withdraw contact consent or to have a
submission deleted from the sheet, reach us at
<https://vicone.com/contact-us/>. The kill switch below stops future sends;
it does not delete what was already submitted.

The global kill switch covers this form too: with `RADEIS_TELEMETRY=0` (or
`telemetry_enabled = false`) **Send** makes no network call at all, and the
form says so instead of claiming it sent.

## 5. Data handler & honesty caveats

LabR7 owns the Google Sheet and the Apps Script Web App that receives these
pings. Because the POST necessarily travels over the internet to Google's
infrastructure, Google's servers see your source IP in transit as a normal
consequence of routing the request — we do not store that IP ourselves and
we do not derive a location from it. For that reason this pipeline is
deliberately **not** described as "fully anonymous"; the accurate phrase is
**"not tied to a persistent identifier."** The write token shipped in the
extension is public by design (anti-spam only, not a secret), which means
the raw counts are technically spoofable — treat any number derived from
this data as an unauthenticated upper bound, not a certified figure.

## 6. How to opt out

Any ONE of the following disables telemetry entirely:

- set `exts."vicone.labr7.radeis".telemetry_enabled = false` in
  `config/extension.toml`, or
- launch Isaac Sim with the environment variable `RADEIS_TELEMETRY=0`, or
- (a future release) use the in-panel telemetry toggle.

Opt-out is checked **before any work happens** — before the install dedupe
file is even read, and before any network call is attempted.

## 7. Where the code lives

All telemetry code lives in `vicone/labr7/radeis/telemetry/` inside this
extension. Three places import it, each wrapped in its own try/except:
`report_install(ext_id)` in `extension.py::on_startup` (the install ping);
`track(...)` — imported in `ui/window.py` as `_tel_track` — for the
run-test funnel; and `ui/get_in_touch_win.py`, which imports `is_enabled`,
`track_unlinked` and `send_feedback_blocking` through three separate
guarded aliases for the Get in Touch form. Deleting the entire
`telemetry/` folder disables telemetry completely and has no other effect
on the extension: `ui/window.py`'s import falls back to a no-op, the Get
in Touch form still opens and simply reports "Telemetry is off - nothing
was sent." when you press Send, and everything else keeps working
identically.
