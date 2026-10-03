import flet as ft
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS
import os, io, base64, time, urllib.parse

BASE = "#E8EEF6"
SH_D = "#BDC9DA"
SH_L = "#FFFFFF"
TEXT = "#2E3647"
MUTED = "#8A94A6"
PINK = "#FF7BAC"
ORANGE = "#FF9A6B"
BLUE = "#5B8DEF"
TEAL = "#2EC4B6"
AMBER = "#FFB547"
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


def clean_bytes(path):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def report_text(d):
    names = [("camera", "Camera / Phone"), ("time", "Date & Time"),
             ("location", "Location"), ("settings", "Camera Settings"),
             ("file", "File Info")]
    lines = ["Photo Meta report", ""]
    for key, title in names:
        rows = d.get(key) or {}
        if not rows:
            continue
        lines.append(title)
        for k, v in rows.items():
            lines.append(f"  {k}: {v}")
        lines.append("")
    return "\n".join(lines).strip()


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
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = BASE
    page.padding = 0
    try:
        page.appbar = ft.AppBar(
            toolbar_height=0, bgcolor=BASE, elevation=0,
            system_overlay_style=ft.SystemOverlayStyle(
                status_bar_color=BASE,
                status_bar_icon_brightness=ft.Brightness.DARK,
            ),
        )
    except Exception:
        pass

    st = {"path": None, "data": None}
    W = ft.Colors.with_opacity
    box_w = (page.width or 380) - 40
    GRAD = ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right,
                             colors=[PINK, ORANGE])

    def neu(content=None, radius=24, padding=0, depth=8, **kw):
        return ft.Container(
            content=content, padding=padding, border_radius=radius, bgcolor=BASE,
            shadow=[
                ft.BoxShadow(blur_radius=depth * 2, offset=ft.Offset(depth, depth), color=SH_D),
                ft.BoxShadow(blur_radius=depth * 2, offset=ft.Offset(-depth, -depth), color=SH_L),
            ], **kw)

    def badge(icon, color, size=40):
        return neu(ft.Icon(icon, color=color, size=size * 0.5), radius=size / 2, depth=4,
                   width=size, height=size, alignment=ft.alignment.center)

    def toast(msg):
        page.open(ft.SnackBar(ft.Text(msg, color="white"), bgcolor=TEXT,
                              behavior=ft.SnackBarBehavior.FLOATING))

    preview = ft.Image(src_base64=TINY, width=300, height=300, fit=ft.ImageFit.CONTAIN)
    preview_box = neu(
        ft.Container(preview, border_radius=22, clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
        radius=28, padding=10, depth=10, visible=False)
    results = ft.Column(spacing=18)

    def gbtn(text, icon, on_click, width=260, visible=True, grad=True):
        fg = "white" if grad else TEXT
        icon_c = "white" if grad else PINK
        c = ft.Container(
            content=ft.Row(
                [ft.Icon(icon, color=icon_c, size=22),
                 ft.Text(text, size=16, weight=ft.FontWeight.W_600, color=fg)],
                alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            width=width, height=56, border_radius=28, visible=visible,
            ink=True, on_click=on_click,
        )
        if grad:
            c.gradient = GRAD
            c.shadow = ft.BoxShadow(blur_radius=24, color=W(0.5, PINK), offset=ft.Offset(0, 10))
        else:
            c.bgcolor = BASE
            c.shadow = [
                ft.BoxShadow(blur_radius=16, offset=ft.Offset(6, 6), color=SH_D),
                ft.BoxShadow(blur_radius=16, offset=ft.Offset(-6, -6), color=SH_L),
            ]
        return c

    def tile(label, icon, color, on_click):
        return neu(
            ft.Column([ft.Icon(icon, color=color, size=24),
                       ft.Text(label, size=12, color=TEXT, weight=ft.FontWeight.W_500)],
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                      alignment=ft.MainAxisAlignment.CENTER, spacing=6),
            radius=20, depth=6, expand=True, height=82, ink=True, on_click=on_click)

    def feature(label, sub, icon, color):
        return neu(
            ft.Column([badge(icon, color, 44),
                       ft.Text(label, size=15, weight=ft.FontWeight.W_700, color=TEXT),
                       ft.Text(sub, size=11, color=MUTED)],
                      spacing=4),
            radius=22, depth=8, padding=16, expand=True)

    def card(title, icon, color, rows):
        items = []
        for k, v in rows.items():
            if k == "Map":
                items.append(ft.TextButton(
                    content=ft.Row([ft.Icon(ft.Icons.MAP, size=18, color=PINK),
                                    ft.Text("Open in Google Maps", color=PINK)], tight=True),
                    url=v))
            else:
                items.append(ft.Row([
                    ft.Text(k, color=MUTED, size=13, width=110),
                    ft.Text(v, size=14, color=TEXT, expand=True, selectable=True)]))
        c = neu(
            ft.Column([
                ft.Row([badge(icon, color, 38),
                        ft.Text(title, size=16, weight=ft.FontWeight.W_700, color=TEXT)],
                       spacing=12),
                ft.Divider(height=1, color=SH_D),
                *items], spacing=10),
            radius=24, depth=8, padding=18,
            opacity=0, animate_opacity=400,
            offset=ft.Offset(0, 0.08),
            animate_offset=ft.Animation(400, ft.AnimationCurve.EASE_OUT))
        return c

    # ---------- pick / save ----------
    def on_pick(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        st["path"] = e.files[0].path
        st["data"] = None
        try:
            preview.src_base64 = make_preview(st["path"])
        except Exception:
            pass
        preview_box.visible = True
        done_btn.visible = change_btn.visible = back_btn.visible = True
        home_extra.visible = False
        select_btn.visible = False
        actions_wrap.visible = False
        results.controls.clear()
        page.update()

    def on_saved(e: ft.FilePickerResultEvent):
        if getattr(e, "path", None):
            toast(f"Saved: {e.path}")

    picker = ft.FilePicker(on_result=on_pick)
    saver = ft.FilePicker(on_result=on_saved)
    page.overlay.extend([picker, saver])

    def pick(e):
        picker.pick_files(file_type=ft.FilePickerFileType.IMAGE)

    def fallback_save(name, data):
        try:
            folder = "/storage/emulated/0/Pictures/PhotoMeta"
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
            toast("Saved in Pictures/PhotoMeta")
        except Exception as ex:
            toast(f"Could not save: {ex}")

    def remove_meta(e):
        if not st["path"]:
            return
        try:
            data = clean_bytes(st["path"])
        except Exception as ex:
            toast(f"Error: {ex}")
            return
        name = "clean_" + os.path.splitext(os.path.basename(st["path"]))[0] + ".jpg"
        try:
            saver.save_file(dialog_title="Save clean photo", file_name=name, src_bytes=data)
        except Exception:
            fallback_save(name, data)

    def copy_meta(e):
        if st["data"]:
            page.set_clipboard(report_text(st["data"]))
            toast("Copied to clipboard")

    def share_meta(e):
        if st["data"]:
            text = urllib.parse.quote(report_text(st["data"]))
            page.launch_url("https://wa.me/?text=" + text)

    def go_home(e):
        st["path"] = None
        st["data"] = None
        preview_box.visible = False
        done_btn.visible = change_btn.visible = back_btn.visible = False
        home_extra.visible = True
        select_btn.visible = True
        actions_wrap.visible = False
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
        st["data"] = d
        spec = [
            ("Camera / Phone", ft.Icons.PHONE_ANDROID, BLUE, d["camera"]),
            ("Date & Time", ft.Icons.SCHEDULE, PINK, d["time"]),
            ("Location", ft.Icons.LOCATION_ON, ORANGE, d["location"]),
            ("Camera Settings", ft.Icons.CAMERA_ALT, AMBER, d["settings"]),
            ("File Info", ft.Icons.INSERT_DRIVE_FILE, TEAL, d["file"]),
        ]
        cards = []
        for title, icon, color, rows in spec:
            if rows:
                cards.append(card(title, icon, color, rows))
            elif title == "Location":
                cards.append(card(title, icon, color, {"Status": "No location in this photo"}))
        results.controls = cards
        actions_wrap.visible = True
        page.update()
        for c in cards:
            time.sleep(0.1)
            c.opacity = 1
            c.offset = ft.Offset(0, 0)
            c.update()

    # ---------- widgets ----------
    back_btn = ft.Container(
        neu(ft.Icon(ft.Icons.ARROW_BACK, color=TEXT, size=20), radius=22, depth=5,
            width=44, height=44, alignment=ft.alignment.center, ink=True, on_click=go_home),
        visible=False, margin=ft.margin.only(bottom=10))
    select_btn = gbtn("Select Photo", ft.Icons.PHOTO_LIBRARY, pick)
    done_btn = gbtn("Done", ft.Icons.CHECK, show_result, width=160, visible=False)
    change_btn = gbtn("Change", ft.Icons.SWAP_HORIZ, pick, width=140, visible=False, grad=False)

    actions_wrap = ft.Container(
        ft.Row([
            tile("Copy", ft.Icons.CONTENT_COPY, BLUE, copy_meta),
            tile("Share", ft.Icons.SHARE, TEAL, share_meta),
            tile("Remove Meta", ft.Icons.SHIELD, PINK, remove_meta),
        ], spacing=14),
        width=box_w, visible=False, padding=ft.padding.symmetric(vertical=6),
    )

    hero = neu(
        ft.Container(
            ft.Icon(ft.Icons.IMAGE_SEARCH, size=62, color="white"),
            width=130, height=130, border_radius=65, alignment=ft.alignment.center,
            gradient=GRAD,
            shadow=ft.BoxShadow(blur_radius=26, color=W(0.5, PINK), offset=ft.Offset(0, 10))),
        radius=100, depth=14, width=200, height=200, alignment=ft.alignment.center,
        margin=ft.margin.only(top=18, bottom=26))

    grid = ft.Container(
        ft.Column([
            ft.Row([feature("Camera", "Brand & model", ft.Icons.CAMERA_ALT, BLUE),
                    feature("Date", "When it was taken", ft.Icons.SCHEDULE, PINK)], spacing=16),
            ft.Row([feature("GPS", "Where it was taken", ft.Icons.LOCATION_ON, ORANGE),
                    feature("Clean", "Remove metadata", ft.Icons.SHIELD, TEAL)], spacing=16),
        ], spacing=16),
        width=box_w)
    home_extra = ft.Column([hero, grid, ft.Container(height=14)],
                           horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    privacy = ft.Row(
        [ft.Icon(ft.Icons.LOCK_OUTLINE, size=14, color=MUTED),
         ft.Text("Photos never leave your phone", size=12, color=MUTED)],
        alignment=ft.MainAxisAlignment.CENTER, spacing=6)

    header = ft.Row([
        ft.Column([
            ft.Text("Photo Meta", size=30, weight=ft.FontWeight.W_800, color=TEXT),
            ft.Text("Discover the hidden story of every photo", size=12, color=MUTED),
        ], spacing=2, expand=True),
        badge(ft.Icons.IMAGE_SEARCH, PINK, 48),
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    body = ft.Column(
        [
            ft.Row([back_btn]),
            ft.Container(header, width=box_w),
            home_extra,
            ft.Row([preview_box], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=18),
            ft.Row([select_btn], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([done_btn, change_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=14),
            ft.Container(height=10),
            actions_wrap,
            ft.Container(height=6),
            ft.Container(results, width=box_w),
            ft.Container(height=14),
            privacy,
            ft.Container(height=24),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        scroll=ft.ScrollMode.AUTO, expand=True,
    )
    body_wrap = ft.Container(
        body, padding=20, expand=True, opacity=0, offset=ft.Offset(0, 0.04),
        animate_opacity=600, animate_offset=ft.Animation(600, ft.AnimationCurve.EASE_OUT),
    )

    # ---------- loading screen ----------
    logo = neu(
        ft.Image(src="icon.png", width=96, height=96, border_radius=24),
        radius=48, depth=12, width=150, height=150, alignment=ft.alignment.center,
        scale=0.85, opacity=0,
        animate_scale=ft.Animation(650, ft.AnimationCurve.EASE_IN_OUT),
        animate_opacity=600)
    line = ft.Container(
        height=5, width=40, border_radius=3, gradient=GRAD,
        animate=ft.Animation(1000, ft.AnimationCurve.EASE_IN_OUT))
    tag = ft.Text("Reading hidden details...", size=13, color=MUTED,
                  opacity=0, animate_opacity=500)
    splash = ft.Container(
        content=ft.Column(
            [logo, ft.Container(height=14), line, tag],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14),
        bgcolor=BASE, expand=True, alignment=ft.alignment.center, animate_opacity=500,
    )

    page.add(ft.Stack([
        ft.Container(expand=True, gradient=ft.LinearGradient(
            begin=ft.alignment.top_center, end=ft.alignment.bottom_center,
            colors=["#F3F7FC", BASE, "#DDE5F0"])),
        ft.SafeArea(body_wrap, expand=True),
        splash,
    ], expand=True))

    logo.opacity = 1
    logo.scale = 1
    page.update()
    time.sleep(0.6)
    tag.opacity = 1
    logo.scale = 1.06
    line.width = 170
    page.update()
    time.sleep(1.0)
    logo.scale = 1
    page.update()
    time.sleep(0.3)
    splash.opacity = 0
    body_wrap.opacity = 1
    body_wrap.offset = ft.Offset(0, 0)
    page.update()
    time.sleep(0.5)
    splash.visible = False
    page.update()


ft.app(target=main, assets_dir="assets")