"""IExt lifecycle entry point for labr7.radeis.redteam (Radeis Red-Team v0.2).

Registers Window menu items and manages the GUI panel lifetime.
Opens the main red-team panel on startup.
"""
import asyncio

try:
    import omni.ext
    _EXT_BASE = omni.ext.IExt
except ModuleNotFoundError:
    _EXT_BASE = object

_MENU_MAIN = "Radeis | In-Sim Physical AI Safety Validator"


class LabR7IssacExtension(_EXT_BASE):

    def on_startup(self, ext_id: str):
        import omni.kit.app
        import omni.kit.menu.utils as menu_utils
        try:
            self._menu_utils = menu_utils
            self._install_optional_packages()
            manager = omni.kit.app.get_app().get_extension_manager()
            self._ext_path = manager.get_extension_path(ext_id)
            self._window = None
            self._onboarding = None
            self._show_task = None

            self._menu = [
                menu_utils.MenuItemDescription(
                    name=_MENU_MAIN,
                    onclick_fn=lambda *_: self._show_main(),
                ),
            ]
            menu_utils.add_menu_items(self._menu, name="Window")

            # Defer window creation until the docking system is ready.
            async def _show_deferred():
                try:
                    app = omni.kit.app.get_app()
                    for _ in range(5):
                        await app.next_update_async()
                    self._show_main()
                except Exception as e:  # noqa: BLE001
                    print(f"[Radeis] ERROR in _show_deferred: {e}")
                    import traceback
                    traceback.print_exc()
            self._show_task = asyncio.ensure_future(_show_deferred())
        except Exception as e:  # noqa: BLE001
            print(f"[Radeis] ERROR in on_startup: {e}")
            import traceback
            traceback.print_exc()

    def _install_optional_packages(self):
        try:
            import omni.kit.pipapi as pipapi
        except ImportError:
            return
        import carb
        for pkg, module in [("psutil", "psutil"), ("pynvml", "pynvml")]:
            try:
                pipapi.install(pkg, module=module, use_online_index=True)
            except Exception as e:  # noqa: BLE001
                carb.log_warn(f"[radeis] optional package '{pkg}' unavailable: {e}. "
                              "Resource pre-checks will be skipped.")

    def on_shutdown(self):
        if self._show_task is not None and not self._show_task.done():
            self._show_task.cancel()
            self._show_task = None
        menu_utils = getattr(self, "_menu_utils", None)
        if menu_utils is not None:
            menu_utils.remove_menu_items(self._menu, name="Window")
        try:
            from .ui import wizard as _wiz
            inst = _wiz._INSTANCE
            if inst is not None:
                inst._on_complete = None
                inst._on_forget   = None
                inst._close_wizard()  # destroys inst._win and clears _wiz._INSTANCE
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, "_window", None):
            self._window.destroy()
            self._window = None

    def _show_main(self):
        try:
            if self._window is None:
                self._sweep_stale_windows()
                from .ui.window import RadeisRedTeamWindow
                self._window = RadeisRedTeamWindow(ext_path=self._ext_path)
            elif getattr(self._window, "_window", None):
                self._window._window.focus()
        except Exception as e:  # noqa: BLE001
            print(f"[Radeis] ERROR in _show_main: {e}")
            import traceback
            traceback.print_exc()

    def _sweep_stale_windows(self):
        # A mid-init crash in RadeisRedTeamWindow.__init__ used to leave a
        # same-title ui.Window visible with no Python reference (self._window
        # here was never assigned), so it survived on_shutdown and any later
        # reload. A WindowHandle can't destroy the underlying window, only
        # hide it, but that's enough to stop the stale/new pair from both
        # rendering and fighting over the same title-keyed geometry.
        try:
            import omni.ui as ui
            for handle in ui.Workspace.get_windows():
                if handle.title == _MENU_MAIN:
                    handle.visible = False
        except Exception:  # noqa: BLE001
            pass

