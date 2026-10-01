import flet as ft
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS
import os, io, base64, time

ACCENT = "#7C5CFF"
BG = "#0B0B14"
PHONES = {"2411DRN47I": "Redmi 14C 5G"}
TINY = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def deg(v):
    d, m, s = v
    return float(d) + float(m) / 60 + float(s) / 3600


def fmt_shutter(v):
    try:
        f = float(v)
        return f"1/{round(1 / f)} s" if f < 1 else f"{f:.1f} s"
    except Exception:
        return str(v)


def make_preview(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((900, 900))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def read_metadata(path):
    data = {"camera": {}, "time": {}, "location": {}, "settings": {}, "file": {}}
    img = Image.open(path)
    data["file"]["Format"] = img.format or "Unknown"
    data["file"]["Resolution"] = f"{img.width} x {img.height}"
    data["file"]["Size"] = f"{os.path.getsize(path) / 1024:.1f} KB"
    exif = img._getexif() if hasattr(img, "_getexif") else None
    if not exif:
        return data
    n = {TAGS.get(k, k): v for k, v in exif.items()}

    if "Make" in n:
        data["camera"]["Brand"] = str(n["Make"]).strip()
    if "Model" in n:
        m = str(n["Model"]).strip()
        data["camera"]["Model"] = PHONES.get(m, m)
    if "Software" in n:
        data["camera"]["Software"] = str(n["Software"]).strip()
    for k, label in [("DateTimeOriginal", "Taken on"), ("DateTime", "Modified on")]:
        if k in n:
            data["time"][label] = str(n[k])

    s = data["settings"]
    if "ISOSpeedRatings" in n:
        s["ISO"] = str(n["ISOSpeedRatings"])
    if "FNumber" in n:
        s["Aperture"] = f"f/{float(n['FNumber']):.1f}"
    if "ExposureTime" in n:
        s["Shutter"] = fmt_shutter(n["ExposureTime"])
    if "FocalLength" in n:
        s["Focal length"] = f"{float(n['FocalLength']):.2f} mm"
    if "Flash" in n:
        s["Flash"] = "Fired" if int(n["Flash"]) & 1 else "Off"

    raw = n.get("GPSInfo")
    if raw:
        g = {GPSTAGS.get(k, k): v for k, v in raw.items()}
        try:
            lat, lon = deg(g["GPSLatitude"]), deg(g["GPSLongitude"])
            if g.get("GPSLatitudeRef") == "S":
                lat = -lat
            if g.get("GPSLongitudeRef") == "W":
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
    page.bgcolor = BG
    page.padding = 0
    st = {"path": None}
    W = ft.Colors.with_opacity

    preview = ft.Image(src_base64=TINY, width=320, height=320, fit=ft.ImageFit.CONTAIN)
    preview_box = ft.Container(
        preview, border_radius=24, visible=False,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=ft.BoxShadow(blur_radius=40, color=W(0.35, ACCENT)),
    )
    results = ft.Column(spacing=14)

    def glow(color, size, **pos):
        return ft.Container(
            width=size, height=size,
            gradient=ft.RadialGradient(colors=[W(0.45, color), ft.Colors.TRANSPARENT], radius=0.5),
            **pos)

    def gbtn(text, icon, on_click, width=260, visible=True, outline=False):
        return ft.Container(
            content=ft.Row(
                [ft.Icon(icon, color="white", size=22),
                 ft.Text(text, size=16, weight=ft.FontWeight.W_600, color="white")],
                alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            width=width, height=56, border_radius=28, visible=visible,
            ink=True, on_click=on_click,
            gradient=None if outline else ft.LinearGradient(
                begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                colors=["#9B7BFF", "#5B3DF5"]),
            bgcolor=W(0.06, "white") if outline else None,
            border=ft.border.all(1.5, W(0.45, "white")) if outline else None,
            shadow=None if outline else ft.BoxShadow(
                blur_radius=28, color=W(0.55, ACCENT), offset=ft.Offset(0, 8)),
        )

    def card(title, icon, color, rows):
        items = []
        for k, v in rows.items():
            if k == "Map":
                items.append(ft.TextButton("Open in Google Maps", icon=ft.Icons.MAP, url=v))
            else:
                items.append(ft.Row([
                    ft.Text(k, color="#9AA0B4", size=13, width=110),
                    ft.Text(v, size=14, expand=True, selectable=True)]))
        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Icon(icon, color=color, size=20),
                        ft.Text(title, size=16, weight=ft.FontWeight.BOLD)]),
                ft.Divider(height=1, color=W(0.12, "white")),
                *items], spacing=8),
            padding=18, border_radius=20,
            bgcolor=W(0.07, "white"),
            border=ft.border.all(1, W(0.14, "white")),
            blur=ft.Blur(12, 12, ft.BlurTileMode.MIRROR),
            opacity=0, animate_opacity=400,
            offset=ft.Offset(0, 0.08),
            animate_offset=ft.Animation(400, ft.AnimationCurve.EASE_OUT),
        )

    def on_pick(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        st["path"] = e.files[0].path
        try:
            preview.src_base64 = make_preview(st["path"])
        except Exception:
            pass
        preview_box.visible = True
        done_btn.visible = change_btn.visible = back_btn.visible = True
        hero.visible = False
        select_btn.visible = False
        results.controls.clear()
        page.update()

    picker = ft.FilePicker(on_result=on_pick)
    page.overlay.append(picker)

    def pick(e):
        picker.pick_files(file_type=ft.FilePickerFileType.IMAGE)

    def go_home(e):
        st["path"] = None
        preview_box.visible = False
        done_btn.visible = change_btn.visible = back_btn.visible = False
        hero.visible = True
        select_btn.visible = True
        results.controls.clear()
        page.update()

    def show_result(e):
        results.controls.clear()
        try:
            d = read_metadata(st["path"])
        except Exception as ex:
            results.controls.append(ft.Text(f"Error: {ex}", color="red"))
            page.update()
            return
        spec = [
            ("Camera / Phone", ft.Icons.PHONE_ANDROID, "#7C5CFF", d["camera"]),
            ("Date & Time", ft.Icons.SCHEDULE, "#FF6B81", d["time"]),
            ("Location", ft.Icons.LOCATION_ON, "#B388FF", d["location"]),
            ("Camera Settings", ft.Icons.CAMERA_ALT, "#FFB547", d["settings"]),
            ("File Info", ft.Icons.INSERT_DRIVE_FILE, "#2EC4B6", d["file"]),
        ]
        cards = []
        for title, icon, color, rows in spec:
            if rows:
                cards.append(card(title, icon, color, rows))
            elif title == "Location":
                cards.append(card(title, icon, color, {"Status": "No location in this photo"}))
        results.controls = cards
        page.update()
        for c in cards:
            time.sleep(0.1)
            c.opacity = 1
            c.offset = ft.Offset(0, 0)
            c.update()

    back_btn = ft.TextButton("Back", icon=ft.Icons.ARROW_BACK, on_click=go_home, visible=False)
    select_btn = gbtn("Select Photo", ft.Icons.PHOTO_LIBRARY, pick)
    done_btn = gbtn("Done", ft.Icons.CHECK, show_result, width=160, visible=False)
    change_btn = gbtn("Change", ft.Icons.SWAP_HORIZ, pick, width=140, visible=False, outline=True)

    hero = ft.Container(
        ft.Icon(ft.Icons.IMAGE_SEARCH, size=72, color="white"),
        width=150, height=150, border_radius=75, alignment=ft.alignment.center,
        gradient=ft.LinearGradient(colors=[W(0.35, ACCENT), W(0.08, "white")]),
        border=ft.border.all(1, W(0.25, "white")),
        shadow=ft.BoxShadow(blur_radius=50, color=W(0.4, ACCENT)),
        margin=ft.margin.only(top=30, bottom=30),
    )

    body = ft.Column(
        [
            ft.Row([back_btn]),
            ft.Text("Photo Meta", size=36, weight=ft.FontWeight.W_800),
            ft.Text("Discover the hidden story of every photo", color="#9AA0B4", size=14),
            hero,
            ft.Row([preview_box], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=14),
            ft.Row([select_btn], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([done_btn, change_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=12),
            ft.Container(height=14),
            results,
            ft.Container(height=20),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        scroll=ft.ScrollMode.AUTO, expand=True,
    )

    logo = ft.Container(
        ft.Image(src="icon.png", width=140, height=140, border_radius=32),
        scale=0.6, opacity=0,
        animate_scale=ft.Animation(900, ft.AnimationCurve.EASE_OUT_BACK),
        animate_opacity=700,
    )
    splash = ft.Container(
        content=ft.Column(
            [logo, ft.Text("Photo Meta", size=26, weight=ft.FontWeight.W_700)],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=18),
        bgcolor=BG, expand=True, alignment=ft.alignment.center, animate_opacity=500,
    )

    page.add(ft.Stack([
        ft.Container(expand=True, gradient=ft.LinearGradient(
            begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
            colors=[BG, "#1A1240", "#2B1B6B"])),
        glow(ACCENT, 420, left=-120, top=-100),
        glow("#2EC4B6", 380, right=-140, bottom=-100),
        ft.SafeArea(ft.Container(body, padding=20, expand=True), expand=True),
        splash,
    ], expand=True))

    logo.scale = 1
    logo.opacity = 1
    page.update()
    time.sleep(1.6)
    splash.opacity = 0
    page.update()
    time.sleep(0.5)
    splash.visible = False
    page.update()


ft.app(target=main, assets_dir="assets")