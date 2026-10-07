"""FrameLoad Native Standalone Window Launcher.
Runs FrameLoad as a dedicated native desktop application window without opening
an external browser (Firefox/Chrome).

Supports:
1. PyQt6 / PySide6 (QtWebEngine)
2. PyQt5 / PySide2 (QtWebEngine)
3. WebKit2GTK (Linux GTK3 native)
4. pywebview
"""
from __future__ import annotations

import argparse
import os
import sys

ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static", "assets", "icon.png")


def try_qt(url: str, fullscreen: bool = False, width: int = 1280, height: int = 800) -> bool:
    """Attempts to launch a standalone QtWebEngine window using PyQt6, PySide6, PyQt5, or PySide2."""
    qt_flavor = None

    try:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import QApplication
        qt_flavor = "PyQt6"
    except ImportError:
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QIcon
            from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWidgets import QApplication
            qt_flavor = "PySide6"
        except ImportError:
            try:
                from PyQt5.QtCore import QUrl
                from PyQt5.QtGui import QIcon
                from PyQt5.QtWebEngineWidgets import QWebEngineProfile, QWebEngineSettings, QWebEngineView
                from PyQt5.QtWidgets import QApplication
                qt_flavor = "PyQt5"
            except ImportError:
                try:
                    from PySide2.QtCore import QUrl
                    from PySide2.QtGui import QIcon
                    from PySide2.QtWebEngineWidgets import QWebEngineProfile, QWebEngineSettings, QWebEngineView
                    from PySide2.QtWidgets import QApplication
                    qt_flavor = "PySide2"
                except ImportError:
                    return False

    print(f"✨ Launching standalone FrameLoad window using native {qt_flavor} WebEngine...")

    app = QApplication.instance() or QApplication([sys.argv[0], "--appname=FrameLoad"])
    app.setApplicationName("FrameLoad")
    app.setApplicationDisplayName("FrameLoad - Steam Frame VR")

    if os.path.isfile(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    view = QWebEngineView()
    view.setWindowTitle("FrameLoad")

    # Configure optimal WebEngine settings for VR web UI
    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled if hasattr(QWebEngineSettings, 'WebAttribute') else QWebEngineSettings.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled if hasattr(QWebEngineSettings, 'WebAttribute') else QWebEngineSettings.JavascriptEnabled, True)
    if hasattr(QWebEngineSettings, 'WebAttribute') and hasattr(QWebEngineSettings.WebAttribute, 'WebGLEnabled'):
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)

    view.resize(width, height)
    view.setUrl(QUrl(url))

    if fullscreen:
        view.showFullScreen()
    else:
        view.show()

    # Center window on screen if desktop
    screen = app.primaryScreen()
    if screen and not fullscreen:
        geo = screen.availableGeometry()
        view.move((geo.width() - width) // 2, (geo.height() - height) // 2)

    sys.exit(app.exec() if hasattr(app, "exec") else app.exec_())


def try_gtk_webkit(url: str, fullscreen: bool = False, width: int = 1280, height: int = 800) -> bool:
    """Attempts to launch a standalone native GTK WebKit2 window (Linux desktop / SteamOS)."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.0")
        from gi.repository import Gdk, GdkPixbuf, Gtk, WebKit2
    except (ImportError, ValueError):
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("WebKit2", "4.1")
            from gi.repository import Gdk, GdkPixbuf, Gtk, WebKit2
        except (ImportError, ValueError):
            return False

    print("✨ Launching standalone FrameLoad window using native GTK WebKit2...")

    Gtk.init(sys.argv)
    window = Gtk.Window(title="FrameLoad")
    window.set_default_size(width, height)
    window.connect("destroy", Gtk.main_quit)

    if os.path.isfile(ICON_PATH):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(ICON_PATH)
            window.set_icon(pixbuf)
        except Exception:
            pass

    webview = WebKit2.WebView()
    webview.load_uri(url)
    window.add(webview)

    if fullscreen:
        window.fullscreen()

    window.show_all()
    Gtk.main()
    sys.exit(0)


def try_pywebview(url: str, fullscreen: bool = False, width: int = 1280, height: int = 800) -> bool:
    """Attempts to launch using pywebview."""
    try:
        import webview
    except ImportError:
        return False

    print("✨ Launching standalone FrameLoad window using pywebview...")
    webview.create_window(
        title="FrameLoad",
        url=url,
        width=width,
        height=height,
        fullscreen=fullscreen,
        background_color="#080c16"
    )
    webview.start()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="FrameLoad Standalone Window Launcher")
    parser.add_argument("--url", default="http://127.0.0.1:5050", help="URL to display")
    parser.add_argument("--fullscreen", action="store_true", help="Launch in fullscreen mode")
    parser.add_argument("--width", type=int, default=1280, help="Window width")
    parser.add_argument("--height", type=int, default=800, help="Window height")
    args = parser.parse_args()

    # Attempt native backends in priority order
    if try_qt(args.url, args.fullscreen, args.width, args.height):
        return
    if try_gtk_webkit(args.url, args.fullscreen, args.width, args.height):
        return
    if try_pywebview(args.url, args.fullscreen, args.width, args.height):
        return

    # No native GUI library available
    sys.exit(2)


if __name__ == "__main__":
    main()
