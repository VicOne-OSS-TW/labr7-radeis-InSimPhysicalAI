"""Get in Touch - feedback / opt-in lead-capture popup window.

Opened by the "Contact" pill in the main panel (ui/window.py). This is NOT
ui/contact_us_win.py: that one is the read-only "coming soon" capabilities
pitch shown from seven upsell call sites and is left untouched.

COPY LIVES HERE ON PURPOSE (deviation from CLAUDE.md's
generated/text_content.json rule): this form's wording is a privacy
disclosure that must move as one unit with TELEMETRY.md, and its sibling
popup ui/contact_us_win.py keeps its copy inline for the same reason.

ASCII ONLY. Kit's bundled UI font renders U+2014, U+2026, U+00B7 and
U+25CF as '?'. The wording is verbatim from the handoff; only those
glyphs are transliterated (- , ... , - , a real ui.Circle).

LAYOUT CONTRACT: the body is a FIXED-HEIGHT ui.ScrollingFrame and the
divider + footer are its SIBLINGS, so the Send button's position is
independent of body height and of Kit's viewport headroom. See
isaac-knowledge-pool/platform-gotchas/
omni-ui-floating-window-cannot-grow-past-viewport-headroom.md. Do not
collapse this back into one flat VStack.
"""
from __future__ import annotations

import asyncio
import weakref
from typing import Optional

import omni.ui as ui
from omni.ui import color as cl

try:
    from ..telemetry import track_unlinked as _tel_track_unlinked
except Exception:  # noqa: BLE001
    def _tel_track_unlinked(*_a, **_k):  # telemetry package absent
        pass

try:
    from ..telemetry import is_enabled as _tel_is_enabled
except Exception:  # noqa: BLE001
    def _tel_is_enabled():  # package absent -> nothing can be sent
        return False

try:
    from ..telemetry import send_feedback_blocking as _tel_send_feedback
except Exception:  # noqa: BLE001
    _tel_send_feedback = None


# ---------------------------------------------------------------------------
# Design tokens (own palette - do not reuse ui/radeis_ui.py's ABGR aliases;
# retuning one there would retune the whole main panel)
# ---------------------------------------------------------------------------
PANEL_BG   = cl("#15181b")
FIELD_BG   = cl("#0d0f11")
FIELD_BRD  = cl("#2b2f33")
DIVIDER    = cl("#202326")
ACCENT     = cl("#ff2d3e")
ACCENT_OK  = cl("#1f9d6b")
T_STRONG   = cl("#f2f4f6")
T_ROW      = cl("#e6e9ec")  # declared but unused - omni.ui Label has no
                             # inline span, so the subtitle emphasis span
                             # from the handoff is dropped
T_BODY     = cl("#b9c0c7")
T_LABEL    = cl("#a2aab1")
T_MUTED    = cl("#828a91")
T_EYEBROW  = cl("#9aa1a8")
T_PLACE    = cl("#6f777e")
FIELD_TEXT = cl("#e2e6ea")
ERR        = cl("#ffa8b0")
OK_TXT     = cl("#7fd6ae")
WHITE      = cl("#ffffff")


# ---------------------------------------------------------------------------
# Copy constants (ASCII, verbatim wording from the handoff)
# ---------------------------------------------------------------------------
WIN_TITLE = "Get in Touch"
WIN_W = 540
WIN_H = 700
H_BODY = 540  # ScrollingFrame height; the ONE live-tuned dial

EYEBROW = "LABR7 - RADEIS"
HEADLINE = "Tell us where Radeis fell short."
SUBTITLE = ("We read every one of these. If you're red-teaming a policy you "
            "actually ship, add your email and tick the box - we'll follow up "
            "and help you get Radeis running on your own robot and scene.")
LBL_NAME = "Name"
LBL_EMAIL = "Email"
LBL_ORG = "Organization"
LBL_ROLE = "Role"
LBL_USE_CASE = "What are you testing?"
LBL_FEEDBACK = "Feedback"
PH_NAME = "Jane Doe"
PH_EMAIL = "jane@company.com"
PH_ORG = "Acme Robotics"
PH_ROLE = "Perception Lead"
PH_FEEDBACK = "What worked, what broke, what you wish it did..."
CHECKBOX_TEXT = "Yes - LabR7 can email me about my use case."
# Names the actual recipient in plain words and states the withdrawal
# channel, per IMPLEMENTATION_PLAN's consent rules (recipient must not be
# a euphemism; sensitive-tier consent must be revocable via a stated
# contact address). vicone.com/contact-us is the repo's existing channel
# (see ui/contact_us_win.py CONTACT_URL_DISPLAY) - do not invent an email.
DISCLOSURE = ("Goes to a LabR7-owned Google Sheet, never joined to your usage "
              "data. To withdraw consent or ask us to delete a submission: "
              "vicone.com/contact-us")
BTN_CLEAR = "Clear"
BTN_SEND = "Send"
BTN_SENT = "Sent"
# NOT in the handoff's exact-copy list - a deliberate, flagged addition,
# same status as STATUS["off"] below. The executor round-trip can take up
# to client.py's 8 s timeout; a button that visibly does nothing for 8 s
# reads as broken. Only .text is written - the style stays ACCENT.
BTN_SENDING = "Sending"

USE_CASES = [
    ("Select...", ""),
    ("Warehouse / logistics AMR", "warehouse_amr"),
    ("Humanoid", "humanoid"),
    ("Autonomous driving / ADAS", "autonomous_driving"),
    ("Industrial arm / manipulation", "industrial_arm"),
    ("Drone / UAV", "drone_uav"),
    ("Inspection & security patrol", "inspection_security"),
    ("Research / academic", "research"),
    ("Other", "other"),
]
USE_CASE_SLUGS = {s for _, s in USE_CASES}  # includes "" for Select...

STATUS = {
    "idle":      ("Optional. Goes to the LabR7 team, never joined to your usage data.", T_MUTED),
    "empty":     ("Add a note or an email first.", ERR),
    "needEmail": ("Add an email so we can reach you.", ERR),
    "sent":      ("Thanks - got it.", OK_TXT),
    "failed":    ("Couldn't send - check your connection.", ERR),
    # NOT in the handoff copy list - added because showing "Thanks - got it."
    # when the kill switch sent nothing would be a lie. See TELEMETRY.md s.4.
    "off":       ("Telemetry is off - nothing was sent.", ERR),
}


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
# No `padding` key on any StringField/ComboBox style (no precedent; cascade
# hazard - see isaac-knowledge-pool omni-ui-vstack-style-margin-cascades note).
STYLE_FIELD = {"background_color": FIELD_BG, "border_color": FIELD_BRD,
               "border_width": 1, "border_radius": 6, "color": FIELD_TEXT,
               "font_size": 15, ":focused": {"border_color": ACCENT}}
STYLE_FIELD_HINT = {**STYLE_FIELD, "color": T_PLACE}
STYLE_COMBO = dict(STYLE_FIELD)
STYLE_LABEL = {"color": T_LABEL, "font_size": 14}
# padding:0 + border_radius stop the box scaling (same guard as window.py:150-155)
STYLE_CB_UNCHECKED = {"background_color": FIELD_BG, "color": WHITE,
                       "border_width": 1, "border_color": FIELD_BRD,
                       "padding": 0, "border_radius": 3}
STYLE_CB_CHECKED = {"background_color": ACCENT, "padding": 0, "border_radius": 3}


def _send_style(bg):
    return {"background_color": bg, "color": WHITE, "border_radius": 6,
            "font_size": 15, ":hovered": {"background_color": bg}}


STYLE_CLEAR = {"background_color": PANEL_BG, "border_color": FIELD_BRD,
               "border_width": 1, "border_radius": 6, "color": T_LABEL,
               "font_size": 15, ":hovered": {"background_color": PANEL_BG}}


# ---------------------------------------------------------------------------
# Height budget (live-tuned against H_BODY = 540)
# ---------------------------------------------------------------------------
# Window 540 x 700, flags = NO_SCROLLBAR | NO_RESIZE, positioned by Kit (see
# __init__). Content width = 540 - 26 - 26 = 488.
# Outer: Spacer(22) / [Spacer(26) | content VStack | Spacer(26)] / Spacer(22) -> 44
# Content VStack has FIVE children plus one trailing greedy Spacer:
#    A ScrollingFrame(height=H_BODY=540, h-scrollbar ALWAYS_OFF)
#    B Spacer 18
#    C ui.Line 1
#    D Spacer 16
#    E footer HStack 40
#    F ui.Spacer()   <-- THE ONLY GREEDY SPACER IN THE FILE
# Total fixed = 44 + 540 + 75 = 659 < 700, so the footer is inside the window
# with margin for the titlebar, and cannot be pushed out by body growth.
#
# Inside the ScrollingFrame, one VStack(spacing=0), natural height 539:
#    1 eyebrow HStack                     17
#    2 Spacer                             12
#    3 headline Label  word_wrap size 24  34   (32 chars @24 ~ 353px of 488 -> 1 line)
#    4 Spacer                              8
#    5 subtitle Label  word_wrap size 16  60   (188 chars @16 -> 2.84 lines; 3-line budget)
#    6 Spacer                             14
#    7 row A HStack (Name|Email)          59   (label 16 + Spacer 5 + field 38)
#    8 Spacer                             12
#    9 row B HStack (Organization|Role)   59
#   10 Spacer                             12
#   11 Label LBL_USE_CASE                 16
#   12 Spacer                              5
#   13 ComboBox                           38
#   14 Spacer                             12
#   15 Label LBL_FEEDBACK                 16
#   16 Spacer                              5
#   17 feedback StringField multiline     84
#   18 Spacer                             12
#   19 checkbox HStack                    22
#   20 Spacer                             10
#   21 DISCLOSURE Label word_wrap size 12 32   (143 chars @12 -> 2 lines of 488)
#   sum = 539  (<= H_BODY 540, so no scrollbar appears nominally)
# DIALS if live measurement disagrees: raise/lower H_BODY ONLY, keeping
# 44 + H_BODY + 75 comfortably under the window's inner height. Do not change
# any item height. If multiline is dropped (see risks) item 17 goes 84 -> 38.


class GetInTouchWin:
    """Floating "Get in Touch" feedback / opt-in lead-capture popup.

    Composes a ui.Window rather than subclassing it, and is owned as an
    instance attribute by the caller (self._get_in_touch on
    RadeisRedTeamWindow) - NOT a module-level singleton. See
    ui/contact_us_win.py's module-level `_INSTANCE`, which is the documented
    leak this pattern avoids: on extension reload the module re-imports and
    a module global resets to None while the old title-keyed window is still
    alive and undestroyable.
    """

    def __init__(self) -> None:
        # ALL persistent state BEFORE ui.Window(), so a frame rebuild rebinds
        # to the same models instead of orphaning them.
        self._closed = False
        self._flash_task = None
        self._send_task = None
        self._window: Optional[ui.Window] = None
        self._fields = {}
        for key, hint in (("name", PH_NAME), ("email", PH_EMAIL), ("org", PH_ORG),
                          ("role", PH_ROLE), ("feedback", PH_FEEDBACK)):
            m = ui.SimpleStringModel()
            m.set_value(hint)
            self._fields[key] = {"model": m, "hint": hint, "is_hint": [True], "field": None}
        self._contact_ok_model = ui.SimpleBoolModel()
        self._use_case_idx = 0
        self._combo = None
        self._check = None
        self._status_label = None
        self._send_btn = None

        # REGISTER ALL MODEL HANDLERS HERE, NOT IN _build. The models are
        # instance-owned and survive a rebuild, so registering inside the
        # build fn would stack 3 subscriptions per field per rebuild, and the
        # stale closures would write to widgets from the destroyed frame.
        # Same shape as ui/window.py:571 + :586-597 - weakref to self, key
        # captured, WIDGET RESOLVED AT CALL TIME.
        _w = weakref.ref(self)
        for key in self._fields:
            def _begin(m, _w=_w, _k=key):
                win = _w()
                if win is None or win._closed:
                    return
                st = win._fields[_k]
                if not st["is_hint"][0]:
                    return
                st["is_hint"][0] = False
                f = st["field"]
                if f is not None:
                    try:
                        f.style = STYLE_FIELD
                    except Exception:  # noqa: BLE001
                        pass
                m.set_value("")

            def _end(m, _w=_w, _k=key):
                win = _w()
                if win is None or win._closed:
                    return
                if m.get_value_as_string():
                    return
                st = win._fields[_k]
                st["is_hint"][0] = True
                f = st["field"]
                if f is not None:
                    try:
                        f.style = STYLE_FIELD_HINT
                    except Exception:  # noqa: BLE001
                        pass
                m.set_value(st["hint"])

            self._fields[key]["model"].add_begin_edit_fn(_begin)
            self._fields[key]["model"].add_end_edit_fn(_end)
        # NO add_value_changed_fn on the text models: model_download.py needs
        # one only because it mirrors into self._hf_token. Here the payload is
        # read at Send time through _val(), which has its own hint guard, so
        # that handler would be a pure no-op. Do not add it back.

        def _on_toggle(m, _w=_w):
            win = _w()
            if win is None or win._closed:
                return
            cb = win._check
            if cb is None:
                return
            try:
                cb.style = (STYLE_CB_CHECKED if m.get_value_as_bool()
                            else STYLE_CB_UNCHECKED)
            except Exception:  # noqa: BLE001
                pass

        self._contact_ok_model.add_value_changed_fn(_on_toggle)

        self._window = ui.Window(
            WIN_TITLE, width=WIN_W, height=WIN_H,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR | ui.WINDOW_FLAGS_NO_RESIZE)
        try:
            # Centred in the app, which is where Contact Us lands
            # (contact_us_win.py never sets a position and Kit centres a
            # fresh window - measured: its centre is the app centre). Doing
            # it explicitly rather than by omission, because Kit remembers a
            # position per window TITLE: a slot left over from an earlier
            # build overrides the default placement and the two windows drift
            # apart. Centring both makes them concentric despite the
            # different heights. The old anchor-on-the-main-panel formula
            # came from the onboarding card, which is no longer a window.
            self._window.position_x = max(
                0.0, (ui.Workspace.get_main_window_width() - WIN_W) / 2.0)
            self._window.position_y = max(
                0.0, (ui.Workspace.get_main_window_height() - WIN_H) / 2.0)
            self._window.set_visibility_changed_fn(self._on_visibility_changed)
            self._window.frame.set_build_fn(self._build)
            self._window.visible = False  # first show() is a real transition
        except Exception:  # noqa: BLE001
            self.destroy()
            raise

    # -- Public API ----------------------------------------------------------

    def show(self) -> None:
        w = self._window
        if w is None:
            return
        was_visible = False
        try:
            was_visible = bool(w.visible)
            w.visible = True   # INSIDE the try - a failure here must not
            w.focus()          # escape and strand a live orphan window
        except Exception:  # noqa: BLE001
            pass
        if not was_visible:
            self._on_shown()

    def hide(self) -> None:
        """Hide without destroying - the draft and every field survive.

        Symmetric with show(); the caller keeps its reference. Used by the
        main panel before it opens the onboarding card, which is a takeover
        flow: leaving a side form competing with it for attention (and
        stacked above it) is not a state worth supporting.
        """
        w = self._window
        if w is None:
            return
        try:
            w.visible = False
        except Exception:  # noqa: BLE001
            pass

    def _on_shown(self) -> None:
        # exactly once per hidden->visible transition
        # NOTE: deliberately does NOT clear the fields. Kit's titlebar X only
        # hides the window, so clearing here would silently destroy an unsent
        # draft. The resend hazard is covered by the clear-on-success in
        # _send_async, which is the only place fields are ever cleared.
        try:
            self._restore_send_button()  # a 'Sent' flash cancelled by the hide
        except Exception:  # noqa: BLE001
            pass                          # would otherwise persist across reopen
        try:
            self._set_status("idle")
        except Exception:  # noqa: BLE001
            pass
        _tel_track_unlinked("feedback_opened")  # zero params, blank session_id

    def _on_visibility_changed(self, visible: bool) -> None:
        if visible:
            return
        self._cancel_flash()

    # -- Data ----------------------------------------------------------------

    def _val(self, key: str) -> str:
        st = self._fields[key]
        if st["is_hint"][0]:
            return ""  # hint text can NEVER become data
        try:
            return st["model"].get_value_as_string().strip()
        except Exception:  # noqa: BLE001
            return ""

    def payload(self) -> dict:
        idx = self._use_case_idx
        if self._combo is not None:
            try:
                idx = self._combo.model.get_item_value_model().as_int
            except Exception:  # noqa: BLE001
                pass
        slug = USE_CASES[idx][1] if 0 <= idx < len(USE_CASES) else "other"
        if slug not in USE_CASE_SLUGS:
            slug = "other"  # schema coercion before post_json
        try:
            contact_ok = bool(self._contact_ok_model.get_value_as_bool())
        except Exception:  # noqa: BLE001
            contact_ok = False
        return {"name": self._val("name"), "email": self._val("email"),
                "org": self._val("org"), "role": self._val("role"),
                "use_case": slug, "feedback": self._val("feedback"),
                "contact_ok": contact_ok}
        # exactly the 7 keys client.send_feedback reads. NO client timestamp.

    def _reset_fields(self) -> None:
        for st in self._fields.values():
            st["is_hint"][0] = True  # set BEFORE set_value
            try:
                st["model"].set_value(st["hint"])
            except Exception:  # noqa: BLE001
                pass
            f = st["field"]
            if f is not None:
                try:
                    f.style = STYLE_FIELD_HINT
                except Exception:  # noqa: BLE001
                    pass
        self._use_case_idx = 0
        if self._combo is not None:
            try:
                self._combo.model.get_item_value_model().set_value(0)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._contact_ok_model.set_value(False)  # fires _on_toggle -> restyles
        except Exception:  # noqa: BLE001
            pass

    def _on_clear_clicked(self) -> None:
        self._cancel_flash()
        self._reset_fields()
        self._restore_send_button()
        self._set_status("idle")  # Clear does NOT start a 2.2 s timer

    # -- Status / send button -----------------------------------------------

    def _set_status(self, key: str) -> None:
        if self._status_label is None:
            return
        text, color = STATUS[key]
        try:
            self._status_label.text = text
            self._status_label.style = {"color": color, "font_size": 13}
        except Exception:  # noqa: BLE001
            pass

    def _restore_send_button(self) -> None:
        if self._send_btn is None:
            return
        try:
            self._send_btn.text = BTN_SEND
            self._send_btn.style = _send_style(ACCENT)
        except Exception:  # noqa: BLE001
            pass

    def _cancel_flash(self) -> None:
        t = self._flash_task
        self._flash_task = None
        try:
            if t is not None and not t.done():
                t.cancel()
        except Exception:  # noqa: BLE001
            pass

    def _flash(self, key: str) -> None:
        self._set_status(key)
        self._cancel_flash()
        self._flash_task = asyncio.ensure_future(self._reset_after(2.2))

    async def _reset_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._closed:
            return
        try:
            self._set_status("idle")
            self._restore_send_button()
        except Exception:  # noqa: BLE001
            pass

    # -- Submit --------------------------------------------------------------

    def _on_send_clicked(self) -> None:
        # runs on the Kit UI thread; must not block
        if self._send_task is not None and not self._send_task.done():
            return  # in-flight: ignore double click
        p = self.payload()
        if not any([p["name"], p["email"], p["org"], p["role"], p["use_case"], p["feedback"]]):
            return self._flash("empty")
        if p["contact_ok"] and not p["email"]:
            return self._flash("needEmail")  # unticked form still submits
        if _tel_send_feedback is None or not _tel_is_enabled():
            return self._flash("off")  # kill switch / package deleted
        self._cancel_flash()
        if self._send_btn is not None:
            try:
                self._send_btn.text = BTN_SENDING  # text only; style unchanged
            except Exception:  # noqa: BLE001
                pass
        self._send_task = asyncio.ensure_future(self._send_async(p))

    async def _send_async(self, payload: dict) -> None:
        ok = False
        try:
            loop = asyncio.get_running_loop()
            # The ONLY thread crossing. The lambda touches no omni.ui widget
            # and returns a plain bool. client.py's 8 s timeout bounds it.
            ok = await loop.run_in_executor(None, lambda: bool(_tel_send_feedback(**payload)))
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            ok = False
        # Resumed on the Kit event loop == the UI thread: widgets are safe here.
        if self._closed:
            return
        try:
            if ok:
                self._reset_fields()  # only place fields are cleared
                if self._send_btn is not None:
                    self._send_btn.text = BTN_SENT
                    self._send_btn.style = _send_style(ACCENT_OK)
                self._flash("sent")
            else:
                self._restore_send_button()
                self._flash("failed")
        except Exception:  # noqa: BLE001
            pass

    # -- Layout helpers (construction ONLY - no add_*_fn in here) ----------

    def _hint_field(self, key: str, height: int = 38, multiline: bool = False):
        st = self._fields[key]
        f = ui.StringField(st["model"], height=height, multiline=multiline,
                            style=(STYLE_FIELD_HINT if st["is_hint"][0] else STYLE_FIELD))
        st["field"] = f  # handlers registered in __init__ read this at call time
        return f

    def _labeled_half(self, caption: str, key: str) -> None:
        # used inside a 59-tall HStack
        with ui.VStack(width=ui.Fraction(1), height=59, spacing=0):
            ui.Label(caption, height=16, style=STYLE_LABEL)
            ui.Spacer(height=5)
            self._hint_field(key, height=38)

    # -- Build ---------------------------------------------------------------

    def _build(self) -> None:
        # the frame build fn; may run more than once (rebuild). It creates
        # NO models and registers NO handlers.
        with ui.ZStack():
            ui.Rectangle(style={"background_color": PANEL_BG})
            # NO style={"margin_*"} on this VStack - Kit cascades it to every child.
            with ui.VStack(spacing=0):
                ui.Spacer(height=22)
                with ui.HStack(spacing=0):
                    ui.Spacer(width=26)
                    with ui.VStack(spacing=0):
                        # The style dict is NOT optional: an unstyled
                        # ui.ScrollingFrame paints Kit's default frame chrome,
                        # which is LIGHTER than PANEL_BG and sits a few px
                        # wider than its content - so the whole form renders
                        # inside a visible grey box that is absent from the
                        # mock. Same three keys as the proven
                        # ui/wizard/complete_test.py:299-300.
                        with ui.ScrollingFrame(
                                height=H_BODY,
                                horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                                style={"background_color": 0x00000000,
                                       "border_color": 0x00000000, "border_width": 0}):
                            with ui.VStack(spacing=0):
                                # 1 eyebrow (Circle shape from contact_us_win.py:120-128)
                                with ui.HStack(height=17, spacing=8):
                                    with ui.VStack(width=7):
                                        ui.Spacer()
                                        ui.Circle(width=7, height=7, radius=3,
                                                  alignment=ui.Alignment.CENTER,
                                                  size_policy=ui.CircleSizePolicy.FIXED,
                                                  style={"background_color": ACCENT})
                                        ui.Spacer()
                                    ui.Label(EYEBROW, alignment=ui.Alignment.LEFT_CENTER,
                                             style={"color": T_EYEBROW, "font_size": 12})
                                ui.Spacer(height=12)
                                ui.Label(HEADLINE, word_wrap=True, height=34,
                                         alignment=ui.Alignment.LEFT_TOP,
                                         style={"color": T_STRONG, "font_size": 24})
                                ui.Spacer(height=8)
                                ui.Label(SUBTITLE, word_wrap=True, height=60,
                                         alignment=ui.Alignment.LEFT_TOP,
                                         style={"color": T_BODY, "font_size": 16})
                                ui.Spacer(height=14)
                                with ui.HStack(height=59, spacing=12):
                                    self._labeled_half(LBL_NAME, "name")
                                    self._labeled_half(LBL_EMAIL, "email")
                                ui.Spacer(height=12)
                                with ui.HStack(height=59, spacing=12):
                                    self._labeled_half(LBL_ORG, "org")
                                    self._labeled_half(LBL_ROLE, "role")
                                ui.Spacer(height=12)
                                ui.Label(LBL_USE_CASE, height=16, style=STYLE_LABEL)
                                ui.Spacer(height=5)
                                self._combo = ui.ComboBox(self._use_case_idx,
                                                           *[c[0] for c in USE_CASES],
                                                           height=38, style=STYLE_COMBO)
                                # Combo state lives in self._use_case_idx because a
                                # ComboBox cannot take an injected model. This is the
                                # ONE add_*_fn left in the build fn: its target model
                                # is created per build by the ComboBox itself, so it
                                # dies with the frame and cannot stack. ONE arg.
                                _w = weakref.ref(self)

                                def _on_uc(m, _w=_w):
                                    win = _w()
                                    if win is None or win._closed:
                                        return
                                    try:
                                        win._use_case_idx = m.get_value_as_int()
                                    except Exception:  # noqa: BLE001
                                        pass

                                self._combo.model.get_item_value_model().add_value_changed_fn(_on_uc)
                                ui.Spacer(height=12)
                                ui.Label(LBL_FEEDBACK, height=16, style=STYLE_LABEL)
                                ui.Spacer(height=5)
                                self._hint_field("feedback", height=84, multiline=True)
                                ui.Spacer(height=12)
                                # checkbox row: 18 box centred in 22 (2/18/2 sandwich)
                                with ui.HStack(height=22, spacing=10):
                                    with ui.VStack(width=18, height=22, spacing=0):
                                        ui.Spacer(height=2)
                                        checked = self._contact_ok_model.get_value_as_bool()
                                        self._check = ui.CheckBox(
                                            width=18, height=18,
                                            style=(STYLE_CB_CHECKED if checked else STYLE_CB_UNCHECKED))
                                        self._check.model = self._contact_ok_model
                                        ui.Spacer(height=2)
                                    ui.Label(CHECKBOX_TEXT, width=ui.Fraction(1), height=22,
                                             word_wrap=True, alignment=ui.Alignment.LEFT_CENTER,
                                             style=STYLE_LABEL)
                                ui.Spacer(height=10)
                                ui.Label(DISCLOSURE, word_wrap=True, height=32,
                                         alignment=ui.Alignment.LEFT_TOP,
                                         style={"color": T_MUTED, "font_size": 12})
                        # --- siblings of the ScrollingFrame: always visible ---
                        ui.Spacer(height=18)
                        ui.Line(height=1, alignment=ui.Alignment.H_CENTER,
                                style={"color": DIVIDER, "border_width": 1})
                        ui.Spacer(height=16)
                        with ui.HStack(height=40, spacing=0):
                            with ui.VStack(width=270, height=40, spacing=0):
                                ui.Spacer(height=3)
                                self._status_label = ui.Label(
                                    STATUS["idle"][0], word_wrap=True, height=34,
                                    alignment=ui.Alignment.LEFT_TOP,
                                    style={"color": T_MUTED, "font_size": 13})
                                ui.Spacer(height=3)
                            ui.Spacer()  # slack absorber (1 of 2)
                            with ui.VStack(width=204, height=40, spacing=0):
                                ui.Spacer(height=3)
                                with ui.HStack(height=34, spacing=14):
                                    ui.Button(BTN_CLEAR, width=86,
                                              clicked_fn=self._on_clear_clicked,
                                              style=STYLE_CLEAR)
                                    self._send_btn = ui.Button(
                                        BTN_SEND, width=104,
                                        clicked_fn=self._on_send_clicked,
                                        style=_send_style(ACCENT))
                                ui.Spacer(height=3)
                        ui.Spacer()  # trailing greedy Spacer (2 of 2)
                    ui.Spacer(width=26)
                ui.Spacer(height=22)

    # -- Teardown ------------------------------------------------------------

    def destroy(self) -> None:
        self._closed = True
        for attr in ("_flash_task", "_send_task"):
            t = getattr(self, attr, None)
            setattr(self, attr, None)
            try:
                if t is not None and not t.done():
                    t.cancel()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._window is not None:
                self._window.set_visibility_changed_fn(None)
        except Exception:  # noqa: BLE001
            pass
        self._status_label = None
        self._send_btn = None
        self._combo = None
        self._check = None
        try:
            for st in self._fields.values():
                st["field"] = None
        except Exception:  # noqa: BLE001
            pass
        if self._window is not None:
            try:
                self._window.destroy()
            finally:
                self._window = None
        # No remove_*_fn calls: every handler is weakref+_closed guarded and its
        # target model is instance-owned, so nothing outlives this object.
