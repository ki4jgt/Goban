"""System (desktop) notifications on Windows, macOS and Linux, using only built-in tools.

Linux uses `notify-send`, macOS `osascript`, Windows a PowerShell toast. Title and
body are passed as arguments or environment variables, never pasted into script
text, so message content cannot inject commands. Failures are silent: a missing
tool just means no system notification.
"""

import os
import shutil
import subprocess
import sys
import threading

from .paths import ICON_DIR

_WINDOWS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$title = [Security.SecurityElement]::Escape($env:GOBAN_TITLE)
$body = [Security.SecurityElement]::Escape($env:GOBAN_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
# PowerShell's own app id is registered on every Windows 10/11 install.
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""


def desktop_notify(title, body):
    threading.Thread(target=_send, args=(title[:120], body[:300]), daemon=True).start()


def _send(title, body):
    try:
        if sys.platform == "win32":
            env = dict(os.environ, GOBAN_TITLE=title, GOBAN_BODY=body)
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", _WINDOWS_TOAST],
                env=env, timeout=15, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        elif sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", "on run argv", "-e",
                 "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                 title, body],
                timeout=10, capture_output=True,
            )
        elif shutil.which("notify-send"):
            icon = ICON_DIR / "goban-128.png"
            args = ["notify-send", "--app-name=Goban"]
            if icon.exists():
                args.append(f"--icon={icon}")
            subprocess.run(args + ["--", title, body], timeout=10, capture_output=True)
    except Exception:
        pass
