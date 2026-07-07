"""Shared frameless-window controller for app windows, dialogs, and tools."""

from __future__ import annotations

import ctypes
import sys
import weakref
from collections.abc import Callable
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QEvent, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QWidget

from app.debug_logger import debug_logger


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", wintypes.POINT),
        ("ptMaxSize", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("ptMinTrackSize", wintypes.POINT),
        ("ptMaxTrackSize", wintypes.POINT),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [
        ("rgrc", wintypes.RECT * 3),
        ("lppos", ctypes.c_void_p),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class _ChromeNativeEventFilter(QAbstractNativeEventFilter):
    """Application-wide Windows frame hook routed to one chrome controller."""

    def __init__(self, controller: "FramelessWindowChromeController") -> None:
        super().__init__()
        self._controller_ref = weakref.ref(controller)

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        controller = self._controller_ref()
        if controller is None:
            return False, 0
        hit_test = controller.handle_native_event(event_type, message)
        if hit_test is None:
            return False, 0
        return True, hit_test


class FramelessWindowChromeController:
    """Complete frameless chrome behavior shared by all Qt top-level windows."""

    FRAMELESS_RESIZE_BORDER_PX = 8
    AUTO_HIDE_TASKBAR_RESERVE_PX = 2
    WVR_REDRAW = 0x0300
    SM_CXSIZEFRAME = 32
    SM_CYSIZEFRAME = 33
    SM_CXPADDEDBORDER = 92
    GWL_STYLE = -16
    MONITOR_DEFAULTTONEAREST = 2
    ABM_GETSTATE = 0x00000004
    ABM_GETTASKBARPOS = 0x00000005
    ABM_GETAUTOHIDEBAREX = 0x0000000B
    ABS_AUTOHIDE = 0x00000001
    ABE_LEFT = 0
    ABE_TOP = 1
    ABE_RIGHT = 2
    ABE_BOTTOM = 3
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SW_MAXIMIZE = 3
    SW_RESTORE = 9
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_MAXIMIZEBOX = 0x00010000
    WS_MINIMIZEBOX = 0x00020000
    WS_SYSMENU = 0x00080000
    WS_THICKFRAME = 0x00040000
    WM_MOVE = 0x0003
    WM_SIZE = 0x0005
    WM_GETMINMAXINFO = 0x0024
    WM_WINDOWPOSCHANGED = 0x0047
    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    WM_NCLBUTTONDOWN = 0x00A1
    WM_NCLBUTTONUP = 0x00A2
    WM_NCLBUTTONDBLCLK = 0x00A3
    HTCLIENT = 1
    HTCAPTION = 2
    HTMINBUTTON = 8
    HTMAXBUTTON = 9
    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17
    HTCLOSE = 20

    def __init__(
        self,
        host: QWidget,
        *,
        title_bar_getter: Callable[[], QWidget | None],
        is_effectively_maximized: Callable[[], bool] | None = None,
        toggle_maximized: Callable[[], None] | None = None,
        resizable: bool = True,
        minimizable: bool = True,
        maximizable: bool = True,
    ) -> None:
        self.host = host
        self._title_bar_getter = title_bar_getter
        self._is_effectively_maximized_callback = is_effectively_maximized
        self._toggle_maximized_callback = toggle_maximized
        self.resizable = bool(resizable)
        self.minimizable = bool(minimizable)
        self.maximizable = bool(maximizable)
        self._windows_hwnd: int | None = None
        self._windows_frameless_style_applied = False
        self._windows_native_frame_filter: _ChromeNativeEventFilter | None = None
        self._windows_native_frame_filter_installed = False
        self._frameless_resize_event_filter_installed = False
        self._frameless_resize_override_cursor_active = False

    def install(self) -> None:
        if self._uses_windows_native_resize():
            self.install_windows_native_frame_filter()
        else:
            self.install_frameless_resize_event_filter()

    def uninstall(self) -> None:
        self.remove_windows_native_frame_filter()
        self.remove_frameless_resize_event_filter()

    def on_show_event(self) -> None:
        self.apply_windows_frameless_window_style()
        self.sync_title_bar_state()

    def set_window_flags(self) -> None:
        flags = self.host.windowFlags() | Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        self.host.setWindowFlags(flags)

    def sync_title_bar_state(self) -> None:
        title_bar = self._title_bar()
        set_maximized = getattr(title_bar, "set_maximized", None)
        if callable(set_maximized):
            set_maximized(self._is_effectively_maximized())

    def handle_native_event(self, _event_type, message) -> int | None:
        if not sys.platform.startswith("win"):
            return None
        try:
            msg = _MSG.from_address(int(message))
        except (AttributeError, TypeError, ValueError):
            return None
        if not self._native_msg_belongs_to_this_window(msg):
            return None
        message_id = int(msg.message)
        if message_id == self.WM_NCCALCSIZE and bool(msg.wParam):
            return self._handle_nc_calc_size(msg)
        if message_id == self.WM_GETMINMAXINFO:
            self._handle_get_min_max_info(msg)
            return 0
        if message_id in {self.WM_MOVE, self.WM_SIZE, self.WM_WINDOWPOSCHANGED}:
            self.sync_title_bar_state()
            QTimer.singleShot(0, self.sync_title_bar_state)
            return None
        if message_id == self.WM_NCHITTEST:
            return self._win32_hit_test(msg)
        if message_id == self.WM_NCLBUTTONDOWN and int(msg.wParam) == self.HTMAXBUTTON:
            return 0
        if message_id == self.WM_NCLBUTTONUP and int(msg.wParam) == self.HTMAXBUTTON:
            self._toggle_maximized()
            return 0
        if message_id == self.WM_NCLBUTTONDBLCLK and int(msg.wParam) == self.HTCAPTION:
            self._toggle_maximized()
            return 0
        return None

    def apply_windows_frameless_window_style(self) -> None:
        if self._windows_frameless_style_applied or not sys.platform.startswith("win"):
            return
        try:
            hwnd = int(self.host.winId())
            self._windows_hwnd = hwnd
            user32 = ctypes.windll.user32
            long_ptr = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_window_long.restype = long_ptr
            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
            set_window_long.restype = long_ptr
            hwnd_handle = wintypes.HWND(hwnd)
            style = int(get_window_long(hwnd_handle, self.GWL_STYLE))
            desired_style = (style & ~self.WS_POPUP) | self.WS_CAPTION | self.WS_SYSMENU
            if self.resizable:
                desired_style |= self.WS_THICKFRAME
            if self.minimizable:
                desired_style |= self.WS_MINIMIZEBOX
            if self.maximizable:
                desired_style |= self.WS_MAXIMIZEBOX
            if desired_style != style:
                set_window_long(hwnd_handle, self.GWL_STYLE, long_ptr(desired_style))
            user32.SetWindowPos(
                hwnd_handle,
                0,
                0,
                0,
                0,
                0,
                self.SWP_NOMOVE
                | self.SWP_NOSIZE
                | self.SWP_NOZORDER
                | self.SWP_NOACTIVATE
                | self.SWP_FRAMECHANGED,
            )
            self._windows_frameless_style_applied = True
        except Exception as exc:
            debug_logger.log_exception("WindowChrome", "apply_windows_frameless_window_style", exc)

    def install_frameless_resize_event_filter(self) -> None:
        if self._uses_windows_native_resize() or self._frameless_resize_event_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self.host)
        self._frameless_resize_event_filter_installed = True

    def install_windows_native_frame_filter(self) -> None:
        if not sys.platform.startswith("win") or self._windows_native_frame_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        try:
            self._windows_hwnd = int(self.host.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        native_filter = _ChromeNativeEventFilter(self)
        app.installNativeEventFilter(native_filter)
        self._windows_native_frame_filter = native_filter
        self._windows_native_frame_filter_installed = True

    def remove_windows_native_frame_filter(self) -> None:
        if not self._windows_native_frame_filter_installed:
            return
        app = QApplication.instance()
        if app is not None and self._windows_native_frame_filter is not None:
            app.removeNativeEventFilter(self._windows_native_frame_filter)
        self._windows_native_frame_filter = None
        self._windows_native_frame_filter_installed = False

    def remove_frameless_resize_event_filter(self) -> None:
        if not self._frameless_resize_event_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self.host)
        self._frameless_resize_event_filter_installed = False
        self._set_frameless_resize_cursor(None)

    def mouse_press_event(self, event) -> bool:
        if event.button() == Qt.MouseButton.LeftButton and self._start_frameless_system_resize(self._mouse_event_global_pos(event)):
            event.accept()
            return True
        return False

    def event_filter(self, watched, event) -> bool:
        event_type = event.type()
        if self._event_belongs_to_this_window(watched):
            if event_type in {QEvent.Type.MouseMove, QEvent.Type.HoverMove, QEvent.Type.Enter}:
                self._update_frameless_resize_cursor(self._mouse_event_global_pos(event))
            elif event_type in {QEvent.Type.Leave, QEvent.Type.WindowDeactivate}:
                self._set_frameless_resize_cursor(None)
            elif (
                event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self._start_frameless_system_resize(self._mouse_event_global_pos(event))
            ):
                event.accept()
                return True
        return False

    def frameless_hit_test(self, global_pos: QPoint) -> int | None:
        if self.host.isFullScreen():
            return None
        frame = self.host.frameGeometry()
        border_x, border_y = self.frameless_resize_margins()
        hit_frame = frame.adjusted(-border_x, -border_y, border_x, border_y)
        if not hit_frame.contains(global_pos):
            return None

        title_bar = self._title_bar()
        title_local_pos = None
        title_contains_pos = False
        if title_bar is not None and title_bar.isVisible():
            title_local_pos = title_bar.mapFromGlobal(global_pos)
            title_contains_pos = title_bar.rect().contains(title_local_pos)
            if title_contains_pos and hasattr(title_bar, "chrome_button_kind_at"):
                button_kind = title_bar.chrome_button_kind_at(title_local_pos)
                if button_kind == "minimize":
                    return self.HTMINBUTTON
                if button_kind == "maximize":
                    return self.HTMAXBUTTON
                if button_kind == "close":
                    return self.HTCLOSE

        if self.resizable and not self._is_effectively_maximized():
            x = global_pos.x()
            y = global_pos.y()
            left = self._point_in_leading_edge(x, frame.left(), border_x)
            right = self._point_in_trailing_edge(x, frame.right(), border_x)
            top = self._point_in_leading_edge(y, frame.top(), border_y)
            bottom = self._point_in_trailing_edge(y, frame.bottom(), border_y)
            if top and left:
                return self.HTTOPLEFT
            if top and right:
                return self.HTTOPRIGHT
            if bottom and left:
                return self.HTBOTTOMLEFT
            if bottom and right:
                return self.HTBOTTOMRIGHT
            if left:
                return self.HTLEFT
            if right:
                return self.HTRIGHT
            if top:
                return self.HTTOP
            if bottom:
                return self.HTBOTTOM

        if title_contains_pos and title_local_pos is not None and not title_bar.is_interactive_at(title_local_pos):
            return self.HTCAPTION
        return None

    def frameless_resize_edges_for_global_pos(self, global_pos: QPoint):
        if not self.resizable or self.host.isFullScreen() or self._is_effectively_maximized():
            return None
        frame = self.host.frameGeometry()
        border_x, border_y = self.frameless_resize_margins()
        hit_frame = frame.adjusted(-border_x, -border_y, border_x, border_y)
        if not hit_frame.contains(global_pos):
            return None
        x = global_pos.x()
        y = global_pos.y()
        left = self._point_in_leading_edge(x, frame.left(), border_x)
        right = self._point_in_trailing_edge(x, frame.right(), border_x)
        top = self._point_in_leading_edge(y, frame.top(), border_y)
        bottom = self._point_in_trailing_edge(y, frame.bottom(), border_y)
        edge = None
        for enabled, qt_edge in (
            (left, Qt.Edge.LeftEdge),
            (right, Qt.Edge.RightEdge),
            (top, Qt.Edge.TopEdge),
            (bottom, Qt.Edge.BottomEdge),
        ):
            if enabled:
                edge = qt_edge if edge is None else edge | qt_edge
        return edge

    @classmethod
    def cursor_for_resize_edges(cls, edges) -> Qt.CursorShape | None:
        if edges is None:
            return None
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (top and left) or (bottom and right):
            return Qt.CursorShape.SizeFDiagCursor
        if (top and right) or (bottom and left):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return None

    def frameless_resize_margins(self) -> tuple[int, int]:
        fallback = int(self.FRAMELESS_RESIZE_BORDER_PX)
        if not sys.platform.startswith("win"):
            return fallback, fallback
        try:
            hwnd = int(self.host.winId())
            horizontal = max(fallback, int(self._resize_border_thickness_for_hwnd(hwnd, horizontal=True)))
            vertical = max(fallback, int(self._resize_border_thickness_for_hwnd(hwnd, horizontal=False)))
            return horizontal, vertical
        except Exception:
            return fallback, fallback

    def _title_bar(self):
        try:
            return self._title_bar_getter()
        except RuntimeError:
            return None

    def _is_effectively_maximized(self) -> bool:
        if self._is_effectively_maximized_callback is not None:
            return bool(self._is_effectively_maximized_callback())
        if sys.platform.startswith("win"):
            try:
                hwnd = int(self._windows_hwnd if self._windows_hwnd is not None else self.host.winId())
                return bool(self._is_hwnd_maximized(hwnd))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        try:
            return bool(self.host.windowState() & Qt.WindowState.WindowMaximized) or self.host.isMaximized()
        except RuntimeError:
            return False

    def _toggle_maximized(self) -> None:
        if not self.maximizable:
            return
        if self._toggle_maximized_callback is not None:
            self._toggle_maximized_callback()
            return
        should_maximize = not self._is_effectively_maximized()
        if sys.platform.startswith("win"):
            try:
                hwnd = int(self._windows_hwnd if self._windows_hwnd is not None else self.host.winId())
                if self.set_hwnd_maximized(hwnd, should_maximize):
                    self.sync_title_bar_state()
                    QTimer.singleShot(80, self.sync_title_bar_state)
                    return
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        if should_maximize:
            self.host.showMaximized()
        else:
            self.host.showNormal()
        self.sync_title_bar_state()

    def _uses_windows_native_resize(self) -> bool:
        return self.resizable and sys.platform.startswith("win")

    def _native_msg_belongs_to_this_window(self, msg) -> bool:
        try:
            hwnd = int(msg.hWnd)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        return self._windows_hwnd is not None and hwnd == int(self._windows_hwnd)

    def _handle_nc_calc_size(self, _msg) -> int:
        return 0

    def _dwm_def_window_proc(self, msg) -> int | None:
        try:
            result_type = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
            result = result_type()
            handled = ctypes.windll.dwmapi.DwmDefWindowProc(
                msg.hWnd,
                msg.message,
                msg.wParam,
                msg.lParam,
                ctypes.byref(result),
            )
        except Exception:
            return None
        return int(result.value) if handled else None

    def _monitor_info_for_hwnd(self, hwnd) -> _MONITORINFO | None:
        monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, self.MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None
        monitor_info = _MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return None
        return monitor_info

    def _is_hwnd_maximized(self, hwnd) -> bool:
        try:
            return bool(ctypes.windll.user32.IsZoomed(hwnd))
        except Exception:
            return False

    def set_hwnd_maximized(self, hwnd, maximized: bool) -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            ctypes.windll.user32.ShowWindow(
                wintypes.HWND(int(hwnd)),
                self.SW_MAXIMIZE if maximized else self.SW_RESTORE,
            )
            return True
        except Exception as exc:
            debug_logger.log_exception("WindowChrome", "set_hwnd_maximized", exc)
            return False

    def _handle_get_min_max_info(self, msg) -> None:
        try:
            monitor = ctypes.windll.user32.MonitorFromWindow(
                msg.hWnd,
                self.MONITOR_DEFAULTTONEAREST,
            )
            if not monitor:
                return
            monitor_info = _MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                return
            min_max_info = ctypes.cast(msg.lParam, ctypes.POINTER(_MINMAXINFO)).contents
            monitor_rect = monitor_info.rcMonitor
            work_rect = monitor_info.rcWork
            taskbar_edge = self._auto_hide_taskbar_edge_for_monitor(monitor_rect)
            work_left, work_top, work_right, work_bottom = self.adjust_work_area_for_auto_hide_taskbar(
                monitor_rect,
                work_rect,
                taskbar_edge,
            )
            min_max_info.ptMaxPosition.x = work_left - monitor_rect.left
            min_max_info.ptMaxPosition.y = work_top - monitor_rect.top
            max_track_width = max(1, work_right - work_left)
            max_track_height = max(1, work_bottom - work_top)
            min_max_info.ptMaxSize.x = max_track_width
            min_max_info.ptMaxSize.y = max_track_height
            min_max_info.ptMaxTrackSize.x = max_track_width
            min_max_info.ptMaxTrackSize.y = max_track_height
            min_size = self.host.minimumSize()
            min_width = self._logical_px_to_native_track_px(min_size.width())
            min_height = self._logical_px_to_native_track_px(min_size.height())
            if min_width > 0:
                min_max_info.ptMinTrackSize.x = min(
                    max_track_width,
                    max(min_max_info.ptMinTrackSize.x, min_width),
                )
            if min_height > 0:
                min_max_info.ptMinTrackSize.y = min(
                    max_track_height,
                    max(min_max_info.ptMinTrackSize.y, min_height),
                )
        except Exception as exc:
            debug_logger.log_exception("WindowChrome", "handle_get_min_max_info", exc)

    def _logical_px_to_native_track_px(self, value: int) -> int:
        if value <= 0:
            return 0
        return max(1, round(value * self._qt_dpr()))

    def _win32_hit_test(self, msg) -> int:
        pos = self._native_client_pos_from_lparam(msg)
        x = int(pos.x())
        y = int(pos.y())
        width, height = self._native_client_size_for_hwnd(msg.hWnd)

        title_bar = self._title_bar()
        if title_bar is not None and title_bar.isVisible():
            if self._point_in_rect_px(self._widget_rect_client_px(getattr(title_bar, "btn_maximize", None)), x, y):
                return self.HTMAXBUTTON
            for button in (
                getattr(title_bar, "btn_minimize", None),
                getattr(title_bar, "btn_close", None),
            ):
                if self._point_in_rect_px(self._widget_rect_client_px(button), x, y):
                    return self.HTCLIENT

        if self.resizable and not self._is_effectively_maximized() and not self.host.isFullScreen():
            border_x, border_y = self.frameless_resize_margins()
            left = x < border_x
            right = x >= width - border_x
            top = y < border_y
            bottom = y >= height - border_y
            if top and left:
                return self.HTTOPLEFT
            if top and right:
                return self.HTTOPRIGHT
            if bottom and left:
                return self.HTBOTTOMLEFT
            if bottom and right:
                return self.HTBOTTOMRIGHT
            if left:
                return self.HTLEFT
            if right:
                return self.HTRIGHT
            if top:
                return self.HTTOP
            if bottom:
                return self.HTBOTTOM

        if isinstance(title_bar, QWidget) and self._point_in_rect_px(self._widget_rect_client_px(title_bar), x, y):
            return self.HTCAPTION
        return self.HTCLIENT

    def _native_client_pos_from_lparam(self, msg) -> QPoint:
        point = wintypes.POINT(
            self._signed_word(int(msg.lParam)),
            self._signed_word(int(msg.lParam) >> 16),
        )
        try:
            ctypes.windll.user32.ScreenToClient(msg.hWnd, ctypes.byref(point))
        except Exception:
            return QPoint(int(point.x), int(point.y))
        return QPoint(int(point.x), int(point.y))

    def _native_client_size_for_hwnd(self, hwnd) -> tuple[int, int]:
        rect = wintypes.RECT()
        try:
            if ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return max(1, int(rect.right - rect.left)), max(1, int(rect.bottom - rect.top))
        except Exception:
            pass
        dpr = self._qt_dpr()
        return max(1, round(self.host.width() * dpr)), max(1, round(self.host.height() * dpr))

    def _qt_dpr(self) -> float:
        try:
            handle = self.host.windowHandle()
            if handle is not None:
                dpr = float(handle.devicePixelRatio())
                if dpr > 0:
                    return dpr
        except Exception:
            pass
        try:
            dpr = float(self.host.devicePixelRatioF())
            return dpr if dpr > 0 else 1.0
        except Exception:
            return 1.0

    def _widget_rect_client_px(self, widget: QWidget | None) -> tuple[int, int, int, int] | None:
        if widget is None or not widget.isVisible():
            return None
        dpr = self._qt_dpr()
        pos = widget.mapTo(self.host, QPoint(0, 0))
        return (
            round(pos.x() * dpr),
            round(pos.y() * dpr),
            round((pos.x() + widget.width()) * dpr),
            round((pos.y() + widget.height()) * dpr),
        )

    @staticmethod
    def _point_in_rect_px(rect: tuple[int, int, int, int] | None, x: int, y: int) -> bool:
        if rect is None:
            return False
        left, top, right, bottom = rect
        return left <= x < right and top <= y < bottom

    def _resize_border_thickness_for_hwnd(self, hwnd, *, horizontal: bool) -> int:
        frame_metric = self.SM_CXSIZEFRAME if horizontal else self.SM_CYSIZEFRAME
        frame = self._system_metric_for_hwnd(frame_metric, hwnd)
        padded = self._system_metric_for_hwnd(self.SM_CXPADDEDBORDER, hwnd)
        return max(0, frame + padded)

    def _system_metric_for_hwnd(self, metric: int, hwnd) -> int:
        try:
            get_metric_for_dpi = getattr(ctypes.windll.user32, "GetSystemMetricsForDpi")
            return int(get_metric_for_dpi(metric, self._window_dpi(hwnd)))
        except Exception:
            return int(ctypes.windll.user32.GetSystemMetrics(metric))

    def _window_dpi(self, hwnd) -> int:
        try:
            get_dpi_for_window = getattr(ctypes.windll.user32, "GetDpiForWindow")
            dpi = int(get_dpi_for_window(hwnd))
            return dpi if dpi > 0 else 96
        except Exception:
            return 96

    def _auto_hide_taskbar_edge_for_monitor(self, monitor_rect) -> int | None:
        if not sys.platform.startswith("win"):
            return None
        try:
            shell32 = ctypes.windll.shell32
            for edge in (self.ABE_BOTTOM, self.ABE_TOP, self.ABE_LEFT, self.ABE_RIGHT):
                data = _APPBARDATA()
                data.cbSize = ctypes.sizeof(_APPBARDATA)
                data.uEdge = edge
                self._copy_rect_to_appbar_data(data, monitor_rect)
                if shell32.SHAppBarMessage(self.ABM_GETAUTOHIDEBAREX, ctypes.byref(data)):
                    return edge

            data = _APPBARDATA()
            data.cbSize = ctypes.sizeof(_APPBARDATA)
            state = int(shell32.SHAppBarMessage(self.ABM_GETSTATE, ctypes.byref(data)))
            if not state & self.ABS_AUTOHIDE:
                return None

            data = _APPBARDATA()
            data.cbSize = ctypes.sizeof(_APPBARDATA)
            if not shell32.SHAppBarMessage(self.ABM_GETTASKBARPOS, ctypes.byref(data)):
                return None
            if not self._rects_intersect(data.rc, monitor_rect):
                return None
            return int(data.uEdge)
        except Exception as exc:
            debug_logger.log_exception("WindowChrome", "detect_auto_hide_taskbar", exc)
            return None

    def _copy_rect_to_appbar_data(self, data: _APPBARDATA, rect) -> None:
        left, top, right, bottom = self._rect_edges(rect)
        data.rc.left = left
        data.rc.top = top
        data.rc.right = right
        data.rc.bottom = bottom

    def _apply_auto_hide_taskbar_reserve_to_rect(self, rect, edge: int | None) -> None:
        reserve = self.AUTO_HIDE_TASKBAR_RESERVE_PX
        if edge == self.ABE_LEFT:
            rect.left += reserve
        elif edge == self.ABE_TOP:
            rect.top += reserve
        elif edge == self.ABE_RIGHT:
            rect.right -= reserve
        elif edge == self.ABE_BOTTOM:
            rect.bottom -= reserve

    @classmethod
    def adjust_work_area_for_auto_hide_taskbar(cls, monitor_rect, work_rect, edge: int | None) -> tuple[int, int, int, int]:
        left, top, right, bottom = cls._rect_edges(work_rect)
        monitor_left, monitor_top, monitor_right, monitor_bottom = cls._rect_edges(monitor_rect)
        reserve = cls.AUTO_HIDE_TASKBAR_RESERVE_PX
        if edge == cls.ABE_LEFT and left <= monitor_left:
            left += reserve
        elif edge == cls.ABE_TOP and top <= monitor_top:
            top += reserve
        elif edge == cls.ABE_RIGHT and right >= monitor_right:
            right -= reserve
        elif edge == cls.ABE_BOTTOM and bottom >= monitor_bottom:
            bottom -= reserve
        return left, top, max(left + 1, right), max(top + 1, bottom)

    @staticmethod
    def _rect_edges(rect) -> tuple[int, int, int, int]:
        return (
            int(getattr(rect, "left", 0)),
            int(getattr(rect, "top", 0)),
            int(getattr(rect, "right", 0)),
            int(getattr(rect, "bottom", 0)),
        )

    @classmethod
    def _rects_intersect(cls, first, second) -> bool:
        left1, top1, right1, bottom1 = cls._rect_edges(first)
        left2, top2, right2, bottom2 = cls._rect_edges(second)
        return left1 < right2 and right1 > left2 and top1 < bottom2 and bottom1 > top2

    @staticmethod
    def _point_in_leading_edge(value: int, start: int, thickness: int) -> bool:
        thickness = max(1, thickness)
        return start - thickness <= value < start + thickness

    @staticmethod
    def _point_in_trailing_edge(value: int, end: int, thickness: int) -> bool:
        thickness = max(1, thickness)
        return end - thickness < value <= end + thickness

    @classmethod
    def global_pos_from_lparam(cls, lparam: int) -> QPoint:
        return QPoint(cls._signed_word(lparam), cls._signed_word(lparam >> 16))

    @staticmethod
    def _signed_word(value: int) -> int:
        value &= 0xFFFF
        return value - 0x10000 if value & 0x8000 else value

    def _set_frameless_resize_cursor(self, cursor: Qt.CursorShape | None) -> None:
        app = QApplication.instance()
        if app is None:
            return
        active = self._frameless_resize_override_cursor_active
        if cursor is None:
            if active:
                app.restoreOverrideCursor()
                self._frameless_resize_override_cursor_active = False
            return
        qt_cursor = QCursor(cursor)
        if active:
            app.changeOverrideCursor(qt_cursor)
        else:
            app.setOverrideCursor(qt_cursor)
            self._frameless_resize_override_cursor_active = True

    def _update_frameless_resize_cursor(self, global_pos: QPoint) -> None:
        cursor = self.cursor_for_resize_edges(self.frameless_resize_edges_for_global_pos(global_pos))
        self._set_frameless_resize_cursor(cursor)

    def _start_frameless_system_resize(self, global_pos: QPoint) -> bool:
        edge = self.frameless_resize_edges_for_global_pos(global_pos)
        if edge is None:
            return False
        window_handle = self.host.windowHandle()
        start_resize = getattr(window_handle, "startSystemResize", None)
        if not callable(start_resize):
            return False
        try:
            started = bool(start_resize(edge))
            if started:
                self._set_frameless_resize_cursor(None)
            return started
        except Exception as exc:
            debug_logger.log_exception("WindowChrome", "start_system_resize", exc)
            return False

    def _event_belongs_to_this_window(self, watched: object) -> bool:
        widget = watched if isinstance(watched, QWidget) else None
        return widget is not None and widget.window() is self.host

    @staticmethod
    def _mouse_event_global_pos(event) -> QPoint:
        global_position = getattr(event, "globalPosition", None)
        if callable(global_position):
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if callable(global_pos):
            return global_pos()
        return QCursor.pos()
