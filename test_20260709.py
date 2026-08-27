"""Apple 製品に含まれる貴金属の推定量を Flet で表示するアプリ。

実際の含有量はモデル、年式、基板構成によって変わります。
ここでは学習用の概算値として表示します。
"""

import math
import json
import hashlib
import secrets
import time
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import date
from pathlib import Path

import flet as ft


# Shared by all Flet sessions in the same server process. Persistent content is
# still stored separately; this registry intentionally keeps only live presence.
ONLINE_USERS: dict[str, dict] = {}
ONLINE_USERS_LOCK = threading.Lock()
ONLINE_USER_TTL_SECONDS = 15
SERVER_CONTENT_REVISION = 0
COMMUNITY_COLUMNS: list[dict] = []
COMMUNITY_COLUMNS_LOCK = threading.RLock()
CONTENT_STORAGE_LOCK = threading.RLock()


METALS = {
    "Au": {"name": "金", "color": ft.Colors.AMBER_600},
    "Ag": {"name": "銀", "color": ft.Colors.BLUE_GREY_300},
    "Pd": {"name": "パラジウム", "color": ft.Colors.TEAL_400},
    "Pt": {"name": "白金", "color": ft.Colors.INDIGO_300},
}

APPLE_DEVICES = {
    "macbook_air": {
        "name": "MacBook Air",
        "generations": {
            "intel": {
                "name": "Intel 世代",
                "note": "Intel 搭載 MacBook Air の概算です。",
                "metals": {"Au": 0.032, "Ag": 0.310, "Pd": 0.011, "Pt": 0.001},
            },
            "m1": {
                "name": "M1 世代",
                "note": "Apple Silicon 初期の MacBook Air の概算です。",
                "metals": {"Au": 0.030, "Ag": 0.300, "Pd": 0.010, "Pt": 0.001},
            },
            "m2_m3": {
                "name": "M2 / M3 世代",
                "note": "現行に近い薄型 MacBook Air の概算です。",
                "metals": {"Au": 0.029, "Ag": 0.290, "Pd": 0.010, "Pt": 0.001},
            },
        },
    },
    "macbook_pro": {
        "name": "MacBook Pro",
        "generations": {
            "intel": {
                "name": "Intel 世代",
                "note": "Intel 搭載 MacBook Pro の概算です。",
                "metals": {"Au": 0.045, "Ag": 0.450, "Pd": 0.016, "Pt": 0.001},
            },
            "m1": {
                "name": "M1 / M1 Pro 世代",
                "note": "Apple Silicon 初期の MacBook Pro の概算です。",
                "metals": {"Au": 0.040, "Ag": 0.420, "Pd": 0.014, "Pt": 0.001},
            },
            "m2_m3": {
                "name": "M2 / M3 Pro 世代",
                "note": "近年の MacBook Pro の概算です。",
                "metals": {"Au": 0.042, "Ag": 0.430, "Pd": 0.015, "Pt": 0.001},
            },
        },
    },
    "iphone": {
        "name": "iPhone",
        "generations": {
            "iphone_8": {
                "name": "iPhone 8 / SE 系",
                "note": "ホームボタン世代に近い iPhone の概算です。",
                "metals": {"Au": 0.030, "Ag": 0.300, "Pd": 0.013, "Pt": 0.001},
            },
            "iphone_12": {
                "name": "iPhone 12 / 13 系",
                "note": "5G 対応以降の標準サイズ iPhone の概算です。",
                "metals": {"Au": 0.034, "Ag": 0.330, "Pd": 0.015, "Pt": 0.001},
            },
            "iphone_15": {
                "name": "iPhone 14 / 15 系",
                "note": "近年の高密度基板を持つ iPhone の概算です。",
                "metals": {"Au": 0.036, "Ag": 0.350, "Pd": 0.016, "Pt": 0.001},
            },
        },
    },
    "ipad": {
        "name": "iPad",
        "generations": {
            "standard": {
                "name": "iPad 標準モデル",
                "note": "標準的な iPad の概算です。",
                "metals": {"Au": 0.025, "Ag": 0.250, "Pd": 0.009, "Pt": 0.001},
            },
            "air": {
                "name": "iPad Air",
                "note": "薄型・高性能な iPad Air の概算です。",
                "metals": {"Au": 0.027, "Ag": 0.270, "Pd": 0.010, "Pt": 0.001},
            },
            "pro": {
                "name": "iPad Pro",
                "note": "部品点数が多い iPad Pro の概算です。",
                "metals": {"Au": 0.032, "Ag": 0.320, "Pd": 0.012, "Pt": 0.001},
            },
        },
    },
    "apple_watch": {
        "name": "Apple Watch",
        "generations": {
            "series_3": {
                "name": "Series 3 以前",
                "note": "旧世代 Apple Watch の概算です。",
                "metals": {"Au": 0.005, "Ag": 0.050, "Pd": 0.002, "Pt": 0.000},
            },
            "series_7": {
                "name": "Series 7 / 8 / 9",
                "note": "近年の標準 Apple Watch の概算です。",
                "metals": {"Au": 0.006, "Ag": 0.060, "Pd": 0.003, "Pt": 0.000},
            },
            "ultra": {
                "name": "Apple Watch Ultra",
                "note": "大型モデルの Apple Watch Ultra の概算です。",
                "metals": {"Au": 0.008, "Ag": 0.080, "Pd": 0.004, "Pt": 0.000},
            },
        },
    },
    "airpods": {
        "name": "AirPods",
        "generations": {
            "airpods": {
                "name": "AirPods",
                "note": "標準 AirPods と充電ケースを合わせた概算です。",
                "metals": {"Au": 0.004, "Ag": 0.040, "Pd": 0.002, "Pt": 0.000},
            },
            "airpods_pro": {
                "name": "AirPods Pro",
                "note": "AirPods Pro と充電ケースを合わせた概算です。",
                "metals": {"Au": 0.005, "Ag": 0.050, "Pd": 0.002, "Pt": 0.000},
            },
            "airpods_max": {
                "name": "AirPods Max",
                "note": "ヘッドホン型 AirPods Max の概算です。",
                "metals": {"Au": 0.012, "Ag": 0.120, "Pd": 0.005, "Pt": 0.000},
            },
        },
    },
    "mac_mini": {
        "name": "Mac mini",
        "generations": {
            "intel": {
                "name": "Intel 世代",
                "note": "Intel 搭載 Mac mini の概算です。",
                "metals": {"Au": 0.038, "Ag": 0.380, "Pd": 0.013, "Pt": 0.001},
            },
            "m1": {
                "name": "M1 世代",
                "note": "M1 搭載 Mac mini の概算です。",
                "metals": {"Au": 0.035, "Ag": 0.360, "Pd": 0.012, "Pt": 0.001},
            },
            "m2": {
                "name": "M2 世代",
                "note": "M2 搭載 Mac mini の概算です。",
                "metals": {"Au": 0.036, "Ag": 0.370, "Pd": 0.012, "Pt": 0.001},
            },
        },
    },
    "imac": {
        "name": "iMac",
        "generations": {
            "intel": {
                "name": "Intel 21.5 / 27 インチ",
                "note": "Intel 世代の iMac の概算です。",
                "metals": {"Au": 0.055, "Ag": 0.550, "Pd": 0.020, "Pt": 0.001},
            },
            "m1": {
                "name": "24 インチ M1",
                "note": "薄型 24 インチ iMac の概算です。",
                "metals": {"Au": 0.050, "Ag": 0.500, "Pd": 0.018, "Pt": 0.001},
            },
            "m3": {
                "name": "24 インチ M3",
                "note": "近年の 24 インチ iMac の概算です。",
                "metals": {"Au": 0.049, "Ag": 0.490, "Pd": 0.018, "Pt": 0.001},
            },
        },
    },
}

DEVICE_LIBRARY = {
    "smartphone": {
        "name": "スマホ",
        "icon": ft.Icons.PHONE_IPHONE,
        "color": ft.Colors.BLUE_600,
        "metals": {"Au": 0.034, "Ag": 0.330, "Pd": 0.015, "Pt": 0.001},
    },
    "feature_phone": {
        "name": "ガラケー",
        "icon": ft.Icons.PHONE_ANDROID,
        "color": ft.Colors.GREEN_600,
        "metals": {"Au": 0.020, "Ag": 0.180, "Pd": 0.008, "Pt": 0.001},
    },
    "digital_camera": {
        "name": "デジカメ",
        "icon": ft.Icons.CAMERA_ALT,
        "color": ft.Colors.DEEP_ORANGE_500,
        "metals": {"Au": 0.025, "Ag": 0.220, "Pd": 0.009, "Pt": 0.001},
    },
    "laptop": {
        "name": "ノートPC",
        "icon": ft.Icons.LAPTOP_MAC,
        "color": ft.Colors.INDIGO_500,
        "metals": {"Au": 0.040, "Ag": 0.420, "Pd": 0.014, "Pt": 0.001},
    },
    "game_console": {
        "name": "ゲーム機",
        "icon": ft.Icons.SPORTS_ESPORTS,
        "color": ft.Colors.PURPLE_500,
        "metals": {"Au": 0.050, "Ag": 0.520, "Pd": 0.018, "Pt": 0.001},
    },
    "tablet": {
        "name": "タブレット",
        "icon": ft.Icons.TABLET_MAC,
        "color": ft.Colors.CYAN_600,
        "metals": {"Au": 0.027, "Ag": 0.270, "Pd": 0.010, "Pt": 0.001},
    },
    "smartwatch": {
        "name": "スマートウォッチ",
        "icon": ft.Icons.WATCH,
        "color": ft.Colors.TEAL_600,
        "metals": {"Au": 0.006, "Ag": 0.060, "Pd": 0.003, "Pt": 0.000},
    },
    "desktop_pc": {
        "name": "デスクトップPC",
        "icon": ft.Icons.DESKTOP_MAC,
        "color": ft.Colors.BLUE_GREY_600,
        "metals": {"Au": 0.060, "Ag": 0.650, "Pd": 0.022, "Pt": 0.001},
    },
}


def main(page: ft.Page) -> None:
    page.title = "製品比較と Virtual Drawer"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = ft.Colors.BLACK
    page.padding = 24
    page.window_width = 1120
    page.window_height = 760
    page.scroll = ft.ScrollMode.AUTO

    selected_device_key = "macbook_air"
    selected_generation_key = "intel"
    selected_symbols = set(METALS.keys())
    active_device_key = "smartphone"
    sort_mode = "total_desc"
    tray_quantities = {}

    metal_list = ft.Column(spacing=8)
    table_area = ft.Column(spacing=12)
    total_text = ft.Text(size=20, weight=ft.FontWeight.BOLD)
    device_note = ft.Text(color=ft.Colors.BLUE_GREY_100)
    device_palette = ft.Row(wrap=True, spacing=10, run_spacing=10)
    water_surface = ft.Stack(width=600, height=220)
    tray_items = ft.Column(spacing=8)
    tray_total_text = ft.Text(size=18, weight=ft.FontWeight.BOLD)
    tray_metal_text = ft.Text(color=ft.Colors.BLUE_GREY_100)
    metal_bars = ft.Column(spacing=8)
    impact_cards = ft.Row(wrap=True, spacing=10, run_spacing=10)
    insight_text = ft.Text(color=ft.Colors.BLUE_GREY_100)
    active_device_text = ft.Text(color=ft.Colors.CYAN_100, weight=ft.FontWeight.BOLD)
    comparison_table = ft.Column(spacing=8)
    comparison_summary = ft.Text(color=ft.Colors.BLUE_GREY_100)

    sort_dropdown = ft.Dropdown(
        label="並び替え",
        value=sort_mode,
        options=[
            ft.dropdown.Option(key="total_desc", text="貴金属量が多い順"),
            ft.dropdown.Option(key="quantity_desc", text="数量が多い順"),
            ft.dropdown.Option(key="name_asc", text="名前順"),
        ],
        width=220,
    )

    device_dropdown = ft.Dropdown(
        label="Apple 製品",
        value=selected_device_key,
        options=[
            ft.dropdown.Option(key=device_key, text=device["name"])
            for device_key, device in APPLE_DEVICES.items()
        ],
        width=240,
    )
    generation_dropdown = ft.Dropdown(label="世代・モデル", width=240)

    def first_generation_key(device_key: str) -> str:
        return next(iter(APPLE_DEVICES[device_key]["generations"]))

    def update_generation_options() -> None:
        device = APPLE_DEVICES[selected_device_key]
        generation_dropdown.options = [
            ft.dropdown.Option(key=generation_key, text=generation["name"])
            for generation_key, generation in device["generations"].items()
        ]
        generation_dropdown.value = selected_generation_key

    def build_device_card(device_key: str, compact: bool = False) -> ft.Container:
        device = DEVICE_LIBRARY[device_key]
        is_active = device_key == active_device_key
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(device["icon"], size=30 if compact else 36, color=device["color"]),
                    ft.Text(
                        device["name"],
                        size=12 if compact else 13,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.BOLD,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
            ),
            width=96,
            height=86,
            padding=10,
            bgcolor=(
                ft.Colors.with_opacity(0.5, device["color"])
                if is_active
                else ft.Colors.BLUE_GREY_900
            ),
            border=ft.border.all(
                2 if is_active else 1,
                device["color"] if is_active else ft.Colors.BLUE_GREY_700,
            ),
            border_radius=8,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color=ft.Colors.with_opacity(0.18, device["color"]),
                offset=ft.Offset(0, 6),
            ),
            on_click=lambda event, key=device_key: select_device(key),
        )

    def build_materialization_sprite(
        device_key: str, quantity: int, left: int, top: int
    ) -> list[ft.Control]:
        device = DEVICE_LIBRARY[device_key]
        total = selected_total_amount(device_key) * quantity
        color = device["color"]
        surface_y = 104
        visible_symbols = [symbol for symbol in METALS if symbol in selected_symbols]
        material_controls = []

        for index, symbol in enumerate(visible_symbols[:4]):
            amount = device["metals"][symbol] * quantity
            particle_size = 18 + min(18, int(amount * 45))
            particle_left = left - 18 + index * 24
            particle_top = surface_y + 25 + (index % 2) * 28
            material_controls.extend(
                [
                    ft.Container(
                        left=particle_left,
                        top=particle_top,
                        width=particle_size,
                        height=particle_size,
                        bgcolor=ft.Colors.with_opacity(0.35, METALS[symbol]["color"]),
                        border=ft.border.all(1, METALS[symbol]["color"]),
                        border_radius=particle_size / 2,
                        shadow=ft.BoxShadow(
                            blur_radius=16,
                            color=ft.Colors.with_opacity(0.3, METALS[symbol]["color"]),
                            offset=ft.Offset(0, 4),
                        ),
                    ),
                    ft.Container(
                        left=particle_left,
                        top=particle_top + 2,
                        width=particle_size,
                        height=particle_size,
                        alignment=ft.alignment.center,
                        content=ft.Text(
                            symbol,
                            size=9,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE,
                        ),
                    ),
                ]
            )

        return [
            ft.Container(
                left=left - 18,
                top=surface_y - 4,
                width=92,
                height=12,
                border=ft.border.all(1, color),
                border_radius=12,
                opacity=0.48,
            ),
            ft.Container(
                left=left - 4,
                top=surface_y,
                width=64,
                height=6,
                border=ft.border.all(1, color),
                border_radius=8,
                opacity=0.2,
            ),
            ft.Container(
                left=left,
                top=top,
                width=56,
                height=56,
                bgcolor=ft.Colors.BLUE_GREY_900,
                border=ft.border.all(1, color),
                border_radius=8,
                alignment=ft.alignment.center,
                content=ft.Icon(device["icon"], size=34, color=color),
                shadow=ft.BoxShadow(
                    blur_radius=20,
                    color=ft.Colors.with_opacity(0.35, color),
                    offset=ft.Offset(0, 8),
                ),
            ),
            ft.Container(
                left=left - 16,
                top=surface_y + 14,
                width=88,
                height=12,
                bgcolor=ft.Colors.with_opacity(0.22, ft.Colors.CYAN_ACCENT_400),
                border_radius=8,
            ),
            ft.Container(
                left=left - 22,
                top=surface_y + 92,
                width=100,
                height=4,
                bgcolor=ft.Colors.with_opacity(0.38, ft.Colors.CYAN_ACCENT_400),
                border_radius=4,
            ),
            *material_controls,
            ft.Container(
                left=left - 22,
                top=174,
                width=100,
                content=ft.Text(
                    f"{device['name']} x{quantity}",
                    size=11,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BLUE_GREY_50,
                    text_align=ft.TextAlign.CENTER,
                ),
            ),
            ft.Container(
                left=left - 22,
                top=191,
                width=100,
                content=ft.Text(
                    f"{total:.3f} g",
                    size=10,
                    color=ft.Colors.CYAN_100,
                    text_align=ft.TextAlign.CENTER,
                ),
            ),
        ]

    def build_water_scene_controls() -> list[ft.Control]:
        controls: list[ft.Control] = [
            ft.Container(
                left=0,
                top=104,
                width=600,
                height=2,
                bgcolor=ft.Colors.CYAN_ACCENT_400,
                opacity=0.75,
            ),
            ft.Container(
                left=0,
                top=106,
                width=600,
                height=114,
                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.CYAN_ACCENT_400),
            ),
            ft.Container(
                left=12,
                top=125,
                width=560,
                height=1,
                bgcolor=ft.Colors.CYAN_100,
                opacity=0.45,
            ),
            ft.Container(
                left=42,
                top=154,
                width=500,
                height=1,
                bgcolor=ft.Colors.CYAN_100,
                opacity=0.28,
            ),
        ]

        if not tray_quantities:
            controls.append(
                ft.Container(
                    left=0,
                    top=58,
                    width=600,
                    alignment=ft.alignment.center,
                    content=ft.Column(
                        controls=[
                            ft.Icon(
                                ft.Icons.WATER_DROP,
                                color=ft.Colors.LIGHT_BLUE_300,
                                size=38,
                            ),
                            ft.Text(
                                "ここへ落とすと下側で物質化します",
                                color=ft.Colors.BLUE_GREY_100,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                    ),
                )
            )
            return controls

        positions = [(44, 42), (176, 34), (308, 46), (440, 36), (110, 50), (374, 44)]
        for index, (device_key, quantity) in enumerate(sorted_tray_items()):
            left, top = positions[index % len(positions)]
            controls.extend(build_materialization_sprite(device_key, quantity, left, top))
        return controls

    def update_device_palette() -> None:
        active_device_text.value = (
            f"選択中: {DEVICE_LIBRARY[active_device_key]['name']} "
            "水面クリックでも投入できます。"
        )
        device_palette.controls = [
            ft.Column(
                controls=[
                    ft.Draggable(
                        group="device",
                        data=device_key,
                        content=build_device_card(device_key),
                        content_feedback=ft.Container(
                            content=build_device_card(device_key, compact=True),
                            opacity=0.85,
                        ),
                        content_when_dragging=ft.Container(
                            content=ft.Icon(DEVICE_LIBRARY[device_key]["icon"], size=30),
                            width=96,
                            height=86,
                            alignment=ft.alignment.center,
                            bgcolor=ft.Colors.BLUE_GREY_800,
                            border=ft.border.all(1, ft.Colors.CYAN_700),
                            border_radius=8,
                        ),
                    ),
                    ft.FilledButton(
                        text="追加",
                        icon=ft.Icons.ADD_BOX,
                        width=96,
                        on_click=lambda event, key=device_key: add_to_tray(key),
                    ),
                ],
                spacing=6,
            )
            for device_key in DEVICE_LIBRARY
        ]

    def add_to_tray(device_key: str) -> None:
        tray_quantities[device_key] = tray_quantities.get(device_key, 0) + 1
        update_tray()

    def select_device(device_key: str) -> None:
        nonlocal active_device_key
        active_device_key = device_key
        update_device_palette()
        if page.controls:
            page.update()

    def add_active_device(event: ft.ControlEvent | None = None) -> None:
        add_to_tray(active_device_key)

    def set_tray_quantity(device_key: str, quantity: int) -> None:
        tray_quantities[device_key] = max(1, min(20, quantity))
        update_tray()

    def remove_from_tray(device_key: str) -> None:
        if device_key not in tray_quantities:
            return
        tray_quantities[device_key] -= 1
        if tray_quantities[device_key] <= 0:
            del tray_quantities[device_key]
        update_tray()

    def device_total_amount(device_key: str) -> float:
        return sum(DEVICE_LIBRARY[device_key]["metals"].values())

    def selected_total_amount(device_key: str) -> float:
        return sum(
            DEVICE_LIBRARY[device_key]["metals"][symbol]
            for symbol in METALS
            if symbol in selected_symbols
        )

    def sorted_tray_items() -> list[tuple[str, int]]:
        items = list(tray_quantities.items())
        if sort_mode == "quantity_desc":
            return sorted(items, key=lambda item: (-item[1], DEVICE_LIBRARY[item[0]]["name"]))
        if sort_mode == "name_asc":
            return sorted(items, key=lambda item: DEVICE_LIBRARY[item[0]]["name"])
        return sorted(
            items,
            key=lambda item: selected_total_amount(item[0]) * item[1],
            reverse=True,
        )

    def clear_tray(event: ft.ControlEvent | None = None) -> None:
        tray_quantities.clear()
        update_tray()

    def load_sample(event: ft.ControlEvent | None = None) -> None:
        tray_quantities.clear()
        tray_quantities.update(
            {
                "smartphone": 3,
                "feature_phone": 2,
                "laptop": 1,
                "game_console": 1,
            }
        )
        update_tray()

    def build_impact_card(label: str, value: str, icon: str, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, color=color, size=24),
                        width=42,
                        height=42,
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.with_opacity(0.12, color),
                        border_radius=8,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(label, size=11, color=ft.Colors.BLUE_GREY_200),
                            ft.Text(value, size=18, weight=ft.FontWeight.BOLD),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=190,
            padding=12,
            bgcolor=ft.Colors.with_opacity(0.52, ft.Colors.BLUE_GREY_900),
            border=ft.border.all(1, ft.Colors.with_opacity(0.4, color)),
            border_radius=8,
        )

    def update_tray() -> None:
        water_surface.controls = build_water_scene_controls()
        if tray_quantities:
            tray_items.controls = [
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        DEVICE_LIBRARY[device_key]["icon"],
                                        color=DEVICE_LIBRARY[device_key]["color"],
                                        size=26,
                                    ),
                                    ft.Text(DEVICE_LIBRARY[device_key]["name"], expand=True),
                                    ft.IconButton(
                                        icon=ft.Icons.REMOVE,
                                        tooltip="数量を減らす",
                                        on_click=lambda event, key=device_key: remove_from_tray(
                                            key
                                        ),
                                    ),
                                    ft.Text(
                                        f"{quantity} 個",
                                        width=52,
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.ADD,
                                        tooltip="数量を増やす",
                                        on_click=lambda event, key=device_key: add_to_tray(key),
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Slider(
                                value=quantity,
                                min=1,
                                max=20,
                                divisions=19,
                                label="{value} 個",
                                on_change=lambda event, key=device_key: set_tray_quantity(
                                    key, int(event.control.value)
                                ),
                            ),
                        ],
                        spacing=4,
                    ),
                    padding=8,
                    bgcolor=ft.Colors.with_opacity(0.62, ft.Colors.BLUE_GREY_900),
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                    border_radius=8,
                )
                for device_key, quantity in sorted_tray_items()
            ]
        else:
            tray_items.controls = [
                ft.Container(
                    content=ft.Text("水面にデバイスをドラッグ＆ドロップ"),
                    alignment=ft.alignment.center,
                    height=96,
                    bgcolor=ft.Colors.with_opacity(0.28, ft.Colors.CYAN_900),
                    border=ft.border.all(1, ft.Colors.CYAN_700),
                    border_radius=8,
                )
            ]

        total_devices = sum(tray_quantities.values())
        visible_symbols = [symbol for symbol in METALS if symbol in selected_symbols]
        metal_totals = {
            symbol: sum(
                DEVICE_LIBRARY[device_key]["metals"][symbol] * quantity
                for device_key, quantity in tray_quantities.items()
            )
            for symbol in visible_symbols
        }
        selected_total = sum(metal_totals.values())
        top_device_key = None
        if tray_quantities and visible_symbols:
            top_device_key = max(
                tray_quantities,
                key=lambda key: selected_total_amount(key) * tray_quantities[key],
            )

        impact_cards.controls = [
            build_impact_card(
                "投入数",
                f"{total_devices} 個",
                ft.Icons.TOUCH_APP,
                ft.Colors.CYAN_ACCENT_400,
            ),
            build_impact_card(
                "選択中の合計",
                f"{selected_total:.3f} g",
                ft.Icons.INSIGHTS,
                ft.Colors.AMBER_300,
            ),
            build_impact_card(
                "最大インパクト",
                DEVICE_LIBRARY[top_device_key]["name"] if top_device_key else "-",
                ft.Icons.RADAR,
                ft.Colors.TEAL_ACCENT_400,
            ),
        ]
        insight_text.value = (
            "水面の上が投入デバイス、下側が物質化した貴金属です。数量や金属フィルターを変えると比較も連動します。"
            if tray_quantities
            else "左のデバイスをドラッグするか、追加ボタンで水面に投入できます。"
        )
        tray_total_text.value = f"トレイ内の合計台数: {total_devices} 個"
        if visible_symbols:
            tray_metal_text.value = " / ".join(
                f"{METALS[symbol]['name']}: {amount:.3f} g"
                for symbol, amount in metal_totals.items()
            )
        else:
            tray_metal_text.value = "表示する金属が選択されていません。"

        max_metal_total = max(metal_totals.values(), default=0)
        if max_metal_total > 0:
            metal_bars.controls = [
                ft.Row(
                    controls=[
                        ft.Text(METALS[symbol]["name"], width=74),
                        ft.ProgressBar(
                            value=amount / max_metal_total,
                            color=METALS[symbol]["color"],
                            bgcolor=ft.Colors.BLUE_GREY_800,
                            width=260,
                            bar_height=10,
                        ),
                        ft.Text(f"{amount:.3f} g", width=76, text_align=ft.TextAlign.RIGHT),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for symbol, amount in metal_totals.items()
            ]
        else:
            metal_bars.controls = [
                ft.Text("金属別バーは、デバイスと表示金属を選ぶと表示されます。")
            ]

        if tray_quantities and visible_symbols:
            comparison_rows = []
            for device_key, quantity in sorted_tray_items():
                device = DEVICE_LIBRARY[device_key]
                total_per_unit = selected_total_amount(device_key)
                total = total_per_unit * quantity
                comparison_rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(device["name"])),
                            ft.DataCell(ft.Text(f"{quantity}")),
                            *[
                                ft.DataCell(
                                    ft.Text(f"{device['metals'][symbol] * quantity:.3f}")
                                )
                                for symbol in visible_symbols
                            ],
                            ft.DataCell(ft.Text(f"{total:.3f} g")),
                        ]
                    )
                )

            comparison_table.controls = [
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("製品")),
                        ft.DataColumn(ft.Text("数")),
                        *[
                            ft.DataColumn(ft.Text(METALS[symbol]["name"]))
                            for symbol in visible_symbols
                        ],
                        ft.DataColumn(ft.Text("合計")),
                    ],
                    rows=comparison_rows,
                    column_spacing=18,
                )
            ]

            top_device_key = max(
                tray_quantities,
                key=lambda key: selected_total_amount(key) * tray_quantities[key],
            )
            top_amount = selected_total_amount(top_device_key) * tray_quantities[top_device_key]
            comparison_summary.value = (
                f"最も貴金属量が多い製品: "
                f"{DEVICE_LIBRARY[top_device_key]['name']} ({top_amount:.3f} g)"
            )
        elif tray_quantities:
            comparison_table.controls = [
                ft.Container(
                    content=ft.Text("表示する金属を選ぶと比較表が表示されます。"),
                    alignment=ft.alignment.center,
                    height=72,
                    bgcolor=ft.Colors.with_opacity(0.44, ft.Colors.BLUE_GREY_900),
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                    border_radius=8,
                )
            ]
            comparison_summary.value = "金属フィルターをオンにしてください。"
        else:
            comparison_table.controls = [
                ft.Container(
                    content=ft.Text("比較する製品がまだありません。"),
                    alignment=ft.alignment.center,
                    height=72,
                    bgcolor=ft.Colors.with_opacity(0.44, ft.Colors.BLUE_GREY_900),
                    border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                    border_radius=8,
                )
            ]
            comparison_summary.value = "デバイスをトレイに入れると、製品別の比較表が表示されます。"

        if page.controls:
            page.update()

    def accept_device(event: ft.DragTargetEvent) -> None:
        source = page.get_control(event.src_id) or page.get_control(str(event.src_id))
        if source is not None:
            add_to_tray(source.data)

    def update_view() -> None:
        device = APPLE_DEVICES[selected_device_key]
        generation = device["generations"][selected_generation_key]
        device_note.value = f"{device['name']} - {generation['name']}: {generation['note']}"
        visible_symbols = [
            symbol for symbol in METALS if symbol in selected_symbols
        ]

        if visible_symbols:
            rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Row(
                                controls=[
                                    ft.Container(
                                        width=12,
                                        height=12,
                                        bgcolor=METALS[symbol]["color"],
                                        border_radius=6,
                                    ),
                                    ft.Text(METALS[symbol]["name"]),
                                ],
                                spacing=10,
                            )
                        ),
                        ft.DataCell(ft.Text(symbol)),
                        ft.DataCell(ft.Text(f"{generation['metals'][symbol]:.3f} g")),
                    ]
                )
                for symbol in visible_symbols
            ]

            table_area.controls = [
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("金属")),
                        ft.DataColumn(ft.Text("元素記号")),
                        ft.DataColumn(ft.Text("推定量")),
                    ],
                    rows=rows,
                    column_spacing=60,
                )
            ]
        else:
            table_area.controls = [
                ft.Container(
                    content=ft.Text("表示する貴金属が選択されていません。"),
                    padding=20,
                    bgcolor=ft.Colors.with_opacity(0.44, ft.Colors.BLUE_GREY_900),
                    border_radius=8,
                )
            ]

        total = sum(generation["metals"][symbol] for symbol in visible_symbols)
        total_text.value = f"表示中の合計: {total:.3f} g"
        page.update()

    def change_device(event: ft.ControlEvent) -> None:
        nonlocal selected_device_key, selected_generation_key
        selected_device_key = event.control.value
        selected_generation_key = first_generation_key(selected_device_key)
        update_generation_options()
        update_view()

    def change_generation(event: ft.ControlEvent) -> None:
        nonlocal selected_generation_key
        selected_generation_key = event.control.value
        update_view()

    def change_sort(event: ft.ControlEvent) -> None:
        nonlocal sort_mode
        sort_mode = event.control.value
        update_tray()

    def toggle_metal(symbol: str, checked: bool) -> None:
        if checked:
            selected_symbols.add(symbol)
        else:
            selected_symbols.discard(symbol)
        update_tray()
        update_view()

    device_dropdown.on_change = change_device
    generation_dropdown.on_change = change_generation
    sort_dropdown.on_change = change_sort
    update_generation_options()
    update_device_palette()
    update_tray()

    for symbol, metal in METALS.items():
        metal_list.controls.append(
            ft.Checkbox(
                label=f"{metal['name']} ({symbol})",
                value=True,
                on_change=lambda event, symbol=symbol: toggle_metal(
                    symbol, event.control.value
                ),
            )
        )

    page.add(
        ft.Column(
            controls=[
                ft.Text(
                    "製品比較と Virtual Drawer",
                    size=28,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "デバイスを水面へ落とすと、下側で貴金属として物質化し、数量込みの量を比較できます。",
                    color=ft.Colors.BLUE_GREY_200,
                ),
                ft.Divider(),
                ft.Text("Virtual Drawer", size=22, weight=ft.FontWeight.BOLD),
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Text("デバイス一覧", weight=ft.FontWeight.BOLD),
                                    active_device_text,
                                    device_palette,
                                ],
                                spacing=12,
                            ),
                            width=380,
                            padding=16,
                            bgcolor=ft.Colors.with_opacity(0.52, ft.Colors.BLUE_GREY_900),
                            border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                            border_radius=8,
                            shadow=ft.BoxShadow(
                                blur_radius=22,
                                color=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
                                offset=ft.Offset(0, 10),
                            ),
                        ),
                        ft.DragTarget(
                            group="device",
                            on_accept=accept_device,
                            content=ft.Container(
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            "水面ドロップエリア",
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Container(
                                            content=water_surface,
                                            width=600,
                                            height=220,
                                            on_click=add_active_device,
                                            gradient=ft.LinearGradient(
                                                begin=ft.alignment.top_left,
                                                end=ft.alignment.bottom_right,
                                                colors=[
                                                    ft.Colors.BLUE_GREY_900,
                                                    ft.Colors.BLUE_GREY_800,
                                                    ft.Colors.CYAN_900,
                                                ],
                                            ),
                                            border=ft.border.all(
                                                1,
                                                ft.Colors.with_opacity(
                                                    0.75, ft.Colors.CYAN_ACCENT_400
                                                ),
                                            ),
                                            border_radius=8,
                                            shadow=ft.BoxShadow(
                                                blur_radius=30,
                                                color=ft.Colors.with_opacity(
                                                    0.24, ft.Colors.CYAN_ACCENT_400
                                                ),
                                                offset=ft.Offset(0, 12),
                                            ),
                                        ),
                                        impact_cards,
                                        insight_text,
                                        ft.Row(
                                            controls=[
                                                sort_dropdown,
                                                ft.FilledButton(
                                                    text="サンプル投入",
                                                    icon=ft.Icons.AUTO_AWESOME,
                                                    on_click=load_sample,
                                                ),
                                                ft.OutlinedButton(
                                                    text="全クリア",
                                                    icon=ft.Icons.CLEAR,
                                                    on_click=clear_tray,
                                                ),
                                            ],
                                            spacing=10,
                                        ),
                                        tray_items,
                                        tray_total_text,
                                        tray_metal_text,
                                        metal_bars,
                                        ft.Divider(),
                                        ft.Text("製品比較", weight=ft.FontWeight.BOLD),
                                        comparison_table,
                                        comparison_summary,
                                    ],
                                    spacing=12,
                                ),
                                width=640,
                                padding=16,
                                bgcolor=ft.Colors.with_opacity(0.48, ft.Colors.BLUE_GREY_900),
                                border=ft.border.all(1, ft.Colors.CYAN_700),
                                border_radius=8,
                                shadow=ft.BoxShadow(
                                    blur_radius=24,
                                    color=ft.Colors.with_opacity(0.26, ft.Colors.BLACK),
                                    offset=ft.Offset(0, 12),
                                ),
                            ),
                        ),
                    ],
                    spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Divider(),
                ft.Text("Apple 製品の世代別参考値", size=22, weight=ft.FontWeight.BOLD),
                ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Text("製品を選択", weight=ft.FontWeight.BOLD),
                                    device_dropdown,
                                    generation_dropdown,
                                    ft.Divider(),
                                    ft.Text("表示する金属", weight=ft.FontWeight.BOLD),
                                    metal_list,
                                ],
                                spacing=12,
                            ),
                            width=280,
                            padding=16,
                            bgcolor=ft.Colors.with_opacity(0.52, ft.Colors.BLUE_GREY_900),
                            border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                            border_radius=8,
                        ),
                        ft.Container(
                            content=ft.Column(
                                controls=[device_note, table_area, total_text],
                                spacing=18,
                            ),
                            expand=True,
                            padding=16,
                            border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                            border_radius=8,
                        ),
                    ],
                    spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ],
            spacing=14,
        )
    )

    update_view()


def physics_app(page: ft.Page, on_back=None) -> None:
    page.title = "fukucycle — 都市鉱山ラボ"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#05070A"
    page.padding = 0
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.CYAN_ACCENT_400,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )
    try:
        page.window.width = 1240
        page.window.height = 820
        page.window.maximized = True
    except AttributeError:
        pass

    stage_width = 1240
    stage_height = 820
    waterline = 352
    active_device_key = "smartphone"
    selected_symbols = set(METALS.keys())
    tray_quantities: dict[str, int] = {}
    drops: list[dict[str, float | str]] = []
    click_marks: list[dict[str, float]] = []
    water_impulses: list[dict[str, float]] = []
    material_bursts: list[dict[str, float | str]] = []
    gravity = 1.0
    viscosity = 0.55
    next_fallback_x = 150
    simulation_running = True
    ui_visible = True
    sim_time = 0.0
    target_fps = 30
    last_stage_render = 0.0
    device_keys = list(DEVICE_LIBRARY)
    static_world_key: tuple[int, int, int] | None = None
    static_world_controls: list[ft.Control] = []
    wave_controls: list[ft.Container] = []
    glint_controls: list[ft.Container] = []

    world_stack = ft.Stack(width=stage_width, height=stage_height)
    world_container = ft.Container(
        content=world_stack,
        width=stage_width,
        height=stage_height,
    )
    water_drop_target = ft.DragTarget(group="device", content=world_container)
    stage_stack = ft.Stack(
        controls=[water_drop_target],
        width=stage_width,
        height=stage_height,
    )
    stage_container = ft.Container(content=stage_stack, width=stage_width, height=stage_height)
    palette = ft.Row(wrap=True, spacing=8, run_spacing=8)
    totals_panel = ft.Column(spacing=10)
    material_bars = ft.Column(spacing=8)
    device_quantities = ft.Column(spacing=6)
    active_label = ft.Text(weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_100)
    hint_text = ft.Text(color=ft.Colors.BLUE_GREY_100)

    def leave_lab(event: ft.ControlEvent | None = None) -> None:
        nonlocal simulation_running
        simulation_running = False
        page.on_keyboard_event = None
        page.on_resized = None
        page.clean()
        if on_back:
            on_back()

    def back_to_explorer_button() -> ft.Container:
        return ft.Container(
            left=16,
            top=16,
            content=ft.FilledButton(
                "探索画面へ戻る",
                icon=ft.Icons.ARROW_BACK,
                on_click=leave_lab,
                style=ft.ButtonStyle(bgcolor="#D6A06C", color="#120D0B"),
            ),
            shadow=ft.BoxShadow(blur_radius=18, color=ft.Colors.with_opacity(.35, ft.Colors.BLACK)),
        )

    # A small, local-first collection point directory.  The coordinates are used
    # only to calculate an approximate straight-line distance from the demo
    # location (Tokyo Station); no API key or network connection is required.
    user_location = {"lat": 35.6812, "lon": 139.7671, "label": "東京駅付近"}
    collection_points = [
        {
            "name": "Apple 丸の内 回収カウンター",
            "address": "東京都千代田区丸の内 2-5-2",
            "lat": 35.6798,
            "lon": 139.7638,
            "types": ["スマホ", "タブレット", "PC"],
            "hours": "10:00–21:00",
            "verified": True,
        },
        {
            "name": "有楽町 小型家電回収ボックス",
            "address": "東京都千代田区有楽町 2-10-1",
            "lat": 35.6751,
            "lon": 139.7634,
            "types": ["スマホ", "小型家電"],
            "hours": "08:30–20:00",
            "verified": True,
        },
        {
            "name": "京橋リサイクルステーション",
            "address": "東京都中央区京橋 2-2-1",
            "lat": 35.6768,
            "lon": 139.7701,
            "types": ["PC", "ゲーム機", "小型家電"],
            "hours": "09:00–18:00",
            "verified": False,
        },
        {
            "name": "日本橋 e-Waste ポイント",
            "address": "東京都中央区日本橋 2-5-1",
            "lat": 35.6825,
            "lon": 139.7744,
            "types": ["スマホ", "タブレット", "バッテリー"],
            "hours": "10:30–19:30",
            "verified": True,
        },
    ]

    def collection_distance(point: dict) -> float:
        lat1, lon1 = math.radians(user_location["lat"]), math.radians(user_location["lon"])
        lat2, lon2 = math.radians(point["lat"]), math.radians(point["lon"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371 * 2 * math.asin(math.sqrt(value))

    def notify(message: str) -> None:
        page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=ft.Colors.BLUE_GREY_800,
        )
        page.snack_bar.open = True
        page.update()

    def close_dialog(dialog: ft.AlertDialog) -> None:
        dialog.open = False
        page.update()

    def show_add_collection_point(event: ft.ControlEvent | None = None) -> None:
        compact = stage_width < 700
        name = ft.TextField(label="スポット名 *", autofocus=True)
        address = ft.TextField(label="住所 *", hint_text="例：東京都千代田区…")
        category = ft.Dropdown(
            label="主な回収品目",
            value="小型家電",
            options=[ft.dropdown.Option(item) for item in ["小型家電", "スマホ", "PC", "バッテリー"]],
        )
        hours = ft.TextField(label="受付時間", value="09:00–18:00")
        note = ft.Text(
            "追加したスポットは「未確認」として端末内の一覧に反映されます。",
            size=12,
            color=ft.Colors.BLUE_GREY_300,
        )
        dialog = ft.AlertDialog(modal=True)

        def save_point(save_event: ft.ControlEvent) -> None:
            if not (name.value or "").strip() or not (address.value or "").strip():
                name.error_text = "入力してください" if not (name.value or "").strip() else None
                address.error_text = "入力してください" if not (address.value or "").strip() else None
                page.update()
                return
            # Without geocoding, place a user contribution close to the current
            # demo location. It can still be searched and reviewed immediately.
            offset = 0.0014 + len(collection_points) * 0.00025
            collection_points.append(
                {
                    "name": name.value.strip(),
                    "address": address.value.strip(),
                    "lat": user_location["lat"] + offset,
                    "lon": user_location["lon"] - offset / 2,
                    "types": [category.value],
                    "hours": (hours.value or "時間未登録").strip(),
                    "verified": False,
                }
            )
            close_dialog(dialog)
            notify("回収スポットを追加しました")
            show_collection_points()

        dialog.title = ft.Row(
            [
                ft.Container(
                    content=ft.Icon(ft.Icons.ADD_LOCATION_ALT, color=ft.Colors.CYAN_ACCENT_400),
                    width=44,
                    height=44,
                    alignment=ft.alignment.center,
                    bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.CYAN_ACCENT_400),
                    border_radius=12,
                ),
                ft.Column([ft.Text("回収スポットを追加", size=20, weight=ft.FontWeight.BOLD),
                           ft.Text("みんなで回収網をアップデート", size=12, color=ft.Colors.BLUE_GREY_300)], spacing=1),
            ],
            spacing=12,
        )
        dialog.content = ft.Container(
            content=ft.Column(
                [name, address, *( [category, hours] if compact else [ft.Row([category, hours], spacing=12)] ), note],
                tight=True,
                spacing=14,
            ),
            width=min(520, stage_width - 64),
        )
        dialog.actions = [
            ft.TextButton("キャンセル", on_click=lambda e: close_dialog(dialog)),
            ft.FilledButton("スポットを追加", icon=ft.Icons.ADD, on_click=save_point),
        ]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def show_collection_points(event: ft.ControlEvent | None = None) -> None:
        compact = stage_width < 700
        search = ft.TextField(
            hint_text="施設名・住所・回収品目で検索",
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            expand=True,
        )
        category = ft.Dropdown(
            value="すべて",
            dense=True,
            width=150,
            options=[ft.dropdown.Option(item) for item in ["すべて", "スマホ", "PC", "小型家電", "バッテリー"]],
        )
        result_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO, height=280 if compact else 320)
        result_count = ft.Text(size=12, color=ft.Colors.BLUE_GREY_300)
        dialog = ft.AlertDialog(modal=True)

        def filtered_points() -> list[dict]:
            query = (search.value or "").strip().lower()
            selected = category.value or "すべて"
            matches = []
            for point in collection_points:
                haystack = " ".join([point["name"], point["address"], *point["types"]]).lower()
                if query and query not in haystack:
                    continue
                if selected != "すべて" and selected not in point["types"]:
                    continue
                matches.append(point)
            return sorted(matches, key=collection_distance)

        def point_card(point: dict) -> ft.Container:
            distance = collection_distance(point)
            badge_color = ft.Colors.TEAL_ACCENT_400 if point["verified"] else ft.Colors.AMBER_300
            leading = ft.Container(
                content=ft.Icon(ft.Icons.LOCATION_ON, color=ft.Colors.CYAN_ACCENT_400),
                width=46,
                height=46,
                alignment=ft.alignment.center,
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.CYAN_ACCENT_400),
                border_radius=12,
            )
            details = ft.Column(
                [
                    ft.Row([ft.Text(point["name"], weight=ft.FontWeight.BOLD, expand=True),
                            ft.Text("確認済" if point["verified"] else "未確認", size=10, color=badge_color)], spacing=8),
                    ft.Text(point["address"], size=11, color=ft.Colors.BLUE_GREY_300),
                    ft.Row([ft.Icon(ft.Icons.SCHEDULE, size=13, color=ft.Colors.BLUE_GREY_300),
                            ft.Text(point["hours"], size=11),
                            ft.Text("  •  ".join(point["types"]), size=11, color=ft.Colors.CYAN_100)], spacing=5, wrap=True),
                ],
                spacing=4,
                expand=True,
            )
            distance_label = ft.Text(f"{distance:.1f} km", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_100)
            card_content = (
                ft.Column([ft.Row([leading, details], spacing=10),
                           ft.Row([distance_label, ft.Text("現在地からの直線距離", size=10, color=ft.Colors.BLUE_GREY_400),
                                   ft.Container(expand=True), ft.Icon(ft.Icons.DIRECTIONS, size=18, color=ft.Colors.CYAN_ACCENT_400)], spacing=6)], spacing=8)
                if compact
                else ft.Row(
                    [leading, details,
                        ft.Column([distance_label,
                                   ft.Text("直線距離", size=10, color=ft.Colors.BLUE_GREY_400)], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=0),
                        ft.IconButton(icon=ft.Icons.DIRECTIONS, icon_color=ft.Colors.CYAN_ACCENT_400,
                                      tooltip="経路を確認", on_click=lambda e, p=point: notify(f"{p['name']}への経路を選択しました")),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                )
            )
            return ft.Container(
                content=card_content,
                padding=12,
                bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLUE_GREY_900),
                border=ft.border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.WHITE)),
                border_radius=14,
            )

        def refresh_results(change_event: ft.ControlEvent | None = None) -> None:
            matches = filtered_points()
            result_count.value = f"{len(matches)}件  •  距離が近い順"
            result_list.controls = [point_card(point) for point in matches] or [
                ft.Container(ft.Text("条件に合うスポットがありません"), alignment=ft.alignment.center, height=90)
            ]
            page.update()

        search.on_change = refresh_results
        category.on_change = refresh_results
        title_content = ft.Row(
            [
                ft.Column([ft.Text("近くの回収スポット", size=22, weight=ft.FontWeight.BOLD),
                           ft.Row([ft.Icon(ft.Icons.MY_LOCATION, size=14, color=ft.Colors.CYAN_ACCENT_400),
                                   ft.Text(user_location["label"], size=12, color=ft.Colors.BLUE_GREY_300)], spacing=5)], spacing=3, expand=True),
                ft.FilledButton("新しい場所を追加", icon=ft.Icons.ADD_LOCATION_ALT,
                                on_click=lambda e: (close_dialog(dialog), show_add_collection_point())),
            ]
        )
        if compact:
            title_content = ft.Column(
                [title_content.controls[0],
                 ft.FilledButton("新しい場所を追加", icon=ft.Icons.ADD_LOCATION_ALT,
                                 on_click=lambda e: (close_dialog(dialog), show_add_collection_point()))],
                spacing=10,
            )
        dialog.title = title_content
        map_width = min(760, stage_width - 56)
        dialog.content = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Stack([
                            ft.Container(gradient=ft.LinearGradient(colors=[ft.Colors.BLUE_GREY_900, ft.Colors.CYAN_900]), border_radius=14),
                            ft.Container(left=50, top=34, content=ft.Icon(ft.Icons.LOCATION_ON, color=ft.Colors.CYAN_ACCENT_400, size=34)),
                            ft.Container(left=195, top=68, content=ft.Icon(ft.Icons.LOCATION_ON, color=ft.Colors.AMBER_300, size=30)),
                            ft.Container(left=map_width * 0.72, top=28, content=ft.Icon(ft.Icons.LOCATION_ON, color=ft.Colors.TEAL_ACCENT_400, size=34)),
                            ft.Container(left=map_width * 0.50, top=42, content=ft.Icon(ft.Icons.MY_LOCATION, color=ft.Colors.WHITE, size=22)),
                            ft.Container(left=18, bottom=12, content=ft.Text("現在地周辺 • プレビュー", size=11, color=ft.Colors.BLUE_GREY_200)),
                        ], height=112),
                        height=112,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.CYAN_ACCENT_400)),
                        border_radius=14,
                    ),
                    ft.Column([search, category], spacing=8) if compact else ft.Row([search, category], spacing=10),
                    result_count,
                    result_list,
                ],
                spacing=10,
                tight=True,
            ),
            width=map_width,
        )
        dialog.actions = [ft.TextButton("閉じる", on_click=lambda e: close_dialog(dialog))]
        page.overlay.append(dialog)
        dialog.open = True
        refresh_results()

    gravity_slider = ft.Slider(
        value=gravity,
        min=0.4,
        max=1.8,
        divisions=14,
        label="重力 {value}",
        width=220,
    )
    viscosity_slider = ft.Slider(
        value=viscosity,
        min=0.1,
        max=1.0,
        divisions=9,
        label="粘性 {value}",
        width=220,
    )
    active_device_dropdown = ft.Dropdown(
        label="デバイスを選択",
        value=active_device_key,
        options=[
            ft.dropdown.Option(key=device_key, text=device["name"])
            for device_key, device in DEVICE_LIBRARY.items()
        ],
        width=260,
    )

    def visible_symbols() -> list[str]:
        return [symbol for symbol in METALS if symbol in selected_symbols]

    def selected_total_amount(device_key: str) -> float:
        return sum(DEVICE_LIBRARY[device_key]["metals"][symbol] for symbol in visible_symbols())

    def clamp_x(x: float) -> float:
        return max(90, min(stage_width - 120, float(x)))

    def clamp_y(y: float) -> float:
        return max(56, min(waterline - 96, float(y)))

    def resize_stage(event: ft.ControlEvent | None = None) -> None:
        nonlocal stage_width, stage_height, waterline, next_fallback_x
        window_width = getattr(getattr(page, "window", None), "width", None)
        window_height = getattr(getattr(page, "window", None), "height", None)
        width = getattr(page, "width", None) or window_width or 1240
        height = getattr(page, "height", None) or window_height or 820
        stage_width = max(390, int(width))
        stage_height = max(700, int(height))
        waterline = int(stage_height * 0.43)
        stage_stack.width = stage_width
        stage_stack.height = stage_height
        world_stack.width = stage_width
        world_stack.height = stage_height
        world_container.width = stage_width
        world_container.height = stage_height
        stage_container.width = stage_width
        stage_container.height = stage_height
        next_fallback_x = min(next_fallback_x, stage_width - 150)
        for drop in drops:
            drop["x"] = clamp_x(float(drop["x"]))
            if str(drop["phase"]) == "fall":
                drop["y"] = clamp_y(float(drop["y"]))
            else:
                drop["y"] = min(float(drop["y"]), stage_height - 170)
        render()

    def fallback_x() -> float:
        nonlocal next_fallback_x
        value = next_fallback_x
        next_fallback_x += 135
        if next_fallback_x > stage_width - 140:
            next_fallback_x = 150
        return value

    def select_device(device_key: str) -> None:
        nonlocal active_device_key
        active_device_key = device_key
        active_device_dropdown.value = device_key
        render()

    def change_active_device(event: ft.ControlEvent) -> None:
        select_device(event.control.value)

    def drop_active_device(event: ft.ControlEvent | None = None) -> None:
        add_drop(active_device_key)

    def add_drop(device_key: str, x: float | None = None, y: float | None = None) -> None:
        drop_x = clamp_x(x if x is not None else fallback_x())
        drop_y = clamp_y(y if y is not None else 90)
        material_total = selected_total_amount(device_key)
        mass = 0.72 + material_total * 6.2
        area = 0.82 + min(1.45, material_total * 3.4)
        tray_quantities[device_key] = tray_quantities.get(device_key, 0) + 1
        click_marks.append({"x": drop_x, "y": drop_y, "age": 0.0})
        drops.append(
            {
                "device_key": device_key,
                "x": drop_x,
                "y": drop_y,
                "vx": ((len(drops) % 5) - 2) * 14.0,
                "vy": 0.0,
                "age": 0.0,
                "dissolve": 0.0,
                "phase": "fall",
                "impact": selected_total_amount(device_key) * gravity,
                "mass": mass,
                "area": area,
                "water_hit": 0.0,
                "depth": 0.0,
                "burst_done": 0.0,
                "settle_done": 0.0,
                "spin": 0.0,
                "seed": float((len(drops) * 37) % 100),
            }
        )
        if len(click_marks) > 6:
            del click_marks[0]
        render()

    def water_field_force(x: float, y: float) -> float:
        depth_factor = max(0.15, min(1.0, (y - waterline + 120) / max(1, stage_height - waterline)))
        force = 0.0
        for impulse in water_impulses:
            age = float(impulse["age"])
            strength = float(impulse["strength"])
            decay = max(0.0, 1 - age / 2.4)
            wave_front = 80 + age * (210 + strength * 42)
            distance = abs(x - float(impulse["x"]))
            band = 78 + strength * 34
            proximity = max(0.0, 1 - abs(distance - wave_front) / band)
            direction = 1 if x >= float(impulse["x"]) else -1
            force += direction * strength * proximity * decay * 190 * depth_factor
        return force

    def step_drop(drop: dict[str, float | str], dt: float) -> None:
        device_key = str(drop["device_key"])
        phase = str(drop["phase"])
        x = float(drop["x"])
        y = float(drop["y"])
        vx = float(drop.get("vx", 0.0))
        vy = float(drop["vy"])
        age = float(drop["age"]) + dt
        dissolve = float(drop["dissolve"])
        mass = float(drop.get("mass", 1.0))
        area = float(drop.get("area", 1.0))
        depth = max(0.0, y - waterline)
        current = math.sin(sim_time * 1.7 + y * 0.018 + mass) * (26 + 18 * (1 - viscosity))
        eddy = math.cos(sim_time * 2.9 + x * 0.01 + mass) * (10 + dissolve * 16)
        field_force = water_field_force(x, y)

        if phase == "fall":
            vy += 980 * gravity * dt
            x += vx * dt * 0.35
            y += vy * dt
            if y >= waterline - 56:
                y = waterline - 56
                hit_strength = min(2.6, max(0.35, abs(vy) / 420 * mass))
                water_impulses.append(
                    {
                        "x": x,
                        "age": 0.0,
                        "strength": hit_strength,
                        "width": 110 + hit_strength * 120,
                    }
                )
                if len(water_impulses) > 10:
                    del water_impulses[0]
                drop["water_hit"] = hit_strength
                vy *= 0.12 + min(0.1, viscosity * 0.08)
                vx = vx * 1.6 + eddy * 0.55
                phase = "splash"
                age = 0.0
        elif phase == "splash":
            damping = max(0.05, 1 - viscosity * 0.12)
            vx += (current + eddy + field_force * 0.24) * dt
            vy = vy * damping + (120 * gravity + mass * 16) * dt
            x += vx * dt
            vx *= 0.9 - min(0.08, viscosity * 0.04)
            y += vy * dt
            dissolve = min(0.28, dissolve + dt * 0.7)
            if age > 0.24 + viscosity * 0.18:
                phase = "sink"
                age = 0.0
        elif phase == "sink":
            drag = min(0.82, (0.18 + viscosity * 0.34) * area)
            buoyancy = 250 * viscosity * area
            pressure_drag = min(0.36, depth / max(1, stage_height) * 0.9)
            vx += (current * 0.9 + eddy * 0.4 + field_force * 0.38) * dt
            vy += (500 * gravity * mass - buoyancy) * dt
            vy *= max(0.58, 1 - drag * dt * 4.2 - pressure_drag * dt)
            x += vx * dt
            vx *= max(0.84, 1 - viscosity * 0.12)
            y += vy * dt
            dissolve = min(0.86, dissolve + dt * (0.22 + gravity * 0.18 + depth / stage_height * 0.5))
            if y > waterline + 132 or dissolve > 0.82:
                phase = "dissolve"
                age = 0.0
        elif phase == "dissolve":
            floor_y = stage_height - 170
            vx += (current * 0.34 + field_force * 0.22) * dt
            vy += (120 * gravity - 80 * viscosity) * dt
            vy *= 0.78
            vx *= 0.88
            x += vx * dt
            y += vy * dt
            dissolve = min(1.0, dissolve + dt * (0.28 + viscosity * 0.2))
            y = min(y, floor_y)
            if y >= floor_y - 2:
                vy *= -0.08
                vx *= 0.55
            if dissolve >= 1.0 and age > 1.2 and abs(vy) < 32:
                phase = "settled"
                age = 0.0
                vx = 0.0
                vy = 0.0
                if float(drop.get("settle_done", 0.0)) == 0.0:
                    material_bursts.append(
                        {
                            "x": x,
                            "y": y + 74,
                            "age": 0.0,
                            "strength": 0.62,
                            "color": DEVICE_LIBRARY[device_key]["color"],
                            "kind": "settle",
                        }
                    )
                    drop["settle_done"] = 1.0
        else:
            dissolve = 1.0
            vx = 0.0
            vy = 0.0
            y = min(y, stage_height - 170)

        drop["phase"] = phase
        drop["x"] = clamp_x(x)
        drop["y"] = y
        drop["vx"] = vx
        drop["vy"] = vy
        drop["age"] = age
        drop["dissolve"] = dissolve
        drop["depth"] = max(0.0, y - waterline)
        drop["spin"] = float(drop.get("spin", 0.0)) + (vx * 0.02 + vy * 0.004) * dt

        if phase == "dissolve" and float(drop.get("burst_done", 0.0)) == 0.0:
            material_bursts.append(
                {
                    "x": x,
                    "y": y + 70,
                    "age": 0.0,
                    "strength": 1.0 + dissolve,
                    "color": DEVICE_LIBRARY[device_key]["color"],
                    "kind": "material",
                }
            )
            if len(material_bursts) > 12:
                del material_bursts[0]
            drop["burst_done"] = 1.0

    def refresh_drop_masses() -> None:
        for drop in drops:
            device_key = str(drop["device_key"])
            drop["mass"] = 0.7 + selected_total_amount(device_key) * 6

    def physics_loop() -> None:
        nonlocal sim_time, last_stage_render
        last = time.time()
        while simulation_running:
            now = time.time()
            dt = min(0.033, now - last)
            last = now
            sim_time += dt
            if drops:
                for drop in drops:
                    if str(drop["phase"]) != "settled":
                        step_drop(drop, dt)
            if click_marks:
                for mark in click_marks:
                    mark["age"] = float(mark["age"]) + dt
                click_marks[:] = [
                    mark for mark in click_marks if float(mark["age"]) < 0.55
                ]
            if water_impulses:
                for impulse in water_impulses:
                    impulse["age"] = float(impulse["age"]) + dt
                water_impulses[:] = [
                    impulse for impulse in water_impulses if float(impulse["age"]) < 2.4
                ]
            if material_bursts:
                for burst in material_bursts:
                    burst["age"] = float(burst["age"]) + dt
                material_bursts[:] = [
                    burst for burst in material_bursts if float(burst["age"]) < 1.4
                ]
            if now - last_stage_render >= 1 / target_fps:
                render_stage_only()
                last_stage_render = now
            time.sleep(1 / target_fps)

    def clear_all(event: ft.ControlEvent | None = None) -> None:
        tray_quantities.clear()
        drops.clear()
        click_marks.clear()
        water_impulses.clear()
        material_bursts.clear()
        render()

    def load_sample(event: ft.ControlEvent | None = None) -> None:
        clear_all()
        for device_key, x in [
            ("smartphone", 240),
            ("laptop", 430),
            ("game_console", 650),
            ("digital_camera", 835),
            ("smartwatch", 1010),
        ]:
            add_drop(device_key, x, waterline - 120)

    def set_quantity(device_key: str, delta: int) -> None:
        current = tray_quantities.get(device_key, 0) + delta
        if current <= 0:
            tray_quantities.pop(device_key, None)
        else:
            tray_quantities[device_key] = current
        render()

    def undo_last_drop(event: ft.ControlEvent | None = None) -> None:
        if not drops:
            return
        last_drop = drops.pop()
        device_key = str(last_drop["device_key"])
        current = tray_quantities.get(device_key, 0) - 1
        if current <= 0:
            tray_quantities.pop(device_key, None)
        else:
            tray_quantities[device_key] = current
        render()

    def clear_settled(event: ft.ControlEvent | None = None) -> None:
        removed_counts: dict[str, int] = {}
        remaining_drops = []
        for drop in drops:
            if str(drop["phase"]) == "settled":
                device_key = str(drop["device_key"])
                removed_counts[device_key] = removed_counts.get(device_key, 0) + 1
            else:
                remaining_drops.append(drop)

        if not removed_counts:
            return

        drops[:] = remaining_drops
        for device_key, count in removed_counts.items():
            current = tray_quantities.get(device_key, 0) - count
            if current <= 0:
                tray_quantities.pop(device_key, None)
            else:
                tray_quantities[device_key] = current
        render()

    def reset_physics(event: ft.ControlEvent | None = None) -> None:
        nonlocal gravity, viscosity
        gravity = 1.0
        viscosity = 0.55
        gravity_slider.value = gravity
        viscosity_slider.value = viscosity
        render()

    def toggle_symbol(symbol: str, checked: bool) -> None:
        if checked:
            selected_symbols.add(symbol)
        else:
            selected_symbols.discard(symbol)
        refresh_drop_masses()
        render()

    def update_gravity(event: ft.ControlEvent) -> None:
        nonlocal gravity
        gravity = float(event.control.value)
        render()

    def update_viscosity(event: ft.ControlEvent) -> None:
        nonlocal viscosity
        viscosity = float(event.control.value)
        render()

    def toggle_ui(event: ft.ControlEvent | None = None) -> None:
        nonlocal ui_visible
        ui_visible = not ui_visible
        render()

    def build_device_chip(device_key: str) -> ft.Column:
        device = DEVICE_LIBRARY[device_key]
        is_active = device_key == active_device_key
        border_color = device["color"] if is_active else ft.Colors.BLUE_GREY_700
        return ft.Column(
            controls=[
                ft.Draggable(
                    group="device",
                    data=device_key,
                    on_drag_start=lambda event, key=device_key: select_device(key),
                    content=ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Icon(device["icon"], size=30, color=device["color"]),
                                ft.Text(
                                    device["name"],
                                    size=10,
                                    weight=ft.FontWeight.BOLD,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        width=86,
                        height=76,
                        alignment=ft.alignment.center,
                        bgcolor=(
                            ft.Colors.with_opacity(0.30, device["color"])
                            if is_active
                            else ft.Colors.with_opacity(0.64, ft.Colors.BLUE_GREY_900)
                        ),
                        border=ft.border.all(2 if is_active else 1, border_color),
                        border_radius=8,
                        on_click=lambda event, key=device_key: select_device(key),
                    ),
                    content_feedback=ft.Container(
                        content=ft.Icon(device["icon"], size=34, color=device["color"]),
                        width=70,
                        height=70,
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.with_opacity(0.82, ft.Colors.BLUE_GREY_900),
                        border=ft.border.all(1, device["color"]),
                        border_radius=8,
                    ),
                ),
                ft.IconButton(
                    icon=ft.Icons.ADD_CIRCLE,
                    icon_color=device["color"],
                    tooltip="中央付近に落とす",
                    on_click=lambda event, key=device_key: add_drop(key),
                ),
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def build_particle(
        symbol: str,
        x: float,
        y: float,
        amount: float,
        opacity: float,
    ) -> list[ft.Control]:
        pulse = 1 + math.sin(sim_time * 5.4 + x * 0.02 + y * 0.01) * 0.08
        size = (15 + min(30, int(amount * 90 * gravity))) * pulse
        color = METALS[symbol]["color"]
        return [
            ft.Container(
                left=x - size * 0.35,
                top=y - size * 0.35,
                width=size * 1.7,
                height=size * 1.7,
                border=ft.border.all(1, ft.Colors.with_opacity(0.45, color)),
                border_radius=size,
                opacity=max(0.05, opacity * 0.85),
            ),
            ft.Container(
                left=x,
                top=y,
                width=size,
                height=size,
                bgcolor=ft.Colors.with_opacity(0.34 + opacity, color),
                border=ft.border.all(1, color),
                border_radius=size / 2,
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    color=ft.Colors.with_opacity(0.36, color),
                    offset=ft.Offset(0, 6),
                ),
            ),
            ft.Container(
                left=x + size * 0.2,
                top=y + size * 0.16,
                width=max(5, size * 0.34),
                height=max(5, size * 0.34),
                bgcolor=ft.Colors.with_opacity(0.68, ft.Colors.WHITE),
                border_radius=size,
                opacity=max(0.1, opacity + 0.18),
            ),
            ft.Container(
                left=x,
                top=y + 2,
                width=size,
                height=size,
                alignment=ft.alignment.center,
                content=ft.Text(
                    symbol,
                    size=9,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.WHITE,
                ),
            ),
        ]

    def phase_label(phase: str) -> str:
        return {
            "fall": "落下中",
            "splash": "着水",
            "sink": "沈降中",
            "dissolve": "素材化中",
            "settled": "回収済み",
        }.get(phase, phase)

    def build_drop_controls(
        drop: dict[str, float | str],
        index: int,
        active_symbols: list[str],
    ) -> list[ft.Control]:
        device_key = str(drop["device_key"])
        device = DEVICE_LIBRARY[device_key]
        x = float(drop["x"])
        y = float(drop["y"])
        impact = float(drop["impact"])
        phase = str(drop["phase"])
        age = float(drop["age"])
        dissolve = float(drop["dissolve"])
        vx = float(drop.get("vx", 0.0))
        spin = float(drop.get("spin", 0.0))
        seed = float(drop.get("seed", 0.0))
        water_hit = float(drop.get("water_hit", impact))
        depth = float(drop.get("depth", max(0.0, y - waterline)))
        splash_width = 70 + min(260, (water_hit + age * 0.35) * 210)
        sink_base = max(waterline + 34, y + 72)
        device_opacity = max(0.12, 1 - dissolve * 0.95)
        wobble = math.sin(sim_time * 6 + seed) * (2 + dissolve * 6)
        controls: list[ft.Control] = []

        if phase == "fall":
            for trail_index in range(2):
                trail_height = 30 + trail_index * 18
                controls.append(
                    ft.Container(
                        left=x - 1 - vx * 0.03 * trail_index,
                        top=y - trail_height - trail_index * 12,
                        width=2,
                        height=trail_height,
                        bgcolor=device["color"],
                        opacity=max(0.04, 0.22 - trail_index * 0.045),
                        border_radius=2,
                    )
                )

        controls.extend(
            [
                ft.Container(
                    left=x - splash_width / 2,
                    top=waterline - 10,
                    width=splash_width,
                    height=20,
                    border=ft.border.all(1, device["color"]),
                    border_radius=20,
                    opacity=0.08 + min(0.42, impact * 2.2 + age * 0.25),
                ),
                ft.Container(
                    left=x - splash_width / 3,
                    top=waterline - 3,
                    width=splash_width * 0.66,
                    height=8,
                    border=ft.border.all(1, ft.Colors.CYAN_ACCENT_400),
                    border_radius=8,
                    opacity=0.25,
                ),
            ]
        )

        if phase in {"splash", "sink", "dissolve"}:
            splash_count = 4 + min(5, int(water_hit * 2.2))
            for splash_index in range(splash_count):
                direction = -1 if splash_index % 2 == 0 else 1
                travel = 24 + splash_index * 12 + age * (150 + water_hit * 45)
                drop_size = max(4, 9 - splash_index * 0.45)
                controls.append(
                    ft.Container(
                        left=x + direction * travel * (0.44 + splash_index * 0.035),
                        top=waterline - 18 - math.sin(age * 4 + splash_index) * 18 + splash_index,
                        width=drop_size,
                        height=drop_size,
                        bgcolor=ft.Colors.with_opacity(0.62, ft.Colors.CYAN_ACCENT_400),
                        border_radius=drop_size,
                        opacity=max(0.0, 0.64 - age * 0.72 - splash_index * 0.025),
                    )
                )

        if phase in {"sink", "dissolve"}:
            bubble_count = 5 + min(4, int(depth / 110))
            for bubble_index in range(bubble_count):
                bubble_age = (age + bubble_index * 0.18 + seed * 0.01) % 1.5
                bubble_size = 4 + (bubble_index % 4) * 2
                bubble_x = x + math.sin(sim_time * 2.4 + bubble_index + seed) * (24 + dissolve * 44)
                bubble_y = y + 54 + bubble_index * 18 - bubble_age * 58
                controls.append(
                    ft.Container(
                        left=bubble_x,
                        top=bubble_y,
                        width=bubble_size,
                        height=bubble_size,
                        border=ft.border.all(1, ft.Colors.CYAN_100),
                        border_radius=bubble_size,
                        opacity=max(0.04, 0.42 - bubble_age * 0.22),
                    )
                )

            for pressure_index in range(2):
                pressure_width = 74 + pressure_index * 36 + depth * 0.08
                controls.append(
                    ft.Container(
                        left=x - pressure_width / 2,
                        top=y + 18 + pressure_index * 28,
                        width=pressure_width,
                        height=10,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.5, ft.Colors.CYAN_100)),
                        border_radius=10,
                        opacity=max(0.04, 0.22 - pressure_index * 0.07),
                    )
                )

        if y < waterline + 12:
            reflection_height = max(8, 52 * (1 - dissolve))
            controls.append(
                ft.Container(
                    left=x - 30 + wobble * 0.3,
                    top=waterline + 12,
                    width=60,
                    height=reflection_height,
                    alignment=ft.alignment.center,
                    opacity=max(0.04, 0.24 - dissolve * 0.2),
                    content=ft.Icon(device["icon"], size=30, color=device["color"]),
                )
            )

        if phase not in {"dissolve", "settled"} or device_opacity > 0.18:
            controls.append(
                ft.Container(
                    left=x - 28 + wobble,
                    top=y,
                    width=56,
                    height=56,
                    bgcolor=ft.Colors.with_opacity(0.86 * device_opacity, ft.Colors.BLUE_GREY_900),
                    border=ft.border.all(1, device["color"]),
                    border_radius=8,
                    alignment=ft.alignment.center,
                    opacity=device_opacity,
                    rotate=spin,
                    content=ft.Icon(device["icon"], size=34, color=device["color"]),
                    shadow=ft.BoxShadow(
                        blur_radius=24,
                        color=ft.Colors.with_opacity(0.36 * device_opacity, device["color"]),
                        offset=ft.Offset(0, 12),
                    ),
                )
            )
            controls.append(
                ft.Container(
                    left=x - 38 + wobble,
                    top=y + 58,
                    width=76,
                    height=9,
                    bgcolor=ft.Colors.with_opacity(0.2 * device_opacity, device["color"]),
                    border_radius=9,
                    opacity=0.45,
                )
            )

        material_count = int(round(len(active_symbols) * max(0.18, dissolve)))
        if phase in {"sink", "dissolve", "settled"}:
            material_count = max(1, material_count)

        for particle_index, symbol in enumerate(active_symbols[:material_count]):
            amount = device["metals"][symbol]
            settled = phase == "settled"
            spread = (particle_index - 1.5) * (28 + viscosity * 44 + dissolve * 34)
            orbit = (
                0
                if settled
                else math.sin(sim_time * 2.8 + particle_index + seed) * (8 + dissolve * 16)
            )
            particle_x = x + spread + orbit - 12
            particle_y = (
                sink_base
                + (particle_index % 2) * 36
                + index * 4
                + dissolve * 46
                + (0 if settled else math.cos(sim_time * 2.2 + particle_index) * 8)
            )
            if settled:
                particle_y = min(stage_height - 105, particle_y + 26)
            controls.extend(
                build_particle(
                    symbol,
                    particle_x,
                    particle_y,
                    amount,
                    opacity=(
                        0.34
                        if settled
                        else max(0.02, min(0.42, dissolve * 0.42 - index * 0.01))
                    ),
                )
            )

        if phase == "settled":
            controls.append(
                ft.Container(
                    left=x - 88,
                    top=min(stage_height - 52, sink_base + 116),
                    width=176,
                    height=12,
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.CYAN_ACCENT_400),
                    border_radius=12,
                    opacity=0.42,
                )
            )

        controls.append(
            ft.Container(
                left=x - 52,
                top=min(stage_height - 34, sink_base + 136),
                width=104,
                content=ft.Text(
                    f"{device['name']} / {phase_label(phase)}",
                    size=11,
                    text_align=ft.TextAlign.CENTER,
                    color=ft.Colors.BLUE_GREY_100,
                    weight=ft.FontWeight.BOLD,
                ),
            )
        )
        return controls

    def total_by_symbol() -> dict[str, float]:
        return {
            symbol: sum(
                DEVICE_LIBRARY[device_key]["metals"][symbol] * quantity
                for device_key, quantity in tray_quantities.items()
            )
            for symbol in visible_symbols()
        }

    def render_palette() -> None:
        active_label.value = f"選択中: {DEVICE_LIBRARY[active_device_key]['name']}"
        palette.controls = [build_device_chip(device_key) for device_key in DEVICE_LIBRARY]

    def render_stats() -> None:
        totals = total_by_symbol()
        selected_total = sum(totals.values())
        device_count = sum(tray_quantities.values())
        moving_count = sum(1 for drop in drops if str(drop["phase"]) != "settled")
        settled_count = sum(1 for drop in drops if str(drop["phase"]) == "settled")
        water_energy = sum(
            float(impulse["strength"]) * max(0.0, 1 - float(impulse["age"]) / 2.4)
            for impulse in water_impulses
        )
        strongest = "-"
        if tray_quantities and visible_symbols():
            strongest_key = max(
                tray_quantities,
                key=lambda key: selected_total_amount(key) * tray_quantities[key],
            )
            strongest = DEVICE_LIBRARY[strongest_key]["name"]

        totals_panel.controls = [
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SCIENCE, color=ft.Colors.AMBER_300, size=22),
                    ft.Text("素材化ステータス", size=17, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Row(
                controls=[
                    metric_card("投入数", f"{device_count}", ft.Icons.TOUCH_APP, ft.Colors.CYAN_ACCENT_400),
                    metric_card("物質化", f"{selected_total:.3f}g", ft.Icons.SCIENCE, ft.Colors.AMBER_300),
                    metric_card("最大", strongest, ft.Icons.RADAR, ft.Colors.TEAL_ACCENT_400),
                ],
                spacing=8,
                wrap=True,
            ),
        ]

        max_total = max(totals.values(), default=0)
        stats_panel_width = min(390, max(320, int(stage_width * 0.31)))
        material_bar_width = max(112, min(190, stats_panel_width - 218))
        material_bars.controls = []
        for symbol, amount in totals.items():
            material_bars.controls.append(
                ft.Row(
                    controls=[
                        ft.Text(METALS[symbol]["name"], width=62, color=ft.Colors.BLUE_GREY_100),
                        ft.ProgressBar(
                            value=0 if max_total == 0 else amount / max_total,
                            color=METALS[symbol]["color"],
                            bgcolor=ft.Colors.BLUE_GREY_800,
                            width=material_bar_width,
                            bar_height=9,
                        ),
                        ft.Text(f"{amount:.3f}g", width=70, text_align=ft.TextAlign.RIGHT),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        if not material_bars.controls:
            material_bars.controls = [
                ft.Text("表示する金属を選んでください。", color=ft.Colors.BLUE_GREY_200)
            ]

        if tray_quantities:
            device_quantities.controls = [
                ft.Row(
                    controls=[
                        ft.Icon(DEVICE_LIBRARY[key]["icon"], color=DEVICE_LIBRARY[key]["color"], size=20),
                        ft.Text(DEVICE_LIBRARY[key]["name"], expand=True),
                        ft.IconButton(
                            icon=ft.Icons.REMOVE,
                            tooltip="減らす",
                            on_click=lambda event, device_key=key: set_quantity(device_key, -1),
                        ),
                        ft.Text(str(quantity), width=24, text_align=ft.TextAlign.CENTER),
                        ft.IconButton(
                            icon=ft.Icons.ADD,
                            tooltip="増やす",
                            on_click=lambda event, device_key=key: set_quantity(device_key, 1),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for key, quantity in sorted(tray_quantities.items())
            ]
        else:
            device_quantities.controls = [
                ft.Text(
                    "水面をクリックすると、選択中のデバイスがその場所に落ちます。",
                    color=ft.Colors.BLUE_GREY_200,
                )
            ]

        hint_text.value = (
            f"重力 {gravity:.1f} / 粘性 {viscosity:.1f}: "
            f"移動中 {moving_count} / 残留 {settled_count} / 水面エネルギー {water_energy:.1f}"
        )

    def metric_card(label: str, value: str, icon: str, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, color=color, size=20),
                        width=34,
                        height=34,
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.with_opacity(0.14, color),
                        border_radius=8,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(label, size=10, color=ft.Colors.BLUE_GREY_200),
                            ft.Text(value, size=14, weight=ft.FontWeight.BOLD),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=106,
            height=64,
            padding=9,
            bgcolor=ft.Colors.with_opacity(0.52, ft.Colors.BLUE_GREY_900),
            border=ft.border.all(1, ft.Colors.with_opacity(0.4, color)),
            border_radius=8,
        )

    def get_static_world_controls() -> list[ft.Control]:
        nonlocal static_world_key, static_world_controls
        key = (stage_width, stage_height, waterline)
        if static_world_key == key:
            return static_world_controls

        static_world_key = key
        static_world_controls = [
            ft.Container(
                left=0,
                top=0,
                width=stage_width,
                height=stage_height,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=[
                        ft.Colors.BLACK,
                        ft.Colors.BLUE_GREY_900,
                        ft.Colors.CYAN_900,
                    ],
                ),
            ),
            ft.Container(
                left=0,
                top=waterline,
                width=stage_width,
                height=2,
                bgcolor=ft.Colors.CYAN_ACCENT_400,
                opacity=0.8,
            ),
            ft.Container(
                left=0,
                top=waterline + 2,
                width=stage_width,
                height=stage_height - waterline,
                bgcolor=ft.Colors.with_opacity(0.17, ft.Colors.CYAN_ACCENT_400),
            ),
            ft.Container(
                left=36,
                top=waterline + 64,
                width=stage_width - 72,
                height=1,
                bgcolor=ft.Colors.CYAN_100,
                opacity=0.35,
            ),
            ft.Container(
                left=92,
                top=waterline + 158,
                width=stage_width - 184,
                height=1,
                bgcolor=ft.Colors.CYAN_100,
                opacity=0.22,
            ),
        ]
        return static_world_controls

    def get_water_animation_controls() -> list[ft.Control]:
        nonlocal wave_controls, glint_controls
        if not wave_controls:
            wave_controls = [
                ft.Container(
                    height=2,
                    bgcolor=ft.Colors.CYAN_100,
                    border_radius=2,
                )
                for _ in range(5)
            ]
        if not glint_controls:
            glint_controls = [
                ft.Container(
                    height=2,
                    bgcolor=ft.Colors.CYAN_ACCENT_400,
                    border_radius=3,
                )
                for _ in range(4)
            ]

        for wave_index, control in enumerate(wave_controls):
            wave_top = waterline + 22 + wave_index * 48
            wave_shift = math.sin(sim_time * (1.2 + wave_index * 0.08) + wave_index) * 26
            impulse_shift = 0.0
            impulse_opacity = 0.0
            for impulse in water_impulses:
                impulse_age = float(impulse["age"])
                decay = max(0.0, 1 - impulse_age / 2.4)
                phase = sim_time * 8 + wave_index - float(impulse["x"]) * 0.01
                impulse_shift += math.sin(phase) * float(impulse["strength"]) * 18 * decay
                impulse_opacity += float(impulse["strength"]) * 0.03 * decay
            control.left = -60 + wave_shift + (wave_index % 2) * stage_width * 0.22
            control.top = wave_top + math.cos(sim_time * 1.6 + wave_index) * 5 + impulse_shift
            control.width = stage_width * (0.48 + (wave_index % 3) * 0.16)
            control.opacity = min(0.35, 0.08 + (wave_index % 3) * 0.035 + impulse_opacity)

        for glint_index, control in enumerate(glint_controls):
            control.left = stage_width * (
                (glint_index * 0.17 + sim_time * 0.025) % 1.0
            )
            control.top = waterline - 5 + math.sin(sim_time * 2.4 + glint_index) * 4
            control.width = 54 + glint_index * 8
            control.opacity = 0.08 + (glint_index % 2) * 0.08

        return [*wave_controls, *glint_controls]

    def build_burst_controls() -> list[ft.Control]:
        controls: list[ft.Control] = []
        for burst in material_bursts:
            age = float(burst["age"])
            strength = float(burst["strength"])
            color = str(burst["color"])
            kind = str(burst["kind"])
            decay = max(0.0, 1 - age / 1.4)
            base_x = float(burst["x"])
            base_y = float(burst["y"])
            ring_size = 44 + age * (150 if kind == "material" else 210) * strength
            controls.append(
                ft.Container(
                    left=base_x - ring_size / 2,
                    top=base_y - ring_size / 2,
                    width=ring_size,
                    height=ring_size,
                    border=ft.border.all(1, color),
                    border_radius=ring_size / 2,
                    opacity=0.42 * decay,
                )
            )
            particle_count = 8 if kind == "material" else 5
            for burst_index in range(particle_count):
                angle = (math.pi * 2 / particle_count) * burst_index + age * 1.8
                radius = (22 + age * 96 * strength) * (0.65 + (burst_index % 3) * 0.16)
                size = 5 + (burst_index % 3) * 2
                controls.append(
                    ft.Container(
                        left=base_x + math.cos(angle) * radius,
                        top=base_y + math.sin(angle) * radius * 0.55,
                        width=size,
                        height=size,
                        bgcolor=ft.Colors.with_opacity(0.72, color),
                        border_radius=size,
                        opacity=0.62 * decay,
                    )
                )
            if kind == "settle":
                controls.append(
                    ft.Container(
                        left=base_x - 112 - age * 60,
                        top=min(stage_height - 52, base_y + 24),
                        width=224 + age * 120,
                        height=10,
                        bgcolor=ft.Colors.with_opacity(0.24 * decay, color),
                        border_radius=10,
                    )
                )
        return controls

    def build_world_controls() -> list[ft.Control]:
        controls: list[ft.Control] = [*get_static_world_controls()]
        controls.extend(get_water_animation_controls())

        for mark in click_marks:
            mark_age = float(mark["age"])
            for ring_index in range(2):
                ring_age = mark_age + ring_index * 0.12
                size = 26 + ring_age * 132
                opacity = max(0, 0.42 - ring_age * 0.55)
                controls.append(
                    ft.Container(
                        left=float(mark["x"]) - size / 2,
                        top=float(mark["y"]) - size / 2,
                        width=size,
                        height=size,
                        border=ft.border.all(1, ft.Colors.CYAN_ACCENT_400),
                        border_radius=size / 2,
                        opacity=opacity,
                    )
                )

        for impulse in water_impulses:
            impulse_age = float(impulse["age"])
            decay = max(0.0, 1 - impulse_age / 2.4)
            width = float(impulse["width"]) + impulse_age * 240
            controls.append(
                ft.Container(
                    left=float(impulse["x"]) - width / 2,
                    top=waterline - 14,
                    width=width,
                    height=28,
                    border=ft.border.all(1, ft.Colors.CYAN_ACCENT_400),
                    border_radius=28,
                    opacity=0.34 * decay,
                )
            )
            for echo_index in range(2):
                echo_width = width * (0.58 + echo_index * 0.34)
                controls.append(
                    ft.Container(
                        left=float(impulse["x"]) - echo_width / 2,
                        top=waterline + 24 + echo_index * 42 + impulse_age * 18,
                        width=echo_width,
                        height=8,
                        border=ft.border.all(1, ft.Colors.with_opacity(0.65, ft.Colors.CYAN_100)),
                        border_radius=8,
                        opacity=0.18 * decay,
                    )
                )

        if not drops:
            controls.append(
                ft.Container(
                    left=0,
                    top=waterline - 96,
                    width=stage_width,
                    alignment=ft.alignment.center,
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.WAVES, size=48, color=ft.Colors.CYAN_ACCENT_400),
                            ft.Text(
                                "水面をクリック、またはデバイスをドラッグ",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_GREY_100,
                            ),
                            ft.Text(
                                "落下した位置から反射し、沈みながら素材へ戻ります。",
                                color=ft.Colors.BLUE_GREY_300,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                )
            )

        active_symbols = visible_symbols()
        for index, drop in enumerate(drops):
            controls.extend(build_drop_controls(drop, index, active_symbols))
        controls.extend(build_burst_controls())

        return controls

    def render_stage() -> None:
        world_stack.controls = build_world_controls()
        stage_stack.controls = [water_drop_target, *build_overlay_controls()]

    def glass_panel(
        content: ft.Control,
        left: int,
        top: int,
        width: int,
        height: int | None = None,
    ) -> ft.Container:
        return ft.Container(
            left=left,
            top=top,
            width=width,
            height=height,
            content=content,
            padding=16,
            bgcolor=ft.Colors.with_opacity(0.72, "#10151D"),
            border=ft.border.all(1, ft.Colors.with_opacity(0.13, ft.Colors.WHITE)),
            border_radius=22,
            shadow=ft.BoxShadow(
                blur_radius=34,
                color=ft.Colors.with_opacity(0.44, ft.Colors.BLACK),
                offset=ft.Offset(0, 14),
            ),
        )

    def panel_heading(icon: str, title: str, color: str = ft.Colors.CYAN_ACCENT_400) -> ft.Row:
        return ft.Row(
            controls=[
                ft.Icon(icon, color=color, size=21),
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def visibility_button() -> ft.Container:
        return ft.Container(
            left=stage_width - 74,
            top=22,
            content=ft.IconButton(
                icon=ft.Icons.VISIBILITY_OFF if ui_visible else ft.Icons.VISIBILITY,
                icon_color=ft.Colors.CYAN_ACCENT_400,
                tooltip="UIを隠す" if ui_visible else "UIを表示",
                on_click=toggle_ui,
            ),
            width=50,
            height=50,
            alignment=ft.alignment.center,
            bgcolor=ft.Colors.with_opacity(0.58, ft.Colors.BLUE_GREY_900),
            border=ft.border.all(1, ft.Colors.with_opacity(0.34, ft.Colors.CYAN_ACCENT_400)),
            border_radius=8,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color=ft.Colors.with_opacity(0.34, ft.Colors.BLACK),
                offset=ft.Offset(0, 8),
            ),
        )

    def mini_status() -> ft.Container:
        return ft.Container(
            left=24,
            bottom=22,
            content=ft.Row(
                controls=[
                    ft.Icon(
                        DEVICE_LIBRARY[active_device_key]["icon"],
                        color=DEVICE_LIBRARY[active_device_key]["color"],
                        size=20,
                    ),
                    ft.Text(
                        f"{DEVICE_LIBRARY[active_device_key]['name']} / {sum(tray_quantities.values())}個",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text("Hキー: 表示切替  Zキー: 取り消す", size=11, color=ft.Colors.BLUE_GREY_200),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=ft.Colors.with_opacity(0.56, ft.Colors.BLUE_GREY_900),
            border=ft.border.all(1, ft.Colors.with_opacity(0.24, ft.Colors.CYAN_ACCENT_400)),
            border_radius=8,
        )

    def build_overlay_controls() -> list[ft.Control]:
        if not ui_visible:
            return [back_to_explorer_button(), visibility_button(), mini_status()]

        if stage_width < 700:
            totals = total_by_symbol()
            material_total = sum(totals.values())
            device_total = sum(tray_quantities.values())
            mobile_device_row = ft.Row(
                controls=[build_device_chip(device_key) for device_key in DEVICE_LIBRARY],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
            header = glass_panel(
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            icon_color=ft.Colors.CYAN_ACCENT_400,
                            tooltip="探索画面へ戻る",
                            on_click=leave_lab,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.WAVES, color="#071015", size=20),
                            width=38,
                            height=38,
                            alignment=ft.alignment.center,
                            bgcolor=ft.Colors.CYAN_ACCENT_400,
                            border_radius=12,
                        ),
                        ft.Column(
                            [
                                ft.Text("fukucycle", size=18, weight=ft.FontWeight.BOLD),
                                ft.Text("都市鉱山・素材回収ラボ", size=9, color=ft.Colors.BLUE_GREY_300),
                            ],
                            spacing=0,
                            expand=True,
                        ),
                        ft.Container(
                            content=ft.IconButton(
                                icon=ft.Icons.RECYCLING,
                                icon_color=ft.Colors.CYAN_ACCENT_400,
                                tooltip="近くの回収スポット",
                                on_click=show_collection_points,
                            ),
                            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                            border_radius=14,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                ),
                16,
                16,
                stage_width - 32,
            )
            status = ft.Container(
                left=16,
                top=92,
                width=stage_width - 32,
                content=ft.Row(
                    [
                        ft.Column([ft.Text("回収素材", size=9, color=ft.Colors.BLUE_GREY_400),
                                   ft.Text(f"{material_total:.3f} g", size=24, weight=ft.FontWeight.BOLD)], spacing=0),
                        ft.Container(width=1, height=34, bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.WHITE)),
                        ft.Column([ft.Text("投入数", size=9, color=ft.Colors.BLUE_GREY_400),
                                   ft.Text(f"{device_total}", size=24, weight=ft.FontWeight.BOLD)], spacing=0),
                        ft.Container(expand=True),
                        ft.Container(
                            content=ft.IconButton(icon=ft.Icons.ADD, icon_color="#071015", on_click=drop_active_device),
                            bgcolor=ft.Colors.CYAN_ACCENT_400,
                            border_radius=16,
                        ),
                    ],
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=18, vertical=12),
                bgcolor=ft.Colors.with_opacity(0.76, "#10151D"),
                border=ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE)),
                border_radius=20,
            )
            dock_height = 196
            dock = ft.Container(
                left=12,
                top=stage_height - dock_height - 12,
                width=stage_width - 24,
                height=dock_height,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Column([ft.Text("デバイスを選択", size=15, weight=ft.FontWeight.BOLD),
                                           ft.Text("タップして水面にドロップ", size=10, color=ft.Colors.BLUE_GREY_300)], spacing=0, expand=True),
                                ft.IconButton(icon=ft.Icons.UNDO, icon_color=ft.Colors.BLUE_GREY_200, on_click=undo_last_drop),
                                ft.IconButton(icon=ft.Icons.TUNE, icon_color=ft.Colors.CYAN_ACCENT_400, on_click=toggle_ui),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        mobile_device_row,
                    ],
                    spacing=10,
                ),
                padding=16,
                bgcolor=ft.Colors.with_opacity(0.88, "#10151D"),
                border=ft.border.all(1, ft.Colors.with_opacity(0.14, ft.Colors.WHITE)),
                border_radius=28,
                shadow=ft.BoxShadow(blur_radius=40, color=ft.Colors.with_opacity(0.55, ft.Colors.BLACK), offset=ft.Offset(0, 16)),
            )
            return [header, status, dock]

        top_bar_width = max(620, stage_width - 116)
        bottom_dock_width = min(stage_width - 48, 1080)
        bottom_dock_left = int((stage_width - bottom_dock_width) / 2)
        bottom_dock_top = max(waterline + 118, stage_height - 218)
        stats_width = min(360, max(310, int(stage_width * 0.28)))
        stats_left = stage_width - stats_width - 24
        metal_checks = ft.Row(
            controls=[
                ft.Checkbox(
                    label=METALS[symbol]["name"],
                    value=symbol in selected_symbols,
                    on_change=lambda event, metal=symbol: toggle_symbol(
                        metal, event.control.value
                    ),
                )
                for symbol in METALS
            ],
            spacing=0,
            wrap=True,
        )

        return [
            visibility_button(),
            glass_panel(
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            icon_color=ft.Colors.CYAN_ACCENT_400,
                            tooltip="探索画面へ戻る",
                            on_click=leave_lab,
                        ),
                        ft.Icon(ft.Icons.WAVES, color=ft.Colors.CYAN_ACCENT_400, size=24),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "都市鉱山 素材ラボ",
                                    size=20,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    "水面をクリックして、素材に戻る動きを見る。",
                                    size=11,
                                    color=ft.Colors.BLUE_GREY_200,
                                ),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                        active_device_dropdown,
                        ft.FilledButton(
                            text=f"回収スポット  {len(collection_points)}",
                            icon=ft.Icons.RECYCLING,
                            tooltip="現在地の近くで回収できる場所を探す",
                            on_click=show_collection_points,
                            style=ft.ButtonStyle(
                                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.CYAN_ACCENT_400),
                                color=ft.Colors.CYAN_50,
                                shape=ft.RoundedRectangleBorder(radius=12),
                            ),
                        ),
                        ft.Row(
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.ADD_CIRCLE,
                                    icon_color=ft.Colors.CYAN_ACCENT_400,
                                    tooltip="選択中を中央に落とす",
                                    on_click=drop_active_device,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.AUTO_AWESOME,
                                    icon_color=ft.Colors.AMBER_300,
                                    tooltip="サンプル投入",
                                    on_click=load_sample,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.UNDO,
                                    icon_color=ft.Colors.TEAL_ACCENT_400,
                                    tooltip="最後の投入を戻す",
                                    on_click=undo_last_drop,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CLEANING_SERVICES,
                                    icon_color=ft.Colors.LIGHT_BLUE_200,
                                    tooltip="残留したアイテムだけ消す",
                                    on_click=clear_settled,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CLEAR,
                                    icon_color=ft.Colors.BLUE_GREY_200,
                                    tooltip="全クリア",
                                    on_click=clear_all,
                                ),
                            ],
                            spacing=2,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                24,
                20,
                top_bar_width,
            ),
            glass_panel(
                ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                panel_heading(ft.Icons.INVENTORY_2, "デバイス選択"),
                                active_label,
                                ft.Text(
                                    "スペースキー: 投入 / 1〜8: 選択 / Hキー: 非表示",
                                    size=11,
                                    color=ft.Colors.BLUE_GREY_200,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        palette,
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Row(
                                            controls=[
                                                ft.Icon(
                                                    ft.Icons.TUNE,
                                                    color=ft.Colors.AMBER_300,
                                                    size=18,
                                                ),
                                                ft.Text(
                                                    "金属フィルター",
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                            ],
                                            spacing=6,
                                        ),
                                        metal_checks,
                                    ],
                                    spacing=4,
                                    expand=True,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Row(
                                            controls=[
                                                ft.Text(
                                                    "重力",
                                                    width=34,
                                                    color=ft.Colors.BLUE_GREY_200,
                                                ),
                                                gravity_slider,
                                            ],
                                            spacing=6,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        ft.Row(
                                            controls=[
                                                ft.Text(
                                                    "粘性",
                                                    width=34,
                                                    color=ft.Colors.BLUE_GREY_200,
                                                ),
                                                viscosity_slider,
                                                ft.IconButton(
                                                    icon=ft.Icons.RESTART_ALT,
                                                    icon_color=ft.Colors.BLUE_GREY_100,
                                                    tooltip="物理値をリセット",
                                                    on_click=reset_physics,
                                                ),
                                            ],
                                            spacing=6,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                    ],
                                    spacing=0,
                                ),
                            ],
                            spacing=18,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                    ],
                    spacing=8,
                ),
                bottom_dock_left,
                bottom_dock_top,
                bottom_dock_width,
            ),
            glass_panel(
                ft.Column(
                    controls=[
                        totals_panel,
                        hint_text,
                        ft.Divider(),
                        panel_heading(ft.Icons.BAR_CHART, "金属量", ft.Colors.TEAL_ACCENT_400),
                        material_bars,
                        ft.Divider(),
                        device_quantities,
                    ],
                    spacing=10,
                ),
                stats_left,
                94,
                stats_width,
            ),
        ]

    def render() -> None:
        render_palette()
        render_stats()
        render_stage()
        if page.controls:
            page.update()

    def render_stage_only() -> None:
        world_stack.controls = build_world_controls()
        if page.controls:
            page.update()

    def accept_drop(event: ft.DragTargetEvent) -> None:
        source = page.get_control(event.src_id) or page.get_control(str(event.src_id))
        if source is not None:
            add_drop(
                source.data,
                event.x if event.x is not None else fallback_x(),
                event.y if event.y is not None else 90,
            )

    def tap_world(event: ft.ContainerTapEvent) -> None:
        add_drop(
            active_device_key,
            event.local_x if event.local_x is not None else fallback_x(),
            event.local_y if event.local_y is not None else 90,
        )

    def handle_keyboard(event: ft.KeyboardEvent) -> None:
        key = (event.key or "").lower()
        if key in {"h", "escape"}:
            toggle_ui()
        elif key in {" ", "space"}:
            drop_active_device()
        elif key == "z":
            undo_last_drop()
        elif key == "x":
            clear_settled()
        elif key == "c":
            clear_all()
        elif key == "s":
            load_sample()
        elif key == "r":
            reset_physics()
        elif key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(device_keys):
                select_device(device_keys[index])

    gravity_slider.on_change = update_gravity
    viscosity_slider.on_change = update_viscosity
    active_device_dropdown.on_change = change_active_device
    water_drop_target.on_accept = accept_drop
    world_container.on_tap_down = tap_world
    page.on_keyboard_event = handle_keyboard
    page.on_resized = resize_stage
    resize_stage()
    render()

    page.add(stage_container)
    page.run_thread(physics_loop)
    page.update()


def recovery_go_app(page: ft.Page) -> None:
    """Location-game inspired recycling explorer built with native Flet controls."""

    page.title = "fukucycle"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#120D0B"
    page.padding = 0
    page.theme = ft.Theme(
        color_scheme_seed="#D6A06C",
        visual_density=ft.VisualDensity.COMFORTABLE,
    )
    try:
        page.window.width = 430
        page.window.height = 860
    except AttributeError:
        pass

    users_file = Path(__file__).with_name("m3ow_users.json")
    try:
        user_accounts = json.loads(users_file.read_text(encoding="utf-8")) if users_file.exists() else {}
        if not isinstance(user_accounts, dict):
            user_accounts = {}
    except (OSError, json.JSONDecodeError):
        user_accounts = {}
    try:
        authenticated_username = page.client_storage.get("m3ow.auth_user")
    except Exception:
        authenticated_username = None
    if authenticated_username not in user_accounts:
        authenticated_username = None

    spots = [
        {"name": "丸の内リサイクルポート", "kind": "小型家電", "lat": 35.6798, "lon": 139.7638, "distance": 0, "x": .23, "y": .27, "color": "#D6A06C", "visited": False, "xp": 80},
        {"name": "京橋バッテリーステーション", "kind": "バッテリー", "lat": 35.6768, "lon": 139.7701, "distance": 0, "x": .70, "y": .22, "color": "#FFD86B", "visited": False, "xp": 120},
        {"name": "有楽町デバイス回収所", "kind": "スマホ・PC", "lat": 35.6751, "lon": 139.7634, "distance": 0, "x": .72, "y": .57, "color": "#73D7FF", "visited": False, "xp": 100},
        {"name": "日本橋リユースラボ", "kind": "ゲーム機", "lat": 35.6825, "lon": 139.7744, "distance": 0, "x": .18, "y": .63, "color": "#BFA5FF", "visited": False, "xp": 150},
    ]
    data_file = Path(__file__).with_name("collection_points.json")
    columns_file = Path(__file__).with_name("urban_mine_columns.json")
    state_file = Path(__file__).with_name("m3ow_state.json")
    current_position = {"lat": 35.6812, "lon": 139.7671, "real": False}
    map_zoom = 15
    location_label = ft.Text("位置ボタンで現在地を取得", size=12, weight=ft.FontWeight.BOLD)
    geolocator = ft.Geolocator()
    page.overlay.append(geolocator)

    if data_file.exists():
        try:
            saved = json.loads(data_file.read_text(encoding="utf-8"))
            if isinstance(saved, list):
                spots.extend(item for item in saved if isinstance(item, dict))
        except (OSError, json.JSONDecodeError):
            pass
    default_community_columns = [
        {"title": "古いスマホは小さな鉱山", "body": "引き出しに眠るスマホにも金・銀・パラジウムが含まれています。まずはデータを消去して、認定された回収場所へ持っていきましょう。", "author": "fukucycle編集部", "category": "はじめて", "likes": 12},
        {"title": "バッテリーを安全に手放すコツ", "body": "膨張や破損がある電池は通常の回収ボックスに入れず、自治体や販売店へ状態を伝えて相談することが大切です。", "author": "eco_taro", "category": "安全", "likes": 8},
    ]
    with COMMUNITY_COLUMNS_LOCK:
        if not COMMUNITY_COLUMNS:
            loaded_columns = default_community_columns
            if columns_file.exists():
                try:
                    saved_columns = json.loads(columns_file.read_text(encoding="utf-8"))
                    if isinstance(saved_columns, list):
                        loaded_columns = [item for item in saved_columns if isinstance(item, dict)]
                except (OSError, json.JSONDecodeError):
                    pass
            COMMUNITY_COLUMNS.extend(loaded_columns)
        community_columns = COMMUNITY_COLUMNS
    xp = 0
    recycled = 0
    selected_spot: dict | None = None
    active_tab = "map"
    active_spot_filter = "すべて"
    nearby_query = ""
    user_id = (hashlib.sha256(authenticated_username.encode()).hexdigest()[:8]
               if authenticated_username else uuid.uuid4().hex[:8])
    user_name = (user_accounts.get(authenticated_username, {}).get("display_name")
                 if authenticated_username else None) or f"Explorer {user_id[:4].upper()}"
    user_color = ["#FF7A8A", "#73D7FF", "#FFD86B", "#BFA5FF", "#D6A06C"][int(user_id[:2], 16) % 5]
    sharing_location = False
    presence_signature = ""
    last_content_revision = SERVER_CONTENT_REVISION
    session_active = True
    session_generation = 0
    presence_thread_started = False
    online_count_text = ft.Text("1 ONLINE", size=9, color="#D6A06C", weight=ft.FontWeight.BOLD)
    sheet = ft.Container()
    root = ft.Stack(expand=True)

    def current_level() -> int:
        return xp // 1000

    if authenticated_username and state_file.exists():
        try:
            with CONTENT_STORAGE_LOCK:
                all_saved_states = json.loads(state_file.read_text(encoding="utf-8"))
            if not isinstance(all_saved_states, dict):
                all_saved_states = {}
            accounts_state = all_saved_states.get("accounts", {})
            saved_state = accounts_state.get(authenticated_username, {}) if isinstance(accounts_state, dict) else {}
            xp = int(saved_state.get("xp", xp))
            recycled = int(saved_state.get("recycled", recycled))
            active_spot_filter = saved_state.get("filter", active_spot_filter)
            spot_states = saved_state.get("spots", {})
            for spot in spots:
                state = spot_states.get(spot["name"], {})
                spot["favorite"] = bool(state.get("favorite", spot.get("favorite", False)))
                spot["visited"] = bool(state.get("visited", spot.get("visited", False)))
                spot["last_checkin"] = state.get("last_checkin", spot.get("last_checkin"))
                spot["visit_count"] = int(state.get("visit_count", 1 if spot.get("visited") else 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    # Browser/client storage keeps daily check-ins separate for each user when
    # multiple people connect to the same temporary server.
    try:
        client_state = (page.client_storage.get(f"m3ow.user_state.{authenticated_username}")
                        if authenticated_username else None)
        if isinstance(client_state, dict):
            xp = int(client_state.get("xp", xp))
            recycled = int(client_state.get("recycled", recycled))
            for spot in spots:
                state = client_state.get("spots", {}).get(spot["name"], {})
                spot["favorite"] = bool(state.get("favorite", spot.get("favorite", False)))
                spot["visited"] = bool(state.get("visited", spot.get("visited", False)))
                spot["last_checkin"] = state.get("last_checkin", spot.get("last_checkin"))
                spot["visit_count"] = int(state.get("visit_count", spot.get("visit_count", 0)))
    except Exception:
        pass
    user_color = ["#FF7A8A", "#73D7FF", "#FFD86B", "#BFA5FF", "#D6A06C"][int(user_id[:2], 16) % 5]

    def save_app_state() -> None:
        payload = {
            "xp": xp,
            "recycled": recycled,
            "filter": active_spot_filter,
            "spots": {spot["name"]: {"favorite": bool(spot.get("favorite")),
                                      "visited": bool(spot.get("visited")),
                                      "last_checkin": spot.get("last_checkin"),
                                      "visit_count": int(spot.get("visit_count", 0))} for spot in spots},
        }
        try:
            if authenticated_username:
                with CONTENT_STORAGE_LOCK:
                    try:
                        all_saved_states = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
                    except (OSError, json.JSONDecodeError):
                        all_saved_states = {}
                    accounts_state = all_saved_states.get("accounts")
                    if not isinstance(accounts_state, dict):
                        accounts_state = {}
                    accounts_state[authenticated_username] = payload
                    state_file.write_text(
                        json.dumps({"accounts": accounts_state}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
        except (OSError, TypeError):
            pass
        try:
            if authenticated_username:
                page.client_storage.set(f"m3ow.user_state.{authenticated_username}", payload)
        except Exception:
            pass

    def update_presence() -> None:
        now = time.time()
        with ONLINE_USERS_LOCK:
            ONLINE_USERS[user_id] = {
                "id": user_id,
                "name": user_name,
                "color": user_color,
                "lat": current_position["lat"],
                "lon": current_position["lon"],
                "sharing": sharing_location,
                "last_seen": now,
            }
            expired = [key for key, value in ONLINE_USERS.items()
                       if now - float(value.get("last_seen", 0)) > ONLINE_USER_TTL_SECONDS]
            for key in expired:
                ONLINE_USERS.pop(key, None)

    def online_users_snapshot() -> list[dict]:
        now = time.time()
        with ONLINE_USERS_LOCK:
            return [dict(value) for value in ONLINE_USERS.values()
                    if now - float(value.get("last_seen", 0)) <= ONLINE_USER_TTL_SECONDS]

    def disconnect_session(event: ft.ControlEvent | None = None) -> None:
        nonlocal session_active, session_generation, presence_thread_started
        session_active = False
        session_generation += 1
        presence_thread_started = False
        with ONLINE_USERS_LOCK:
            ONLINE_USERS.pop(user_id, None)

    def announce_content_change() -> None:
        global SERVER_CONTENT_REVISION
        with ONLINE_USERS_LOCK:
            SERVER_CONTENT_REVISION += 1

    def sync_shared_content() -> None:
        if data_file.exists():
            try:
                shared_spots = json.loads(data_file.read_text(encoding="utf-8"))
                if isinstance(shared_spots, list):
                    spots[:] = [spot for spot in spots if not spot.get("user_added")]
                    spots.extend(item for item in shared_spots if isinstance(item, dict))
                    refresh_distances()
            except (OSError, json.JSONDecodeError):
                pass
        if columns_file.exists():
            try:
                shared_columns = json.loads(columns_file.read_text(encoding="utf-8"))
                if isinstance(shared_columns, list):
                    with COMMUNITY_COLUMNS_LOCK:
                        community_columns[:] = [item for item in shared_columns if isinstance(item, dict)]
            except (OSError, json.JSONDecodeError):
                pass

    def presence_loop(generation: int) -> None:
        nonlocal presence_signature, last_content_revision
        while session_active and generation == session_generation:
            update_presence()
            users = online_users_snapshot()
            signature = "|".join(sorted(f"{item['id']}:{item['sharing']}:{item['lat']:.4f}:{item['lon']:.4f}" for item in users))
            if signature != presence_signature:
                presence_signature = signature
                online_count_text.value = f"{len(users)} ONLINE"
                if page.controls:
                    render()
            if last_content_revision != SERVER_CONTENT_REVISION:
                last_content_revision = SERVER_CONTENT_REVISION
                sync_shared_content()
                if page.controls:
                    render()
            time.sleep(3)

    def distance_m(lat: float, lon: float) -> int:
        lat1, lon1 = math.radians(current_position["lat"]), math.radians(current_position["lon"])
        lat2, lon2 = math.radians(lat), math.radians(lon)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return int(6371000 * 2 * math.asin(math.sqrt(value)))

    def bearing_to(lat: float, lon: float) -> float:
        lat1, lat2 = math.radians(current_position["lat"]), math.radians(lat)
        delta_lon = math.radians(lon - current_position["lon"])
        y = math.sin(delta_lon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def compass_name(bearing: float) -> str:
        names = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]
        return names[int((bearing + 22.5) // 45) % 8]

    def format_distance(distance: int) -> str:
        return f"{distance} m" if distance < 1000 else f"{distance / 1000:.1f} km"

    def direction_indicator(spot: dict, compact: bool = False) -> ft.Container:
        bearing = bearing_to(float(spot.get("lat", current_position["lat"])),
                             float(spot.get("lon", current_position["lon"])))
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ARROW_UPWARD, size=19 if compact else 24, color="#73D7FF",
                        rotate=ft.Rotate(math.radians(bearing))),
                ft.Column([
                    ft.Text(compass_name(bearing), size=10, color="#BCAEA4"),
                    ft.Text(format_distance(int(spot["distance"])), size=12 if compact else 15,
                            weight=ft.FontWeight.BOLD),
                ], spacing=0),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=9, vertical=6),
            bgcolor="#1A2D34",
            border_radius=14,
        )

    def refresh_distances() -> None:
        for spot in spots:
            spot["distance"] = distance_m(float(spot.get("lat", current_position["lat"])), float(spot.get("lon", current_position["lon"])))

    refresh_distances()

    def dimensions() -> tuple[int, int]:
        width = int(page.width or getattr(page.window, "width", 430) or 430)
        height = int(page.height or getattr(page.window, "height", 860) or 860)
        return max(360, width), max(680, height)

    def toast(message: str) -> None:
        page.snack_bar = ft.SnackBar(
            content=ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, color="#D6A06C"), ft.Text(message, weight=ft.FontWeight.BOLD)]),
            bgcolor="#2B1D17",
            behavior=ft.SnackBarBehavior.FLOATING,
            margin=20,
        )
        page.snack_bar.open = True
        page.update()

    def locate_me(event: ft.ControlEvent | None = None) -> None:
        try:
            permission = geolocator.request_permission()
            position = geolocator.get_current_position(
                accuracy=ft.GeolocatorPositionAccuracy.HIGH,
                wait_timeout=20,
            )
            if position is None:
                raise RuntimeError("位置を取得できませんでした")
            current_position.update({"lat": float(position.latitude), "lon": float(position.longitude), "real": True})
            location_label.value = f"現在地  {position.latitude:.4f}, {position.longitude:.4f}"
            refresh_distances()
            toast("現在地を更新しました")
            render()
        except Exception:
            location_label.value = "位置情報を許可してください"
            toast("位置情報を取得できません。端末の設定を確認してください")

    def search_places(event: ft.ControlEvent | None = None) -> None:
        query = ft.TextField(label="場所・住所を検索", prefix_icon=ft.Icons.SEARCH, autofocus=True)
        results = ft.Column(spacing=8, height=300, scroll=ft.ScrollMode.AUTO)
        progress = ft.ProgressRing(width=22, height=22, visible=False)
        dialog = ft.AlertDialog(modal=True, title=ft.Text("場所を検索", weight=ft.FontWeight.BOLD))

        def choose_result(item: dict) -> None:
            current_position.update({"lat": float(item["lat"]), "lon": float(item["lon"]), "real": False})
            location_label.value = item["display_name"].split(",")[0]
            refresh_distances()
            dialog.open = False
            render()

        def run_search(search_event: ft.ControlEvent | None = None) -> None:
            text = (query.value or "").strip()
            if not text:
                return
            progress.visible = True
            results.controls = []
            page.update()
            try:
                params = urllib.parse.urlencode({"q": text, "format": "jsonv2", "limit": 6, "accept-language": "ja"})
                request = urllib.request.Request(
                    f"https://nominatim.openstreetmap.org/search?{params}",
                    headers={"User-Agent": "fukucycle/1.0"},
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    found = json.loads(response.read().decode("utf-8"))
                results.controls = [
                    ft.Container(
                        content=ft.Row([ft.Icon(ft.Icons.PLACE, color="#D6A06C"),
                                        ft.Text(item["display_name"], size=12, expand=True),
                                        ft.Icon(ft.Icons.CHEVRON_RIGHT)], spacing=8),
                        padding=12, bgcolor="#2B1D17", border_radius=14,
                        on_click=lambda e, value=item: choose_result(value),
                    ) for item in found
                ] or [ft.Text("該当する場所がありません")]
            except Exception:
                results.controls = [ft.Text("検索サービスに接続できませんでした")]
            progress.visible = False
            page.update()

        query.on_submit = run_search
        dialog.content = ft.Container(
            ft.Column([ft.Row([query, ft.IconButton(ft.Icons.SEARCH, on_click=run_search), progress]), results], tight=True),
            width=min(420, dimensions()[0] - 64),
        )
        dialog.actions = [ft.TextButton("閉じる", on_click=lambda e: setattr(dialog, "open", False) or page.update())]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def spot_url(spot: dict) -> str:
        lat = float(spot.get("lat", current_position["lat"]))
        lon = float(spot.get("lon", current_position["lon"]))
        return f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=18/{lat:.6f}/{lon:.6f}"

    def open_directions(spot: dict) -> None:
        lat = float(spot.get("lat", current_position["lat"]))
        lon = float(spot.get("lon", current_position["lon"]))
        page.launch_url(
            f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_foot&route="
            f"{current_position['lat']:.6f},{current_position['lon']:.6f};{lat:.6f},{lon:.6f}"
        )

    def share_spot(spot: dict) -> None:
        link = spot_url(spot)
        message = f"{spot['name']}（{spot['kind']}）\n{link}"
        dialog = ft.AlertDialog(modal=True, title=ft.Text("場所を共有"), content=ft.Column([
            ft.Text(spot["name"], weight=ft.FontWeight.BOLD),
            ft.Text(link, size=11, color="#73D7FF", selectable=True),
        ], width=min(380, dimensions()[0] - 64), tight=True), actions=[])

        def copy_link(e) -> None:
            page.set_clipboard(message)
            dialog.open = False
            toast("共有リンクをコピーしました")

        dialog.actions = [
            ft.TextButton("閉じる", on_click=lambda e: setattr(dialog, "open", False) or page.update()),
            ft.OutlinedButton("メール", icon=ft.Icons.MAIL,
                              on_click=lambda e: page.launch_url("mailto:?subject=" + urllib.parse.quote(spot["name"]) + "&body=" + urllib.parse.quote(message))),
            ft.FilledButton("リンクをコピー", icon=ft.Icons.CONTENT_COPY, on_click=copy_link),
        ]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def show_profile(event: ft.ControlEvent | None = None) -> None:
        name_field = ft.TextField(label="表示名", value=user_name, dense=True)
        share_switch = ft.Switch(label="地図上で位置を共有", value=sharing_location,
                                 active_color="#D6A06C")
        dialog = ft.AlertDialog(
            title=ft.Text("マイプロフィール"),
            content=ft.Column([ft.Icon(ft.Icons.ECO, size=54, color="#D6A06C"),
                               ft.Text(f"LEVEL {current_level()}", size=22, weight=ft.FontWeight.BOLD),
                               ft.Text(f"{xp} XP・回収 {recycled}件", color="#BCAEA4"),
                               name_field,
                               share_switch,
                               ft.Text("共有中は同じサーバーに接続したユーザーへ概算位置が表示されます。",
                                       size=10, color="#BCAEA4")],
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            actions=[],
        )

        def apply_profile(apply_event: ft.ControlEvent) -> None:
            nonlocal user_name, sharing_location
            user_name = (name_field.value or user_name).strip()
            sharing_location = bool(share_switch.value)
            update_presence()
            dialog.open = False
            toast("プロフィールと位置共有を更新しました")
            render()

        def logout(logout_event: ft.ControlEvent) -> None:
            nonlocal authenticated_username, sharing_location
            save_app_state()
            sharing_location = False
            disconnect_session()
            authenticated_username = None
            try:
                page.client_storage.remove("m3ow.auth_user")
            except Exception:
                pass
            dialog.open = False
            page.on_resized = None
            page.on_keyboard_event = None
            page.on_disconnect = None
            show_auth_screen()

        dialog.actions = [ft.TextButton("ログアウト", icon=ft.Icons.LOGOUT, on_click=logout),
                          ft.TextButton("キャンセル", on_click=lambda e: setattr(dialog, "open", False) or page.update()),
                          ft.FilledButton("保存", icon=ft.Icons.SAVE, on_click=apply_profile)]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def glass(content: ft.Control, padding: int = 14, radius: int = 22) -> ft.Container:
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=ft.Colors.with_opacity(.88, "#241813"),
            border=ft.border.all(1, ft.Colors.with_opacity(.10, ft.Colors.WHITE)),
            border_radius=radius,
            shadow=ft.BoxShadow(blur_radius=28, color=ft.Colors.with_opacity(.32, ft.Colors.BLACK), offset=ft.Offset(0, 12)),
        )

    def close_sheet(event: ft.ControlEvent | None = None) -> None:
        nonlocal selected_spot
        selected_spot = None
        render()

    def checked_in_today(spot: dict) -> bool:
        return spot.get("last_checkin") == date.today().isoformat()

    def visit_spot(event: ft.ControlEvent | None = None) -> None:
        nonlocal xp, recycled
        if selected_spot is None:
            return
        if selected_spot["distance"] > 150:
            toast(f"あと {selected_spot['distance'] - 150}m 近づくとチェックインできます")
            return
        if checked_in_today(selected_spot):
            toast("この回収場には本日チェックイン済みです。明日また来てね！")
            return
        selected_spot["visited"] = True
        selected_spot["last_checkin"] = date.today().isoformat()
        selected_spot["visit_count"] = int(selected_spot.get("visit_count", 0)) + 1
        xp += selected_spot["xp"]
        recycled += 1
        save_app_state()
        toast(f"デイリーチェックイン！ +{selected_spot['xp']} XP")
        render()

    def open_spot(spot: dict) -> None:
        nonlocal selected_spot
        selected_spot = spot
        render()

    def set_spot_filter(value: str) -> None:
        nonlocal active_spot_filter, selected_spot
        active_spot_filter = value
        selected_spot = None
        save_app_state()
        render()

    def visible_spots() -> list[dict]:
        if active_spot_filter == "お気に入り":
            return [spot for spot in spots if spot.get("favorite")]
        if active_spot_filter == "すべて":
            return spots
        return [spot for spot in spots if spot["kind"] == active_spot_filter]

    def toggle_favorite(spot: dict) -> None:
        spot["favorite"] = not spot.get("favorite", False)
        save_app_state()
        toast("お気に入りに追加しました" if spot["favorite"] else "お気に入りから外しました")
        render()

    def scan_nearby(event: ft.ControlEvent | None = None) -> None:
        candidates = visible_spots()
        if not candidates:
            toast("この条件のスポットは見つかりませんでした")
            return
        nearest = min(candidates, key=lambda item: item["distance"])
        open_spot(nearest)
        toast(f"{compass_name(bearing_to(nearest['lat'], nearest['lon']))}に {format_distance(nearest['distance'])} — 発見！")

    def spot_pin(spot: dict, map_width: int, map_height: int) -> ft.Container:
        near = spot["distance"] <= 150
        bearing = bearing_to(float(spot["lat"]), float(spot["lon"]))
        return ft.Container(
            left=int(map_width * spot["x"]) - 38,
            top=int(map_height * spot["y"]) - 35,
            content=ft.Column([
                ft.Stack([
                    ft.Container(width=54, height=54, bgcolor=ft.Colors.with_opacity(.18, spot["color"]), border_radius=27),
                    ft.Container(
                        left=7, top=7, width=40, height=40,
                        content=ft.Icon(ft.Icons.RECYCLING, color="#120D0B", size=21),
                        alignment=ft.alignment.center,
                        bgcolor=spot["color"],
                        border=ft.border.all(3, "#FFF9F1" if near else "#23342D"),
                        border_radius=20,
                        shadow=ft.BoxShadow(blur_radius=18 if near else 8, color=ft.Colors.with_opacity(.55, spot["color"])),
                    ),
                    ft.Container(
                        left=35, top=1, width=15, height=15,
                        bgcolor="#D6A06C" if checked_in_today(spot) else "#FF6D7A",
                        border=ft.border.all(2, "#10201A"),
                        border_radius=8,
                    ),
                ], width=54, height=54),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ARROW_UPWARD, size=16, color="#73D7FF",
                                rotate=ft.Rotate(math.radians(bearing))),
                        ft.Text(compass_name(bearing), size=9, color="#BCAEA4"),
                        ft.Text(format_distance(int(spot["distance"])), size=10, weight=ft.FontWeight.BOLD),
                    ], spacing=3),
                    padding=ft.padding.symmetric(horizontal=7, vertical=4),
                    bgcolor=ft.Colors.with_opacity(.94, "#241813"),
                    border=ft.border.all(1, ft.Colors.with_opacity(.16, ft.Colors.WHITE)),
                    border_radius=12,
                    shadow=ft.BoxShadow(blur_radius=8, color="#44000000"),
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=-3),
            on_click=lambda e, s=spot: open_spot(s),
        )

    def map_background(width: int, height: int) -> list[ft.Control]:
        center_lat, center_lon = current_position["lat"], current_position["lon"]
        tile_size = 256
        tile_count = 2 ** map_zoom

        def world_pixel(lat: float, lon: float) -> tuple[float, float]:
            safe_lat = max(-85.0511, min(85.0511, lat))
            x = (lon + 180.0) / 360.0 * tile_count * tile_size
            lat_rad = math.radians(safe_lat)
            y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * tile_count * tile_size
            return x, y

        center_x, center_y = world_pixel(center_lat, center_lon)
        first_tile_x = math.floor((center_x - width / 2) / tile_size)
        first_tile_y = math.floor((center_y - height / 2) / tile_size)
        last_tile_x = math.floor((center_x + width / 2) / tile_size) + 1
        last_tile_y = math.floor((center_y + height / 2) / tile_size) + 1
        controls: list[ft.Control] = [ft.Container(width=width, height=height, bgcolor="#DCE8DF")]
        for tile_x in range(first_tile_x, last_tile_x + 1):
            for tile_y in range(first_tile_y, last_tile_y + 1):
                if 0 <= tile_y < tile_count:
                    controls.append(
                        ft.Image(
                            src=f"https://tile.openstreetmap.org/{map_zoom}/{tile_x % tile_count}/{tile_y}.png",
                            left=width / 2 + tile_x * tile_size - center_x,
                            top=height / 2 + tile_y * tile_size - center_y,
                            width=tile_size + 1,
                            height=tile_size + 1,
                            fit=ft.ImageFit.COVER,
                        )
                    )
        for spot in spots:
            spot_x, spot_y = world_pixel(float(spot.get("lat", center_lat)), float(spot.get("lon", center_lon)))
            spot["x"] = max(.04, min(.96, (width / 2 + spot_x - center_x) / width))
            spot["y"] = max(.12, min(.84, (height / 2 + spot_y - center_y) / height))
        controls.extend(spot_pin(spot, width, height) for spot in visible_spots())
        for online_user in online_users_snapshot():
            if online_user["id"] == user_id or not online_user.get("sharing"):
                continue
            user_x, user_y = world_pixel(float(online_user["lat"]), float(online_user["lon"]))
            screen_x = width / 2 + user_x - center_x
            screen_y = height / 2 + user_y - center_y
            if -40 <= screen_x <= width + 40 and 80 <= screen_y <= height - 70:
                controls.append(ft.Container(
                    left=screen_x - 26, top=screen_y - 26,
                    content=ft.Column([
                        ft.Container(content=ft.Icon(ft.Icons.PERSON, color=ft.Colors.WHITE, size=20),
                                     width=44, height=44, alignment=ft.alignment.center,
                                     bgcolor=online_user["color"], border=ft.border.all(3, ft.Colors.WHITE),
                                     border_radius=22, shadow=ft.BoxShadow(blur_radius=14, color="#55000000")),
                        ft.Container(content=ft.Text(online_user["name"], size=9, weight=ft.FontWeight.BOLD),
                                     padding=ft.padding.symmetric(horizontal=6, vertical=2),
                                     bgcolor=ft.Colors.with_opacity(.92, "#241813"), border_radius=8),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=-2),
                    tooltip=f"オンライン: {online_user['name']}",
                ))
        # Current position with a soft radar ring.
        controls.extend([
            ft.Container(left=width / 2 - 58, top=height / 2 - 58, width=116, height=116, border=ft.border.all(1, ft.Colors.with_opacity(.25, "#3988F6")), bgcolor=ft.Colors.with_opacity(.06, "#3988F6"), border_radius=58),
            ft.Container(left=width / 2 - 21, top=height / 2 - 21, width=42, height=42, bgcolor="#3988F6", border=ft.border.all(4, ft.Colors.WHITE), border_radius=21, shadow=ft.BoxShadow(blur_radius=24, color=ft.Colors.with_opacity(.55, "#3988F6")), content=ft.Icon(ft.Icons.NAVIGATION, color=ft.Colors.WHITE, size=20), alignment=ft.alignment.center),
            ft.Container(left=8, bottom=84, content=ft.Text("© OpenStreetMap contributors", size=9, color="#18312A"),
                         padding=ft.padding.symmetric(horizontal=6, vertical=3), bgcolor=ft.Colors.with_opacity(.82, ft.Colors.WHITE), border_radius=6),
        ])
        return controls

    def top_hud(width: int) -> ft.Container:
        progress = (xp % 1000) / 1000
        return ft.Container(
            left=16,
            top=18,
            width=width - 32,
            content=glass(
                ft.Row(
                    [
                        ft.Container(content=ft.Text(str(current_level()), size=18, weight=ft.FontWeight.BOLD, color="#120D0B"), width=44, height=44, alignment=ft.alignment.center, bgcolor="#D6A06C", border_radius=14),
                        ft.Column([ft.Row([ft.Text(f"LEVEL {current_level()}", size=10, color="#BCAEA4"), online_count_text,
                                          ft.Text(f"{xp} XP", size=10, color="#D6A06C")], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                   ft.ProgressBar(value=progress, color="#D6A06C", bgcolor="#4A352C", bar_height=6),
                                   location_label], spacing=5, expand=True),
                        ft.Container(content=ft.IconButton(icon=ft.Icons.PERSON, icon_color="#FFF9F1", on_click=show_profile), bgcolor="#24342D", border_radius=14),
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER
                ), padding=12, radius=20
            ),
        )

    def change_zoom(delta: int) -> None:
        nonlocal map_zoom
        map_zoom = max(12, min(18, map_zoom + delta))
        render()

    def map_actions(width: int, height: int) -> list[ft.Control]:
        current_map_url = f"https://www.openstreetmap.org/?mlat={current_position['lat']:.6f}&mlon={current_position['lon']:.6f}#map={map_zoom}/{current_position['lat']:.6f}/{current_position['lon']:.6f}"
        return [
            ft.Container(right=16, top=106, content=glass(ft.IconButton(icon=ft.Icons.MY_LOCATION, icon_color="#73D7FF", tooltip="現在地を取得", on_click=locate_me), 2, 16)),
            ft.Container(right=16, top=166, content=glass(ft.IconButton(icon=ft.Icons.ADD_LOCATION_ALT, icon_color="#D6A06C", tooltip="スポットを追加", on_click=show_add_spot), 2, 16)),
            ft.Container(right=16, top=226, content=glass(ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_color="#FFF9F1", tooltip="地図を大きく開く", on_click=lambda e: page.launch_url(current_map_url)), 2, 16)),
            ft.Container(right=16, top=286, content=glass(ft.Column([
                ft.IconButton(icon=ft.Icons.ADD, icon_color="#FFF9F1", tooltip="拡大", on_click=lambda e: change_zoom(1)),
                ft.Container(height=1, width=30, bgcolor="#34483F"),
                ft.IconButton(icon=ft.Icons.REMOVE, icon_color="#FFF9F1", tooltip="縮小", on_click=lambda e: change_zoom(-1)),
            ], spacing=0), 2, 16)),
            ft.Container(left=16, top=108, content=ft.Container(content=ft.Row([ft.Icon(ft.Icons.SEARCH, size=15, color="#D6A06C"), ft.Text("場所を検索", size=10, weight=ft.FontWeight.BOLD)], spacing=7), padding=ft.padding.symmetric(horizontal=12, vertical=8), bgcolor=ft.Colors.with_opacity(.85, "#241813"), border_radius=20, on_click=search_places)),
        ]

    def map_filter_bar(width: int) -> ft.Container:
        filter_names = ["すべて", "小型家電", "スマホ・PC", "バッテリー", "ゲーム機", "お気に入り"]
        chips = []
        for value in filter_names:
            selected = active_spot_filter == value
            chips.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.FAVORITE if value == "お気に入り" else ft.Icons.CIRCLE,
                            size=11, color="#120D0B" if selected else "#D6A06C"),
                    ft.Text(value, size=10, weight=ft.FontWeight.BOLD,
                            color="#120D0B" if selected else "#FFF9F1"),
                ], spacing=5),
                padding=ft.padding.symmetric(horizontal=11, vertical=8),
                bgcolor="#D6A06C" if selected else ft.Colors.with_opacity(.90, "#241813"),
                border_radius=18,
                on_click=lambda e, choice=value: set_spot_filter(choice),
            ))
        return ft.Container(left=16, top=151, width=width - 92,
                            content=ft.Row(chips, spacing=7, scroll=ft.ScrollMode.AUTO))

    def scan_button(width: int) -> ft.Container:
        return ft.Container(
            left=width / 2 - 34, bottom=88,
            content=ft.Container(
                content=ft.IconButton(ft.Icons.RADAR, icon_color="#120D0B", icon_size=30,
                                      tooltip="周辺をスキャン", on_click=scan_nearby),
                width=68, height=68, alignment=ft.alignment.center,
                bgcolor="#D6A06C", border=ft.border.all(5, ft.Colors.WHITE), border_radius=34,
                shadow=ft.BoxShadow(blur_radius=24, color=ft.Colors.with_opacity(.55, "#A65E2E"), offset=ft.Offset(0, 8)),
                animate_scale=220,
            ),
        )

    def detail_sheet(width: int, height: int) -> ft.Container | None:
        if selected_spot is None:
            return None
        near = selected_spot["distance"] <= 150
        daily_done = checked_in_today(selected_spot)
        return ft.Container(
            left=12,
            bottom=88,
            width=width - 24,
            content=glass(
                ft.Column(
                    [
                        ft.Row([ft.Container(width=46, height=46, content=ft.Icon(ft.Icons.RECYCLING, color="#120D0B"), alignment=ft.alignment.center, bgcolor=selected_spot["color"], border_radius=15),
                                ft.Column([ft.Text(selected_spot["kind"], size=10, color=selected_spot["color"], weight=ft.FontWeight.BOLD),
                                           ft.Text(selected_spot["name"], size=17, weight=ft.FontWeight.BOLD)], spacing=1, expand=True),
                                ft.IconButton(icon=ft.Icons.FAVORITE if selected_spot.get("favorite") else ft.Icons.FAVORITE_BORDER,
                                              icon_color="#FF7A8A", tooltip="お気に入り",
                                              on_click=lambda e: toggle_favorite(selected_spot)),
                                ft.IconButton(icon=ft.Icons.CLOSE, on_click=close_sheet)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([direction_indicator(selected_spot), ft.Container(expand=True),
                                ft.Icon(ft.Icons.BOLT, size=17, color="#FFD86B"),
                                ft.Text(f"+{selected_spot['xp']} XP", size=12, color="#FFD86B", weight=ft.FontWeight.BOLD)],
                               spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([ft.Icon(ft.Icons.CALENDAR_TODAY, size=15, color="#D6A06C"),
                                ft.Text("本日チェックイン済み" if daily_done else "本日のチェックインが可能",
                                        size=11, color="#D6A06C" if daily_done else "#FFF9F1"),
                                ft.Container(expand=True),
                                ft.Text(f"累計 {int(selected_spot.get('visit_count', 0))}回", size=11, color="#BCAEA4")], spacing=6),
                        ft.Row([
                            ft.OutlinedButton("経路", icon=ft.Icons.DIRECTIONS,
                                              on_click=lambda e: open_directions(selected_spot), expand=True),
                            ft.OutlinedButton("共有", icon=ft.Icons.SHARE,
                                              on_click=lambda e: share_spot(selected_spot), expand=True),
                        ], spacing=8),
                        ft.FilledButton("本日チェックイン済み" if daily_done else ("デイリーチェックイン" if near else f"あと {format_distance(max(0, selected_spot['distance'] - 150))}"),
                                        icon=ft.Icons.CHECK_CIRCLE if daily_done else ft.Icons.RADAR,
                                        disabled=not near or daily_done, on_click=visit_spot,
                                        width=width - 56, height=48,
                                        style=ft.ButtonStyle(bgcolor="#D6A06C", color="#120D0B", shape=ft.RoundedRectangleBorder(radius=15))),
                    ], spacing=12
                ), padding=16, radius=26
            ),
        )

    def show_add_spot(event: ft.ControlEvent | None = None) -> None:
        name = ft.TextField(label="スポット名", prefix_icon=ft.Icons.RECYCLING, autofocus=True)
        kind = ft.Dropdown(label="回収できるもの", value="小型家電", options=[ft.dropdown.Option(v) for v in ["小型家電", "スマホ・PC", "バッテリー", "ゲーム機"]])
        dialog = ft.AlertDialog(modal=True, title=ft.Text("新しいスポットを発見"), content=ft.Column([ft.Text("取得した現在地の緯度・経度と一緒に登録します。", color="#BCAEA4"), ft.Text(location_label.value, size=12, color="#D6A06C"), name, kind], width=min(360, dimensions()[0] - 64), tight=True), actions=[])

        def save(event: ft.ControlEvent) -> None:
            if not (name.value or "").strip():
                name.error_text = "スポット名を入力してください"
                page.update()
                return
            new_spot = {"name": name.value.strip(), "kind": kind.value,
                        "lat": current_position["lat"], "lon": current_position["lon"],
                        "distance": 0, "x": .56, "y": .39, "color": "#D6A06C",
                        "visited": False, "xp": 100, "user_added": True}
            spots.append(new_spot)
            refresh_distances()
            save_app_state()
            try:
                with CONTENT_STORAGE_LOCK:
                    data_file.write_text(
                        json.dumps([spot for spot in spots if spot.get("user_added")], ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                announce_content_change()
            except OSError:
                toast("追加しましたが、端末への保存に失敗しました")
            dialog.open = False
            toast("現在地に新しいスポットを登録しました！")
            render()

        dialog.actions = [ft.TextButton("キャンセル", on_click=lambda e: setattr(dialog, "open", False) or page.update()), ft.FilledButton("マップに追加", icon=ft.Icons.ADD_LOCATION_ALT, on_click=save)]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def bottom_nav(width: int, height: int) -> ft.Container:
        items = [("map", ft.Icons.EXPLORE, "探索"), ("nearby", ft.Icons.RADAR, "近く"),
                 ("lab", ft.Icons.SCIENCE, "素材ラボ"), ("learn", ft.Icons.SCHOOL, "学ぶ"),
                 ("bag", ft.Icons.BACKPACK, "実績")]
        return ft.Container(
            left=12,
            bottom=12,
            width=width - 24,
            height=66,
            content=ft.Row([ft.Container(content=ft.Column([ft.Icon(icon, size=22, color="#D6A06C" if active_tab == key else "#9B8A80"), ft.Text(label, size=9, color="#D6A06C" if active_tab == key else "#9B8A80")], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER), expand=True, alignment=ft.alignment.center, on_click=lambda e, k=key: change_tab(k)) for key, icon, label in items], alignment=ft.MainAxisAlignment.SPACE_AROUND),
            bgcolor=ft.Colors.with_opacity(.94, "#201511"),
            border=ft.border.all(1, ft.Colors.with_opacity(.12, ft.Colors.WHITE)),
            border_radius=24,
            shadow=ft.BoxShadow(blur_radius=30, color=ft.Colors.with_opacity(.45, ft.Colors.BLACK), offset=ft.Offset(0, 12)),
        )

    def change_tab(tab: str) -> None:
        nonlocal active_tab, selected_spot
        active_tab = tab
        selected_spot = None
        render()

    def list_screen(width: int, height: int) -> list[ft.Control]:
        cards = []
        query = nearby_query.strip().lower()
        matches = [spot for spot in visible_spots()
                   if not query or query in f"{spot['name']} {spot['kind']}".lower()]
        for spot in sorted(matches, key=lambda item: item["distance"]):
            cards.append(ft.Container(
                content=ft.Row([
                    ft.Container(content=ft.Icon(ft.Icons.RECYCLING, color="#120D0B"), width=44, height=44,
                                 alignment=ft.alignment.center, bgcolor=spot["color"], border_radius=14),
                    ft.Column([ft.Text(spot["name"], weight=ft.FontWeight.BOLD),
                               ft.Text(spot["kind"], size=11, color="#BCAEA4")], expand=True, spacing=3),
                    direction_indicator(spot, compact=True),
                    ft.Icon(ft.Icons.FAVORITE, color="#FF7A8A", size=16, visible=bool(spot.get("favorite"))),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color="#9B8A80", size=18),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=9),
                padding=12, bgcolor="#2B1D17", border=ft.border.all(1, "#4B342A"), border_radius=18,
                on_click=lambda e, s=spot: open_spot(s)))
        if not cards:
            cards = [ft.Container(
                content=ft.Column([ft.Icon(ft.Icons.SEARCH_OFF, size=38, color="#9B8A80"),
                                   ft.Text("条件に合うスポットがありません", weight=ft.FontWeight.BOLD),
                                   ft.Text("検索語やフィルターを変えてみてください", size=11, color="#BCAEA4")],
                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=7),
                height=150, alignment=ft.alignment.center, bgcolor="#201511", border_radius=18,
            )]
        nearest = min((spot["distance"] for spot in matches), default=0)
        search_field = ft.TextField(
            value=nearby_query, hint_text="名前・回収品目を検索", prefix_icon=ft.Icons.SEARCH,
            dense=True, expand=True,
        )

        def apply_nearby_search(event: ft.ControlEvent) -> None:
            nonlocal nearby_query
            nearby_query = search_field.value or ""
            render()

        search_field.on_submit = apply_nearby_search
        return [ft.Container(width=width, height=height, bgcolor="#120D0B"),
                ft.Container(left=20, top=30, width=width - 40, height=height - 112,
                             content=ft.Column([
                                 ft.Row([ft.Text("近くのスポット", size=28, weight=ft.FontWeight.BOLD, expand=True),
                                         ft.IconButton(ft.Icons.REFRESH, tooltip="現在地と距離を更新", on_click=locate_me)]),
                                 ft.Text(f"{len(matches)}件・最寄りまで {format_distance(nearest)}" if matches else "0件", color="#BCAEA4"),
                                 ft.Row([search_field, ft.IconButton(ft.Icons.SEARCH, tooltip="検索", on_click=apply_nearby_search)], spacing=5),
                                 ft.Column(cards, spacing=10, scroll=ft.ScrollMode.AUTO, expand=True),
                             ], spacing=12))]

    def open_full_lab(event: ft.ControlEvent | None = None) -> None:
        page.clean()
        physics_app(page, on_back=start_main_app)

    def lab_screen(width: int, height: int) -> list[ft.Control]:
        device_cards = []
        for key, device in DEVICE_LIBRARY.items():
            total = sum(device["metals"].values())
            bars = ft.Row([
                ft.Container(width=max(4, device["metals"][symbol] / total * 130), height=7,
                             bgcolor=METALS[symbol]["color"], border_radius=4)
                for symbol in METALS
            ], spacing=2)
            device_cards.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([ft.Container(ft.Icon(device["icon"], color="#120D0B"), width=44, height=44,
                                             alignment=ft.alignment.center, bgcolor=device["color"], border_radius=14),
                                ft.Column([ft.Text(device["name"], weight=ft.FontWeight.BOLD),
                                           ft.Text(f"推定貴金属量 {total:.3f} g", size=11, color="#BCAEA4")], spacing=3, expand=True)], spacing=10),
                        bars,
                        ft.Row([ft.Text("Au 金", size=10, color="#FFD86B"), ft.Text("Ag 銀", size=10, color="#B9C5CB"),
                                ft.Text("Pd パラジウム", size=10, color="#D6A06C")], spacing=12),
                    ], spacing=10),
                    padding=14,
                    bgcolor=ft.Colors.with_opacity(.72, "#07384A"),
                    border=ft.border.all(1, ft.Colors.with_opacity(.28, ft.Colors.WHITE)),
                    border_radius=18,
                    on_click=lambda e, k=key: toast(f"{DEVICE_LIBRARY[k]['name']}を素材ラボに追加しました"),
                )
            )
        return [
            ft.Container(
                width=width,
                height=height,
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=["#EAFBFF", "#7DD8ED", "#176A86", "#082B3A"],
                    stops=[0.0, 0.28, 0.68, 1.0],
                ),
            ),
            ft.Container(left=width * .08, top=height * .16, width=26, height=26,
                         border=ft.border.all(2, ft.Colors.with_opacity(.55, ft.Colors.WHITE)), border_radius=20),
            ft.Container(left=width * .78, top=height * .25, width=14, height=14,
                         border=ft.border.all(2, ft.Colors.with_opacity(.45, ft.Colors.WHITE)), border_radius=20),
            ft.Container(left=width * .68, top=height * .52, width=34, height=34,
                         border=ft.border.all(2, ft.Colors.with_opacity(.32, ft.Colors.WHITE)), border_radius=24),
            ft.Container(left=20, top=26, width=width - 40, height=height - 110,
                         content=ft.Column([
                             ft.Text("素材ラボ", size=28, weight=ft.FontWeight.BOLD),
                             ft.Text("水の動きから、デバイスに眠る資源を見つけよう。", color="#DDF8FF"),
                             ft.Container(content=ft.Column([
                                 ft.Row([ft.Icon(ft.Icons.WATER_DROP, color="#73D7FF", size=34),
                                         ft.Column([ft.Text("デバイスを素材へ戻す", weight=ft.FontWeight.BOLD),
                                                    ft.Text("水中でほどける素材と貴金属量を観察できます", size=11, color="#B9EAF5")], expand=True)], spacing=12),
                                 ft.FilledButton("水中ラボを開く", icon=ft.Icons.WATER,
                                                 on_click=open_full_lab, width=width - 76,
                                                 style=ft.ButtonStyle(bgcolor="#D8F8FF", color="#083548")),
                             ], spacing=12), padding=18,
                                bgcolor=ft.Colors.with_opacity(.68, "#07384A"),
                                border=ft.border.all(1, ft.Colors.with_opacity(.5, ft.Colors.WHITE)),
                                border_radius=24,
                                blur=ft.Blur(12, 12)),
                             ft.Column(device_cards, spacing=10, scroll=ft.ScrollMode.AUTO, expand=True),
                         ], spacing=12)),
        ]

    def save_columns() -> None:
        try:
            with COMMUNITY_COLUMNS_LOCK:
                columns_file.write_text(
                    json.dumps(community_columns, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            announce_content_change()
        except OSError:
            toast("コラムの保存に失敗しました")

    def open_column(column: dict) -> None:
        dialog = ft.AlertDialog(modal=True)

        def like(event: ft.ControlEvent) -> None:
            with COMMUNITY_COLUMNS_LOCK:
                column["likes"] = int(column.get("likes", 0)) + 1
            save_columns()
            like_button.text = str(column["likes"])
            page.update()

        like_button = ft.OutlinedButton(str(column.get("likes", 0)), icon=ft.Icons.FAVORITE_BORDER, on_click=like)
        dialog.title = ft.Column([
            ft.Row([ft.Container(ft.Text(column.get("category", "その他"), size=10, color="#D6A06C", weight=ft.FontWeight.BOLD),
                                 padding=ft.padding.symmetric(horizontal=9, vertical=4), bgcolor="#4A2E20", border_radius=14),
                    ft.Text(f"by {column.get('author', '匿名')}", size=11, color="#BCAEA4")], spacing=8),
            ft.Text(column.get("title", "無題"), size=22, weight=ft.FontWeight.BOLD),
        ], spacing=8)
        dialog.content = ft.Container(
            ft.Column([ft.Text(column.get("body", ""), size=14),
                       ft.Divider(),
                       ft.Text("役に立ったらハートを送ろう", size=11, color="#BCAEA4")],
                      tight=True, spacing=14),
            width=min(460, dimensions()[0] - 64),
        )
        dialog.actions = [like_button, ft.TextButton("閉じる", on_click=lambda e: setattr(dialog, "open", False) or page.update())]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def compose_column(event: ft.ControlEvent | None = None) -> None:
        title = ft.TextField(label="タイトル *", autofocus=True, max_length=60)
        author = ft.TextField(label="投稿者名", value=user_name if authenticated_username else "匿名")
        category = ft.Dropdown(label="カテゴリ", value="発見", options=[ft.dropdown.Option(v) for v in ["発見", "回収体験", "安全", "アイデア", "地域情報"]])
        body = ft.TextField(label="本文 *", multiline=True, min_lines=5, max_lines=9, max_length=1200)
        dialog = ft.AlertDialog(modal=True, title=ft.Text("みんなのコラムを書く", weight=ft.FontWeight.BOLD))

        def publish(publish_event: ft.ControlEvent) -> None:
            if not (title.value or "").strip() or not (body.value or "").strip():
                title.error_text = "タイトルを入力してください" if not (title.value or "").strip() else None
                body.error_text = "本文を入力してください" if not (body.value or "").strip() else None
                page.update()
                return
            with COMMUNITY_COLUMNS_LOCK:
                community_columns.insert(0, {
                    "id": uuid.uuid4().hex,
                    "title": title.value.strip(),
                    "body": body.value.strip(),
                    "author": (author.value or "匿名").strip(),
                    "category": category.value,
                    "likes": 0,
                    "published_at": date.today().isoformat(),
                })
            save_columns()
            dialog.open = False
            toast("サイトのみんなにコラムを公開しました")
            render()

        dialog.content = ft.Container(ft.Column([title, author, category, body,
                                                   ft.Text("投稿すると、このサイトを利用しているみんなに公開されます。", size=10, color="#BCAEA4")],
                                                  tight=True, spacing=12), width=min(480, dimensions()[0] - 64))
        dialog.actions = [ft.TextButton("キャンセル", on_click=lambda e: setattr(dialog, "open", False) or page.update()),
                          ft.FilledButton("公開する", icon=ft.Icons.PUBLISH, on_click=publish)]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def learn_screen(width: int, height: int) -> list[ft.Control]:
        with COMMUNITY_COLUMNS_LOCK:
            columns_snapshot = list(community_columns)
        lessons = [
            ("都市鉱山とは？", "使われなくなった電子機器に眠る金属資源。日本の家庭にも大量の資源が蓄積されています。", ft.Icons.LOCATION_CITY, "#D6A06C"),
            ("スマホの中の資源", "金・銀・パラジウムなど、少量でも価値の高い金属が高密度で含まれています。", ft.Icons.PHONE_IPHONE, "#73D7FF"),
            ("なぜ正しく回収する？", "資源循環だけでなく、不適切な廃棄による有害物質や発火事故を防ぎます。", ft.Icons.RECYCLING, "#FFD86B"),
            ("回収前にすること", "データをバックアップして初期化し、SIM・SDカードを取り外します。電池は自治体の案内を確認しましょう。", ft.Icons.SECURITY, "#BFA5FF"),
        ]
        lesson_cards = [
            ft.Container(content=ft.Row([
                ft.Container(ft.Icon(icon, color="#120D0B"), width=48, height=48, alignment=ft.alignment.center, bgcolor=color, border_radius=15),
                ft.Column([ft.Text(title, size=16, weight=ft.FontWeight.BOLD), ft.Text(body, size=11, color="#C8BBB2")], spacing=5, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START), padding=15, bgcolor="#2B1D17", border_radius=19)
            for title, body, icon, color in lessons
        ]
        column_cards = [
            ft.Container(
                content=ft.Column([
                    ft.Row([ft.Container(ft.Text(column.get("category", "その他"), size=9, color="#D6A06C"),
                                         padding=ft.padding.symmetric(horizontal=8, vertical=3), bgcolor="#4A2E20", border_radius=12),
                            ft.Container(expand=True),
                            ft.Icon(ft.Icons.FAVORITE, size=13, color="#FF7A8A"),
                            ft.Text(str(column.get("likes", 0)), size=10, color="#BCAEA4")], spacing=4),
                    ft.Text(column.get("title", "無題"), size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(column.get("body", ""), size=11, color="#C8BBB2", max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"by {column.get('author', '匿名')}", size=10, color="#9B8A80"),
                ], spacing=7),
                padding=14, bgcolor="#2B1D17", border=ft.border.all(1, "#4B342A"), border_radius=18,
                on_click=lambda e, item=column: open_column(item),
            ) for column in columns_snapshot
        ]
        return [ft.Container(width=width, height=height, bgcolor="#120D0B"),
                ft.Container(left=20, top=26, width=width - 40, height=height - 110,
                             content=ft.Column([ft.Text("都市鉱山を学ぶ", size=28, weight=ft.FontWeight.BOLD),
                                                ft.Text("知る・書く・地域で共有する。", color="#BCAEA4"),
                                                ft.Row([ft.Text("基礎ガイド", size=18, weight=ft.FontWeight.BOLD, expand=True),
                                                        ft.FilledButton("コラムを書く", icon=ft.Icons.EDIT, on_click=compose_column,
                                                                        style=ft.ButtonStyle(bgcolor="#D6A06C", color="#120D0B"))]),
                                                ft.Column([*lesson_cards,
                                                           ft.Container(height=8),
                                                           ft.Text("みんなのコラム", size=20, weight=ft.FontWeight.BOLD),
                                                           ft.Row([ft.Icon(ft.Icons.PUBLIC, size=14, color="#D6A06C"),
                                                                   ft.Text(f"サイトで公開中・{len(columns_snapshot)}件の投稿", size=11, color="#BCAEA4")], spacing=5),
                                                           *column_cards], spacing=11, scroll=ft.ScrollMode.AUTO, expand=True)], spacing=12))]

    def bag_screen(width: int, height: int) -> list[ft.Control]:
        return [ft.Container(width=width, height=height, gradient=ft.LinearGradient(colors=["#332018", "#120D0B"])), ft.Container(left=20, top=30, width=width - 40, content=ft.Column([ft.Text("マイバッグ", size=28, weight=ft.FontWeight.BOLD), ft.Text("回収アクティビティ", color="#BCAEA4"), ft.Container(height=18), glass(ft.Column([ft.Icon(ft.Icons.EMOJI_EVENTS, color="#FFD86B", size=54), ft.Text(f"LEVEL {current_level()}", size=22, weight=ft.FontWeight.BOLD), ft.Text(f"累計 {xp} XP", color="#BCAEA4")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), 24), ft.Row([glass(ft.Column([ft.Text(str(recycled), size=25, weight=ft.FontWeight.BOLD), ft.Text("回収数", size=10, color="#BCAEA4")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), 18), glass(ft.Column([ft.Text(str(sum(1 for s in spots if s['visited'])), size=25, weight=ft.FontWeight.BOLD), ft.Text("発見済み", size=10, color="#BCAEA4")], horizontal_alignment=ft.CrossAxisAlignment.CENTER), 18)], alignment=ft.MainAxisAlignment.SPACE_EVENLY)], spacing=10))]

    def render(event: ft.ControlEvent | None = None) -> None:
        width, height = dimensions()
        if active_tab == "map":
            controls = [*map_background(width, height), top_hud(width), *map_actions(width, height), map_filter_bar(width)]
            detail = detail_sheet(width, height)
            if detail:
                controls.append(detail)
            else:
                controls.append(scan_button(width))
        elif active_tab == "nearby":
            controls = list_screen(width, height)
        elif active_tab == "lab":
            controls = lab_screen(width, height)
        elif active_tab == "learn":
            controls = learn_screen(width, height)
        else:
            controls = bag_screen(width, height)
        controls.append(bottom_nav(width, height))
        root.width = width
        root.height = height
        root.controls = controls
        if page.controls:
            page.update()

    def activate_account(username: str) -> None:
        nonlocal authenticated_username, user_id, user_name, user_color, xp, recycled
        authenticated_username = username
        user_id = hashlib.sha256(username.encode()).hexdigest()[:8]
        user_name = user_accounts[username].get("display_name") or username
        user_color = ["#FF7A8A", "#73D7FF", "#FFD86B", "#BFA5FF", "#D6A06C"][int(user_id[:2], 16) % 5]
        xp = 0
        recycled = 0
        for spot in spots:
            spot["favorite"] = False
            spot["visited"] = False
            spot["last_checkin"] = None
            spot["visit_count"] = 0
        try:
            page.client_storage.set("m3ow.auth_user", username)
            account_state = page.client_storage.get(f"m3ow.user_state.{username}")
            if isinstance(account_state, dict):
                xp = int(account_state.get("xp", 0))
                recycled = int(account_state.get("recycled", 0))
                for spot in spots:
                    state = account_state.get("spots", {}).get(spot["name"], {})
                    spot["favorite"] = bool(state.get("favorite", False))
                    spot["visited"] = bool(state.get("visited", False))
                    spot["last_checkin"] = state.get("last_checkin")
                    spot["visit_count"] = int(state.get("visit_count", 0))
        except Exception:
            pass

    def start_main_app() -> None:
        nonlocal presence_thread_started, session_active, session_generation, presence_signature
        session_active = True
        if not presence_thread_started:
            session_generation += 1
        current_generation = session_generation
        presence_signature = ""
        page.clean()
        page.overlay.clear()
        page.overlay.append(geolocator)
        page.on_resized = render
        page.on_disconnect = disconnect_session
        update_presence()
        page.add(root)
        render()
        if not presence_thread_started:
            presence_thread_started = True
            page.run_thread(presence_loop, current_generation)

    def show_auth_screen(register_mode: bool = False) -> None:
        page.clean()
        page.overlay.clear()
        page.on_resized = None
        page.on_keyboard_event = None
        username = ft.TextField(label="ユーザーID", prefix_icon=ft.Icons.PERSON, autofocus=True)
        display_name = ft.TextField(label="表示名", prefix_icon=ft.Icons.BADGE, visible=register_mode)
        password = ft.TextField(label="パスワード", prefix_icon=ft.Icons.LOCK, password=True, can_reveal_password=True)
        confirm = ft.TextField(label="パスワード確認", prefix_icon=ft.Icons.LOCK_OUTLINE,
                               password=True, can_reveal_password=True, visible=register_mode)
        error = ft.Text(color="#FF7A8A", size=11)

        def refresh_user_accounts() -> None:
            try:
                with CONTENT_STORAGE_LOCK:
                    latest_accounts = json.loads(users_file.read_text(encoding="utf-8")) if users_file.exists() else {}
                if isinstance(latest_accounts, dict):
                    user_accounts.clear()
                    user_accounts.update(latest_accounts)
            except (OSError, json.JSONDecodeError):
                pass

        def submit(event: ft.ControlEvent | None = None) -> None:
            key = (username.value or "").strip().lower()
            secret = password.value or ""
            valid_user_id = len(key) >= 3 and all(
                character.isascii() and (character.isalnum() or character == "_")
                for character in key
            )
            if not valid_user_id:
                error.value = "ユーザーIDは英数字と_で3文字以上にしてください"
                page.update()
                return
            refresh_user_accounts()
            if register_mode:
                if key in user_accounts:
                    error.value = "このユーザーIDは使用されています"
                elif len(secret) < 8:
                    error.value = "パスワードは8文字以上にしてください"
                elif secret != (confirm.value or ""):
                    error.value = "確認用パスワードが一致しません"
                else:
                    salt = secrets.token_hex(16)
                    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), 200_000).hex()
                    user_accounts[key] = {"display_name": (display_name.value or key).strip(),
                                          "salt": salt, "password_hash": digest}
                    try:
                        with CONTENT_STORAGE_LOCK:
                            users_file.write_text(json.dumps(user_accounts, ensure_ascii=False, indent=2), encoding="utf-8")
                    except OSError:
                        error.value = "アカウントを保存できませんでした"
                        page.update()
                        return
                    activate_account(key)
                    start_main_app()
                    return
            else:
                account = user_accounts.get(key)
                if not account:
                    error.value = "ユーザーIDまたはパスワードが違います"
                else:
                    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(account["salt"]), 200_000).hex()
                    if not secrets.compare_digest(digest, account["password_hash"]):
                        error.value = "ユーザーIDまたはパスワードが違います"
                    else:
                        activate_account(key)
                        start_main_app()
                        return
            page.update()

        password.on_submit = submit
        confirm.on_submit = submit
        auth_card = ft.Container(
            content=ft.Column([
                ft.Container(ft.Icon(ft.Icons.RECYCLING, size=38, color="#120D0B"), width=68, height=68,
                             alignment=ft.alignment.center, bgcolor="#D6A06C", border_radius=22),
                ft.Text("fukucycle", size=32, weight=ft.FontWeight.BOLD),
                ft.Text("都市鉱山を、みんなの冒険に。", color="#BCAEA4"),
                ft.Container(height=8), username, display_name, password, confirm, error,
                ft.FilledButton("アカウントを作成" if register_mode else "ログイン",
                                icon=ft.Icons.PERSON_ADD if register_mode else ft.Icons.LOGIN,
                                width=340, height=50, on_click=submit,
                                style=ft.ButtonStyle(bgcolor="#D6A06C", color="#120D0B")),
                ft.TextButton("ログインへ戻る" if register_mode else "新規登録",
                              on_click=lambda e: show_auth_screen(not register_mode)),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            width=min(390, dimensions()[0] - 32), padding=24, bgcolor="#241813",
            border=ft.border.all(1, "#50382D"), border_radius=28,
            shadow=ft.BoxShadow(blur_radius=36, color="#66000000", offset=ft.Offset(0, 16)),
        )
        page.add(ft.Container(content=auth_card, expand=True, alignment=ft.alignment.center,
                              gradient=ft.LinearGradient(colors=["#120D0B", "#2C1B14"])))

    if authenticated_username:
        start_main_app()
    else:
        show_auth_screen()


if __name__ == "__main__":
    ft.app(target=recovery_go_app)
