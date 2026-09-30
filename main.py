import flet as ft
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import os


def to_degrees(value):
    d, m, s = value
    return float(d) + float(m) / 60 + float(s) / 3600


def read_metadata(path):
    data = {"camera": {}, "time": {}, "location": {}, "settings": {}, "file": {}}
    img = Image.open(path)
    data["file"]["Format"] = img.format or "Unknown"
    data["file"]["Resolution"] = f"{img.width} x {img.height}"
    data["file"]["Size"] = f"{os.path.getsize(path) / 1024:.1f} KB"

    exif = img._getexif() if hasattr(img, "_getexif") else None
    if not exif:
        return data

    named = {TAGS.get(k, k): v for k, v in exif.items()}

    for key, label in [("Make", "Brand"), ("Model", "Model"), ("Software", "Software")]:
        if key in named:
            data["camera"][label] = str(named[key]).strip()

    for key, label in [("DateTimeOriginal", "Taken on"), ("DateTime", "Modified on")]:
        if key in named:
            data["time"][label] = str(named[key])

    for key, label in [
        ("ISOSpeedRatings", "ISO"),
        ("FNumber", "Aperture"),
        ("ExposureTime", "Shutter"),
        ("FocalLength", "Focal length"),
        ("Flash", "Flash"),
    ]:
        if key in named:
            data["settings"][label] = str(named[key])

    gps_raw = named.get("GPSInfo")
    if gps_raw:
        gps = {GPSTAGS.get(k, k): v for k, v in gps_raw.items()}
        try:
            lat = to_degrees(gps["GPSLatitude"])
            lon = to_degrees(gps["GPSLongitude"])
            if gps.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps.get("GPSLongitudeRef") == "W":
                lon = -lon
            data["location"]["Latitude"] = f"{lat:.6f}"
            data["location"]["Longitude"] = f"{lon:.6f}"
            data["location"]["Map"] = f"https://www.google.com/maps?q={lat},{lon}"
        except Exception:
            pass
    return data


def main(page: ft.Page):
    page.title = "Photo Meta"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0D0F14"
    page.padding = 0

    ACCENT = "#7C5CFF"
    state = {"path": None}

    preview = ft.Image(width=320, height=320, fit=ft.ImageFit.CONTAIN,
                       border_radius=16, visible=False)
    result_col = ft.Column(spacing=12)

    def glow(color, size, **pos):
        return ft.Container(
            width=size, height=size,
            gradient=ft.RadialGradient(
                colors=[ft.Colors.with_opacity(0.45, color), ft.Colors.TRANSPARENT],
                radius=0.5,
            ),
            **pos,
        )

    def card(title, icon, rows):
        items = []
        for k, v in rows.items():
            if k == "Map":
                items.append(ft.TextButton("Open in Google Maps", url=v))
            else:
                items.append(ft.Row([
                    ft.Text(k, color="#9AA0B4", size=13, width=110),
                    ft.Text(v, size=14, expand=True, selectable=True),
                ]))
        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(icon, color=ACCENT, size=20),
                        ft.Text(title, size=16, weight=ft.FontWeight.BOLD)]),
                ft.Divider(height=1, color="#2C3142"),
                *items,
            ], spacing=8),
            bgcolor=ft.Colors.with_opacity(0.65, "#161A23"),
            border=ft.border.all(1, ft.Colors.with_opacity(0.25, ACCENT)),
            padding=16, border_radius=16,
        )

    def on_pick(e: ft.FilePickerResultEvent):
        if e.files:
            state["path"] = e.files[0].path
            preview.src = state["path"]
            preview.visible = True
            done_btn.visible = True
            change_btn.visible = True
            back_btn.visible = True
            select_btn.visible = False
            result_col.controls.clear()
            page.update()

    picker = ft.FilePicker(on_result=on_pick)
    page.overlay.append(picker)

    def pick(e):
        picker.pick_files(file_type=ft.FilePickerFileType.IMAGE)

    def go_home(e):
        state["path"] = None
        preview.visible = False
        done_btn.visible = False
        change_btn.visible = False
        back_btn.visible = False
        select_btn.visible = True
        result_col.controls.clear()
        page.update()

    def show_result(e):
        result_col.controls.clear()
        try:
            d = read_metadata(state["path"])
        except Exception as ex:
            result_col.controls.append(ft.Text(f"Error: {ex}", color="red"))
            page.update()
            return
        sections = [
            ("Camera / Phone", ft.Icons.PHONE_ANDROID, d["camera"]),
            ("Date & Time", ft.Icons.SCHEDULE, d["time"]),
            ("Location", ft.Icons.LOCATION_ON, d["location"]),
            ("Camera Settings", ft.Icons.CAMERA_ALT, d["settings"]),
            ("File Info", ft.Icons.INSERT_DRIVE_FILE, d["file"]),
        ]
        for title, icon, rows in sections:
            if rows:
                result_col.controls.append(card(title, icon, rows))
            elif title == "Location":
                result_col.controls.append(card(title, icon, {"Status": "No location in this photo"}))
        page.update()

    back_btn = ft.TextButton("Back", icon=ft.Icons.ARROW_BACK, on_click=go_home,
                             visible=False)
    select_btn = ft.ElevatedButton(
        "Select Photo", icon=ft.Icons.PHOTO_LIBRARY, on_click=pick,
        bgcolor=ACCENT, color="white", height=56, width=260,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=28)),
    )
    done_btn = ft.ElevatedButton(
        "Done", icon=ft.Icons.CHECK, on_click=show_result,
        bgcolor=ACCENT, color="white", height=50, width=160, visible=False,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=25)),
    )
    change_btn = ft.OutlinedButton(
        "Change", on_click=pick, height=50, width=140, visible=False,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=25)),
    )

    body = ft.Column(
        [
            ft.Row([back_btn]),
            ft.Text("Photo Meta", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("See the hidden details of any photo", color="#9AA0B4"),
            ft.Container(height=20),
            ft.Row([preview], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([select_btn], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([done_btn, change_btn], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=10),
            result_col,
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    page.add(
        ft.Stack(
            [
                ft.Container(
                    expand=True,
                    gradient=ft.LinearGradient(
                        begin=ft.alignment.top_left,
                        end=ft.alignment.bottom_right,
                        colors=["#0D0F14", "#1A1240", "#2B1B6B"],
                    ),
                ),
                glow(ACCENT, 420, left=-120, top=-100),
                glow("#2EC4B6", 380, right=-140, bottom=-100),
                ft.SafeArea(
                    ft.Container(content=body, padding=20, expand=True),
                    expand=True,
                ),
            ],
            expand=True,
        )
    )


ft.app(target=main)