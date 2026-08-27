"""fukucycle web server entry point for LAN demos and temporary public tunnels."""

import os

import flet as ft

from test_20260709 import recovery_go_app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("FUKUCYCLE_PORT", os.environ.get("M3OW_PORT", "8080"))))
    ft.app(
        target=recovery_go_app,
        host="0.0.0.0",
        port=port,
        view=ft.AppView.WEB_BROWSER,
        assets_dir="assets",
    )
