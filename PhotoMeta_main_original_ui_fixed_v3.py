import flet as ft
from PIL import Image, ImageOps
import os, io, re, base64, time, hashlib, urllib.parse

# PhotoMeta 2.0 metadata engine
from metadata_engine import read_metadata as engine_read_metadata, metadata_to_json

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
RED = "#E5484D"

PHONES = {"2411DRN47I": "Redmi 14C 5G"}
TINY = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
MAGIC = b"PMS1"


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


def report_text(d):
    names = [
        ("camera", "Camera / Phone"),
        ("time", "Date & Time"),
        ("location", "Location"),
        ("settings", "Camera Settings"),
        ("advanced", "Advanced"),
        ("file", "File Info"),
        ("xmp", "XMP"),
        ("png", "PNG Metadata"),
        ("privacy", "Privacy"),
        ("hash", "Hashes"),
    ]

    lines = ["Photo Meta report", ""]

    for key, title in names:
        rows = d.get(key) or {}
        if not rows:
            continue

        lines.append(title)

        for k, v in rows.items():
            if isinstance(v, (dict, list)):
                v = str(v)
            lines.append(f"  {k}: {v}")

        lines.append("")

    return "\n".join(lines).strip()


def read_metadata(path):
    """
    Compatibility wrapper.
    The actual metadata reading is now handled by metadata_engine.py.
    """
    return engine_read_metadata(path)


def make_output_name(prefix, path, ext):
    base = os.path.splitext(os.path.basename(path))[0]
    stamp = time.strftime("%H%M%S")
    return f"{prefix}_{base}_{stamp}.{ext}"


def clean_bytes(path, mode="all"):
    """
    PhotoMeta 2.0 cleaning.
    Current step keeps the existing JPEG output behaviour.
    Format-preserving cleaning will be upgraded in the next phase.
    """
    img = ImageOps.exif_transpose(Image.open(path))
    exif = img.getexif()
    img = img.convert("RGB")

    buf = io.BytesIO()

    if mode == "gps":
        try:
            if 0x8825 in exif:
                del exif[0x8825]
        except Exception:
            pass

        img.save(buf, "JPEG", quality=95, exif=exif)
    else:
        img.save(buf, "JPEG", quality=95)

    return buf.getvalue()


def edit_bytes(path, fields):
    img = ImageOps.exif_transpose(Image.open(path))
    exif = img.getexif()
    img = img.convert("RGB")

    tags = {
        "Author": 0x013B,
        "Copyright": 0x8298,
        "Description": 0x010E,
        "Make": 0x010F,
        "Model": 0x0110,
    }

    for k, tag in tags.items():
        v = (fields.get(k) or "").strip()

        if v:
            exif[tag] = v

    date = (fields.get("Date") or "").strip()

    if date:
        if re.match(r"^\d{4}-\d{2}-\d{2}", date):
            date = date[:10].replace("-", ":") + date[10:]

        if not re.match(
            r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$",
            date,
        ):
            raise ValueError(
                "Date format: YYYY-MM-DD HH:MM:SS"
            )

        exif[0x0132] = date

        try:
            sub = exif.get_ifd(0x8769)
            sub[0x9003] = date
            sub[0x9004] = date
        except Exception:
            pass

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95, exif=exif)

    return buf.getvalue()


def shrink_bytes(path, max_side, strip=True):
    img = ImageOps.exif_transpose(Image.open(path))
    exif = img.getexif()
    img = img.convert("RGB")

    img.thumbnail((max_side, max_side))

    buf = io.BytesIO()

    if strip:
        img.save(
            buf,
            "JPEG",
            quality=85,
            optimize=True,
        )
    else:
        img.save(
            buf,
            "JPEG",
            quality=85,
            optimize=True,
            exif=exif,
        )

    return buf.getvalue()


def flat_meta(d):
    out = {}

    for sec in (
        "camera",
        "time",
        "location",
        "settings",
        "advanced",
        "file",
        "xmp",
        "png",
        "privacy",
        "hash",
    ):
        for k, v in (d.get(sec) or {}).items():
            if k == "Map":
                continue

            if isinstance(v, (dict, list)):
                v = str(v)

            out[f"{sec}.{k}"] = v

    return out


def compare_rows(a, b):
    fa = flat_meta(a)
    fb = flat_meta(b)

    diff = []
    same = 0

    for k in list(fa) + [
        k for k in fb
        if k not in fa
    ]:
        va = fa.get(k, "-")
        vb = fb.get(k, "-")

        if va == vb:
            same += 1
        else:
            diff.append((k, va, vb))

    return diff, same


def _derive(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        20000,
        32,
    )


def _keystream(key, n):
    out = bytearray()
    c = 0

    while len(out) < n:
        out += hashlib.sha256(
            key + c.to_bytes(4, "big")
        ).digest()
        c += 1

    return bytes(out[:n])


def build_payload(message, password):
    data = message.encode("utf-8")

    if password:
        salt = os.urandom(16)
        key = _derive(password, salt)
        check = hashlib.sha256(
            key + b"chk"
        ).digest()[:4]

        ks = _keystream(key, len(data))

        body = (
            salt
            + check
            + bytes(
                a ^ b
                for a, b in zip(data, ks)
            )
        )

        flag = 1
    else:
        body = data
        flag = 0

    return (
        MAGIC
        + bytes([flag])
        + len(body).to_bytes(4, "big")
        + body
    )


def embed_bytes(path, message, password):
    img = ImageOps.exif_transpose(
        Image.open(path)
    ).convert("RGB")

    img.thumbnail((3000, 3000))

    payload = build_payload(
        message,
        password,
    )

    w, h = img.size

    if len(payload) * 8 > w * h * 3:
        raise ValueError(
            "Message is too long for this photo"
        )

    pix = img.load()

    bits = (
        (byte >> (7 - i)) & 1
        for byte in payload
        for i in range(8)
    )

    done = False

    for y in range(h):
        for x in range(w):
            vals = list(pix[x, y])

            for c in range(3):
                bit = next(bits, None)

                if bit is None:
                    done = True
                    break

                vals[c] = (
                    vals[c] & ~1
                ) | bit

            pix[x, y] = tuple(vals)

            if done:
                break

        if done:
            break

    buf = io.BytesIO()
    img.save(buf, "PNG")

    return buf.getvalue()


def extract_text(path, password):
    img = Image.open(path).convert("RGB")

    pix = img.load()
    w, h = img.size

    def bit_stream():
        for y in range(h):
            for x in range(w):
                p = pix[x, y]

                yield p[0] & 1
                yield p[1] & 1
                yield p[2] & 1

    it = bit_stream()

    def read_bytes(n):
        out = bytearray()

        for _ in range(n):
            v = 0

            for _ in range(8):
                v = (
                    v << 1
                ) | next(it)

            out.append(v)

        return bytes(out)

    try:
        head = read_bytes(9)

        if head[:4] != MAGIC:
            raise ValueError(
                "No hidden message found in this photo"
            )

        flag = head[4]
        length = int.from_bytes(
            head[5:9],
            "big",
        )

        if length > w * h * 3 // 8:
            raise ValueError(
                "No hidden message found in this photo"
            )

        body = read_bytes(length)

    except StopIteration:
        raise ValueError(
            "No hidden message found in this photo"
        )

    if flag == 1:
        if not password:
            raise ValueError(
                "This message needs a password"
            )

        salt = body[:16]
        check = body[16:20]
        cipher = body[20:]

        key = _derive(
            password,
            salt,
        )

        if hashlib.sha256(
            key + b"chk"
        ).digest()[:4] != check:
            raise ValueError(
                "Wrong password"
            )

        ks = _keystream(
            key,
            len(cipher),
        )

        data = bytes(
            a ^ b
            for a, b in zip(cipher, ks)
        )

    else:
        data = body

    return data.decode(
        "utf-8",
        errors="replace",
    )


def main(page: ft.Page):
    page.title = "Photo Meta"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = BASE
    page.padding = 0

    try:
        page.theme = ft.Theme(
            scrollbar_theme=ft.ScrollbarTheme(
                thumb_visibility=False,
                track_visibility=False,
                thickness=0,
            )
        )
    except Exception:
        pass

    try:
        page.appbar = ft.AppBar(
            toolbar_height=0,
            bgcolor=BASE,
            elevation=0,
            system_overlay_style=ft.SystemOverlayStyle(
                status_bar_color=BASE,
                status_bar_icon_brightness=ft.Brightness.DARK,
            ),
        )
    except Exception:
        pass

    st = {
        "path": None,
        "data": None,
        "mode": "inspect",
    }

    W = ft.Colors.with_opacity

    box_w = (page.width or 380) - 40

    GRAD = ft.LinearGradient(
        begin=ft.alignment.top_left,
        end=ft.alignment.bottom_right,
        colors=[PINK, ORANGE],
    )

    def neu(
        content=None,
        radius=24,
        padding=0,
        depth=8,
        **kw,
    ):
        return ft.Container(
            content=content,
            padding=padding,
            border_radius=radius,
            bgcolor=BASE,
            shadow=[
                ft.BoxShadow(
                    blur_radius=depth * 2,
                    offset=ft.Offset(
                        depth,
                        depth,
                    ),
                    color=SH_D,
                ),
                ft.BoxShadow(
                    blur_radius=depth * 2,
                    offset=ft.Offset(
                        -depth,
                        -depth,
                    ),
                    color=SH_L,
                ),
            ],
            **kw,
        )

    def badge(icon, color, size=40):
        return neu(
            ft.Icon(
                icon,
                color=color,
                size=size * 0.5,
            ),
            radius=size / 2,
            depth=4,
            width=size,
            height=size,
            alignment=ft.alignment.center,
        )

    def toast(msg):
        page.open(
            ft.SnackBar(
                ft.Text(
                    msg,
                    color="white",
                ),
                bgcolor=TEXT,
                behavior=ft.SnackBarBehavior.FLOATING,
            )
        )

    preview = ft.Image(
        src_base64=TINY,
        width=300,
        height=300,
        fit=ft.ImageFit.CONTAIN,
    )

    preview_box = neu(
        ft.Container(
            preview,
            border_radius=22,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        ),
        radius=28,
        padding=10,
        depth=10,
        visible=False,
    )

    results = ft.Column(spacing=18)

    def gbtn(
        text,
        icon,
        on_click,
        width=260,
        visible=True,
        grad=True,
    ):
        fg = "white" if grad else TEXT
        icon_c = "white" if grad else PINK

        c = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        icon,
                        color=icon_c,
                        size=22,
                    ),
                    ft.Text(
                        text,
                        size=16,
                        weight=ft.FontWeight.W_600,
                        color=fg,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=10,
            ),
            width=width,
            height=56,
            border_radius=28,
            visible=visible,
            ink=True,
            on_click=on_click,
        )

        if grad:
            c.gradient = GRAD

            c.shadow = ft.BoxShadow(
                blur_radius=24,
                color=W(0.5, PINK),
                offset=ft.Offset(0, 10),
            )
        else:
            c.bgcolor = BASE

            c.shadow = [
                ft.BoxShadow(
                    blur_radius=16,
                    offset=ft.Offset(6, 6),
                    color=SH_D,
                ),
                ft.BoxShadow(
                    blur_radius=16,
                    offset=ft.Offset(-6, -6),
                    color=SH_L,
                ),
            ]

        return c

    def tile(label, icon, color, on_click):
        return neu(
            ft.Column(
                [
                    ft.Icon(
                        icon,
                        color=color,
                        size=24,
                    ),
                    ft.Text(
                        label,
                        size=12,
                        color=TEXT,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=6,
            ),
            radius=20,
            depth=6,
            expand=True,
            height=82,
            ink=True,
            on_click=on_click,
        )

    def feature(
        label,
        sub,
        icon,
        color,
        on_click,
    ):
        return neu(
            ft.Column(
                [
                    badge(
                        icon,
                        color,
                        42,
                    ),
                    ft.Text(
                        label,
                        size=15,
                        weight=ft.FontWeight.W_700,
                        color=TEXT,
                    ),
                    ft.Text(
                        sub,
                        size=11,
                        color=MUTED,
                    ),
                ],
                spacing=4,
            ),
            radius=22,
            depth=8,
            padding=14,
            expand=True,
            ink=True,
            on_click=on_click,
        )

    def card(
        title,
        icon,
        color,
        rows,
    ):
        items = []

        for k, v in rows.items():
            if k == "Map":
                items.append(
                    ft.TextButton(
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.MAP,
                                    size=18,
                                    color=PINK,
                                ),
                                ft.Text(
                                    "Open in Google Maps",
                                    color=PINK,
                                ),
                            ],
                            tight=True,
                        ),
                        url=v,
                    )
                )
            else:
                if isinstance(v, (dict, list)):
                    v = str(v)

                items.append(
                    ft.Row(
                        [
                            ft.Text(
                                k,
                                color=MUTED,
                                size=13,
                                width=110,
                            ),
                            ft.Text(
                                str(v),
                                size=14,
                                color=TEXT,
                                expand=True,
                                selectable=True,
                            ),
                        ]
                    )
                )

        return neu(
            ft.Column(
                [
                    ft.Row(
                        [
                            badge(
                                icon,
                                color,
                                38,
                            ),
                            ft.Text(
                                title,
                                size=16,
                                weight=ft.FontWeight.W_700,
                                color=TEXT,
                            ),
                        ],
                        spacing=12,
                    ),
                    ft.Divider(
                        height=1,
                        color=SH_D,
                    ),
                    *items,
                ],
                spacing=10,
            ),
            radius=24,
            depth=8,
            padding=18,
            opacity=0,
            animate_opacity=400,
            offset=ft.Offset(0, 0.08),
            animate_offset=ft.Animation(
                400,
                ft.AnimationCurve.EASE_OUT,
            ),
        )

    def warn_card(path):
        return neu(
            ft.Column(
                [
                    ft.Row(
                        [
                            badge(
                                ft.Icons.WARNING_AMBER_ROUNDED,
                                RED,
                                38,
                            ),
                            ft.Text(
                                "Location is inside this photo",
                                size=15,
                                weight=ft.FontWeight.W_700,
                                color=RED,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                    ),
                    ft.Text(
                        "Anyone you send it to can find where it was taken.",
                        size=13,
                        color=TEXT,
                    ),
                    ft.TextButton(
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.SHIELD,
                                    size=18,
                                    color=RED,
                                ),
                                ft.Text(
                                    "Remove location now",
                                    color=RED,
                                ),
                            ],
                            tight=True,
                        ),
                        on_click=lambda e: do_clean(
                            [path],
                            "gps",
                        ),
                    ),
                ],
                spacing=8,
            ),
            radius=24,
            depth=8,
            padding=18,
            opacity=0,
            animate_opacity=400,
            offset=ft.Offset(0, 0.08),
            animate_offset=ft.Animation(
                400,
                ft.AnimationCurve.EASE_OUT,
            ),
        )

    def privacy_card(data):
        privacy = data.get("privacy") or {}
        risk = privacy.get("Risk", "NONE")
        detected = privacy.get("Detected") or []

        if risk == "HIGH":
            color = RED
        elif risk == "MEDIUM":
            color = AMBER
        elif risk == "LOW":
            color = ORANGE
        else:
            color = TEAL

        if detected:
            text = ", ".join(detected)
        else:
            text = "No obvious privacy-sensitive metadata detected"

        return neu(
            ft.Column(
                [
                    ft.Row(
                        [
                            badge(
                                ft.Icons.SECURITY,
                                color,
                                38,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Privacy Risk",
                                        size=16,
                                        weight=ft.FontWeight.W_700,
                                        color=TEXT,
                                    ),
                                    ft.Text(
                                        risk,
                                        size=12,
                                        weight=ft.FontWeight.W_700,
                                        color=color,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                    ),
                    ft.Text(
                        text,
                        size=13,
                        color=TEXT,
                    ),
                ],
                spacing=8,
            ),
            radius=24,
            depth=8,
            padding=18,
            opacity=0,
            animate_opacity=400,
            offset=ft.Offset(0, 0.08),
            animate_offset=ft.Animation(
                400,
                ft.AnimationCurve.EASE_OUT,
            ),
        )

    def dialog(
        title,
        content,
        actions,
    ):
        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=BASE,
            title=ft.Text(
                title,
                color=TEXT,
                weight=ft.FontWeight.W_700,
            ),
            content=content,
            actions=actions,
            shape=ft.RoundedRectangleBorder(
                radius=24
            ),
        )

        page.open(dlg)

        return dlg

    def dbtn(
        text,
        on_click,
        primary=False,
    ):
        return ft.TextButton(
            text,
            on_click=on_click,
            style=ft.ButtonStyle(
                color=PINK if primary else MUTED
            ),
        )

    def field(
        label,
        hint=None,
        **kw,
    ):
        return ft.TextField(
            label=label,
            hint_text=hint,
            color=TEXT,
            border_radius=14,
            border_color=SH_D,
            focused_border_color=PINK,
            label_style=ft.TextStyle(
                color=MUTED
            ),
            hint_style=ft.TextStyle(
                color=SH_D
            ),
            text_size=14,
            **kw,
        )

    # -----------------------------------------------------
    # Clean
    # -----------------------------------------------------

    def do_clean(paths, mode):
        items = []
        bad = 0
        for p in paths:
            try:
                data = clean_bytes(p, mode)
                prefix = "clean" if mode == "all" else "nogps"
                items.append((data, make_output_name(prefix, p, "jpg"), "jpg"))
            except Exception:
                bad += 1
        if items:
            page.run_task(save_many, items, "Save cleaned photo")
        if bad:
            toast(f"{bad} photo(s) could not be processed")

    def ask_clean(paths):
        def choose(mode):
            def h(e):
                page.close(dlg)
                do_clean(
                    paths,
                    mode,
                )

            return h

        dlg = dialog(
            f"Clean {len(paths)} photo(s)",
            ft.Text(
                "What should be removed? "
                "A new copy is saved, your original stays untouched.",
                color=TEXT,
                size=14,
            ),
            [
                dbtn(
                    "Cancel",
                    lambda e: page.close(dlg),
                ),
                dbtn(
                    "Location only",
                    choose("gps"),
                ),
                dbtn(
                    "Everything",
                    choose("all"),
                    primary=True,
                ),
            ],
        )

    # -----------------------------------------------------
    # Edit
    # -----------------------------------------------------

    def open_edit(path):
        try:
            d = read_metadata(path)
        except Exception:
            d = {
                "camera": {},
                "time": {},
            }

        cam = d.get("camera", {})
        tm = d.get("time", {})

        f_author = field(
            "Author",
            cam.get("Author"),
        )

        f_copy = field(
            "Copyright",
            cam.get("Copyright"),
        )

        f_desc = field(
            "Description",
            cam.get("Description"),
        )

        # IMPORTANT:
        # No fake/default date anymore.
        f_date = field(
            "Date taken",
            tm.get("Taken on"),
            hint="YYYY-MM-DD HH:MM:SS",
        )

        f_make = field(
            "Brand",
            cam.get("Brand"),
        )

        f_model = field(
            "Model",
            cam.get("Model"),
        )

        def save(e):
            fields = {
                "Author": f_author.value,
                "Copyright": f_copy.value,
                "Description": f_desc.value,
                "Date": f_date.value,
                "Make": f_make.value,
                "Model": f_model.value,
            }

            if not any(
                (v or "").strip()
                for v in fields.values()
            ):
                toast(
                    "Fill at least one field"
                )
                return

            try:
                data = edit_bytes(
                    path,
                    fields,
                )

                save_one_task(data, make_output_name("edited", path, "jpg"), "jpg", "Save edited photo")

            except Exception as ex:
                toast(str(ex))
                return

            page.close(dlg)

            toast(
                "Edited copy saved in Pictures/PhotoMeta"
            )

        dlg = dialog(
            "Edit metadata",
            ft.Container(
                ft.Column(
                    [
                        ft.Text(
                            "Blank fields keep their current value. "
                            "A new copy is saved.",
                            size=12,
                            color=MUTED,
                        ),
                        f_author,
                        f_copy,
                        f_desc,
                        f_date,
                        f_make,
                        f_model,
                    ],
                    tight=True,
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=320,
                height=380,
            ),
            [
                dbtn(
                    "Cancel",
                    lambda e: page.close(dlg),
                ),
                dbtn(
                    "Save copy",
                    save,
                    primary=True,
                ),
            ],
        )

    # -----------------------------------------------------
    # JSON export
    # -----------------------------------------------------

    def export_json():
        if not st["data"] or not st["path"]:
            toast("Inspect a photo first")
            return

        try:
            data = metadata_to_json(
                st["data"],
                pretty=True,
            )

            save_one_task(data.encode("utf-8"), make_output_name("metadata", st["path"], "json"), "json", "Save metadata JSON")

            toast(
                "JSON metadata saved in Pictures/PhotoMeta"
            )

        except Exception as ex:
            toast(str(ex))

    # -----------------------------------------------------
    # Hide / Reveal
    # -----------------------------------------------------

    def open_hide(path):
        f_msg = field(
            "Secret message",
            multiline=True,
            min_lines=3,
            max_lines=6,
        )

        f_pw = field(
            "Password (optional)",
            password=True,
            can_reveal_password=True,
        )

        def hide(e):
            msg = (
                f_msg.value or ""
            ).strip()

            if not msg:
                toast(
                    "Write a message first"
                )
                return

            page.close(dlg)
            toast(
                "Hiding message, please wait..."
            )

            try:
                data = embed_bytes(
                    path,
                    msg,
                    f_pw.value or "",
                )

                save_one_task(data, make_output_name("secret", path, "png"), "png", "Save secret photo")

            except Exception as ex:
                toast(str(ex))
                return

            toast(
                "Saved in Pictures/PhotoMeta. "
                "Send it as a File, not as a photo."
            )

        dlg = dialog(
            "Hide a message",
            ft.Container(
                ft.Column(
                    [
                        f_msg,
                        f_pw,
                    ],
                    tight=True,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=320,
            ),
            [
                dbtn(
                    "Cancel",
                    lambda e: page.close(dlg),
                ),
                dbtn(
                    "Hide",
                    hide,
                    primary=True,
                ),
            ],
        )

    def open_reveal(path):
        f_pw = field(
            "Password (if any)",
            password=True,
            can_reveal_password=True,
        )

        def reveal(e):
            pw = f_pw.value or ""

            page.close(dlg)

            try:
                text = extract_text(
                    path,
                    pw,
                )

            except Exception as ex:
                toast(str(ex))
                return

            def copy_it(ev):
                page.set_clipboard(text)
                toast("Message copied")

            out = dialog(
                "Hidden message",
                ft.Container(
                    ft.Column(
                        [
                            ft.Text(
                                text,
                                size=15,
                                color=TEXT,
                                selectable=True,
                            )
                        ],
                        tight=True,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    width=320,
                ),
                [
                    dbtn(
                        "Copy",
                        copy_it,
                    ),
                    dbtn(
                        "Close",
                        lambda ev: page.close(out),
                        primary=True,
                    ),
                ],
            )

        dlg = dialog(
            "Reveal hidden message",
            ft.Container(
                ft.Column(
                    [f_pw],
                    tight=True,
                ),
                width=320,
            ),
            [
                dbtn(
                    "Cancel",
                    lambda e: page.close(dlg),
                ),
                dbtn(
                    "Reveal",
                    reveal,
                    primary=True,
                ),
            ],
        )

    # -----------------------------------------------------
    # Shrink
    # -----------------------------------------------------

    def ask_shrink(paths):
        rg = ft.RadioGroup(
            value="1600",
            content=ft.Column(
                [
                    ft.Radio(
                        value="1080",
                        label="Small - 1080 px (fast to send)",
                    ),
                    ft.Radio(
                        value="1600",
                        label="Medium - 1600 px",
                    ),
                    ft.Radio(
                        value="2400",
                        label="Large - 2400 px",
                    ),
                ],
                tight=True,
            ),
        )

        chk = ft.Checkbox(
            label="Also remove metadata",
            value=True,
            active_color=PINK,
        )

        def go(e):
            size = int(
                rg.value or "1600"
            )

            strip = bool(chk.value)

            page.close(dlg)

            toast(
                "Working, please wait..."
            )

            ok = 0
            bad = 0
            before = 0
            after = 0

            for p in paths:
                try:
                    data = shrink_bytes(
                        p,
                        size,
                        strip,
                    )

                    save_one_task(data, make_output_name("small", p, "jpg"), "jpg", "Save smaller photo")

                    before += os.path.getsize(
                        p
                    )

                    after += len(data)

                    ok += 1

                except Exception:
                    bad += 1

            msg = (
                f"{ok} photo(s) saved: "
                f"{before // 1024} KB to "
                f"{after // 1024} KB"
            )

            if bad:
                msg += f" ({bad} failed)"

            toast(msg)

        dlg = dialog(
            f"Shrink {len(paths)} photo(s)",
            ft.Container(
                ft.Column(
                    [
                        ft.Text(
                            "Makes a smaller copy that is easier to send. "
                            "Original stays untouched.",
                            size=13,
                            color=MUTED,
                        ),
                        rg,
                        chk,
                    ],
                    tight=True,
                    spacing=10,
                ),
                width=320,
            ),
            [
                dbtn(
                    "Cancel",
                    lambda e: page.close(dlg),
                ),
                dbtn(
                    "Shrink",
                    go,
                    primary=True,
                ),
            ],
        )

    # -----------------------------------------------------
    # Compare
    # -----------------------------------------------------

    def compare(paths):
        if len(paths) < 2:
            toast(
                "Select 2 photos to compare"
            )
            return

        try:
            diff, same = compare_rows(
                read_metadata(paths[0]),
                read_metadata(paths[1]),
            )

        except Exception as ex:
            toast(
                f"Error: {ex}"
            )
            return

        items = [
            ft.Text(
                f"{len(diff)} different, {same} same",
                size=13,
                color=MUTED,
            )
        ]

        if len(paths) > 2:
            items.append(
                ft.Text(
                    "Only the first 2 photos were compared.",
                    size=12,
                    color=MUTED,
                )
            )

        if not diff:
            items.append(
                ft.Text(
                    "The metadata of both photos is identical.",
                    size=14,
                    color=TEXT,
                )
            )

        for k, va, vb in diff:
            items.append(
                ft.Column(
                    [
                        ft.Text(
                            k,
                            size=13,
                            weight=ft.FontWeight.W_700,
                            color=TEXT,
                        ),
                        ft.Text(
                            f"Photo 1: {va}",
                            size=13,
                            color=BLUE,
                            selectable=True,
                        ),
                        ft.Text(
                            f"Photo 2: {vb}",
                            size=13,
                            color=ORANGE,
                            selectable=True,
                        ),
                    ],
                    spacing=2,
                )
            )

        dlg = dialog(
            "Compare photos",
            ft.Container(
                ft.Column(
                    items,
                    tight=True,
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=320,
                height=min(
                    420,
                    80 + len(diff) * 80,
                ),
            ),
            [
                dbtn(
                    "Close",
                    lambda e: page.close(dlg),
                    primary=True,
                )
            ],
        )

    # -----------------------------------------------------
    # Locate
    # -----------------------------------------------------

    def locate(path):
        try:
            d = read_metadata(path)

        except Exception as ex:
            toast(
                f"Error: {ex}"
            )
            return

        url = (
            d.get("location", {})
            .get("Map")
        )

        if url:
            toast("Opening map...")
            page.launch_url(url)
        else:
            toast(
                "No location in this photo"
            )

    # -----------------------------------------------------
    # Picking
    # -----------------------------------------------------

    def on_pick(e: ft.FilePickerResultEvent):
        if not e.files:
            return

        paths = [
            f.path
            for f in e.files
            if f.path
        ]

        if not paths:
            return

        mode = st["mode"]

        if mode == "clean":
            ask_clean(paths)
            return

        if mode == "shrink":
            ask_shrink(paths)
            return

        if mode == "compare":
            compare(paths)
            return

        path = paths[0]

        if mode == "locate":
            locate(path)
            return

        if mode == "edit":
            open_edit(path)
            return

        if mode == "hide":
            open_hide(path)
            return

        if mode == "reveal":
            open_reveal(path)
            return

        st["path"] = path
        st["data"] = None

        try:
            preview.src_base64 = make_preview(
                path
            )
        except Exception:
            pass

        preview_box.visible = True

        done_btn.visible = True
        change_btn.visible = True
        back_btn.visible = True

        home_extra.visible = False
        actions_wrap.visible = False

        results.controls.clear()

        page.update()

    picker = ft.FilePicker(
        on_result=on_pick
    )

    save_picker = ft.FilePicker()

    page.overlay.append(picker)
    page.overlay.append(save_picker)

    async def save_one(data, filename, extension, label):
        try:
            result = await save_picker.save_file(
                dialog_title=label,
                file_name=filename,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=[extension],
                src_bytes=data,
            )
            toast(f"Saved: {filename}" if result else "Save cancelled")
        except Exception as ex:
            toast(f"Save error: {ex}")

    def save_one_task(data, filename, extension, label):
        page.run_task(save_one, data, filename, extension, label)

    async def save_many(items, label):
        saved = 0
        for data, filename, extension in items:
            try:
                result = await save_picker.save_file(
                    dialog_title=label,
                    file_name=filename,
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=[extension],
                    src_bytes=data,
                )
                if result:
                    saved += 1
            except Exception as ex:
                toast(f"Save error: {ex}")
                break
        toast(f"Saved {saved} file(s)" if saved else "Save cancelled")

    def start_pick(mode):
        st["mode"] = mode

        if mode == "reveal":
            picker.pick_files(
                file_type=ft.FilePickerFileType.IMAGE
            )
        else:
            picker.pick_files(
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=(
                    mode in (
                        "clean",
                        "shrink",
                        "compare",
                    )
                ),
            )

    def copy_meta(e):
        if st["data"]:
            page.set_clipboard(
                report_text(
                    st["data"]
                )
            )

            toast(
                "Copied to clipboard"
            )

    def share_meta(e):
        if st["data"]:
            text = urllib.parse.quote(
                report_text(
                    st["data"]
                )
            )

            page.launch_url(
                "https://wa.me/?text="
                + text
            )

    def go_home(e):
        st["path"] = None
        st["data"] = None

        preview_box.visible = False

        done_btn.visible = False
        change_btn.visible = False
        back_btn.visible = False

        home_extra.visible = True
        actions_wrap.visible = False

        results.controls.clear()

        page.update()

    def show_result(e):
        results.controls.clear()

        try:
            d = read_metadata(
                st["path"]
            )

        except Exception as ex:
            results.controls.append(
                ft.Text(
                    f"Error: {ex}",
                    color="red",
                )
            )

            page.update()
            return

        st["data"] = d

        spec = [
            (
                "Camera / Phone",
                ft.Icons.PHONE_ANDROID,
                BLUE,
                d.get("camera", {}),
            ),
            (
                "Date & Time",
                ft.Icons.SCHEDULE,
                PINK,
                d.get("time", {}),
            ),
            (
                "Location",
                ft.Icons.LOCATION_ON,
                ORANGE,
                d.get("location", {}),
            ),
            (
                "Camera Settings",
                ft.Icons.CAMERA_ALT,
                AMBER,
                d.get("settings", {}),
            ),
            (
                "Advanced",
                ft.Icons.TUNE,
                BLUE,
                d.get("advanced", {}),
            ),
            (
                "File Info",
                ft.Icons.INSERT_DRIVE_FILE,
                TEAL,
                d.get("file", {}),
            ),
            (
                "XMP",
                ft.Icons.DATA_OBJECT,
                PINK,
                d.get("xmp", {}),
            ),
            (
                "PNG Metadata",
                ft.Icons.IMAGE,
                ORANGE,
                d.get("png", {}),
            ),
            (
                "Hashes",
                ft.Icons.TAG,
                TEAL,
                d.get("hash", {}),
            ),
        ]

        cards = []

        if (
            d.get("location", {})
            .get("Map")
        ):
            cards.append(
                warn_card(
                    st["path"]
                )
            )

        cards.append(
            privacy_card(d)
        )

        for title, icon, color, rows in spec:
            if rows:
                cards.append(
                    card(
                        title,
                        icon,
                        color,
                        rows,
                    )
                )

            elif title == "Location":
                cards.append(
                    card(
                        title,
                        icon,
                        color,
                        {
                            "Status":
                                "No location in this photo"
                        },
                    )
                )

        results.controls = cards

        actions_wrap.visible = True

        page.update()

        for c in cards:
            time.sleep(0.1)

            c.opacity = 1
            c.offset = ft.Offset(
                0,
                0,
            )

            c.update()

    # -----------------------------------------------------
    # Widgets
    # -----------------------------------------------------

    back_btn = ft.Container(
        neu(
            ft.Icon(
                ft.Icons.ARROW_BACK,
                color=TEXT,
                size=20,
            ),
            radius=22,
            depth=5,
            width=44,
            height=44,
            alignment=ft.alignment.center,
            ink=True,
            on_click=go_home,
        ),
        visible=False,
        margin=ft.margin.only(
            bottom=10
        ),
    )

    done_btn = gbtn(
        "Done",
        ft.Icons.CHECK,
        show_result,
        width=160,
        visible=False,
    )

    change_btn = gbtn(
        "Change",
        ft.Icons.SWAP_HORIZ,
        lambda e: start_pick(
            "inspect"
        ),
        width=140,
        visible=False,
        grad=False,
    )

    actions_wrap = ft.Container(
        ft.Row(
            [
                tile(
                    "Copy",
                    ft.Icons.CONTENT_COPY,
                    BLUE,
                    copy_meta,
                ),
                tile(
                    "Share",
                    ft.Icons.SHARE,
                    TEAL,
                    share_meta,
                ),
                tile(
                    "JSON",
                    ft.Icons.DATA_OBJECT,
                    BLUE,
                    lambda e: export_json(),
                ),
                tile(
                    "Clean",
                    ft.Icons.SHIELD,
                    PINK,
                    lambda e: ask_clean(
                        [st["path"]]
                    ),
                ),
                tile(
                    "Edit",
                    ft.Icons.EDIT,
                    AMBER,
                    lambda e: open_edit(
                        st["path"]
                    ),
                ),
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=box_w,
        visible=False,
        padding=ft.padding.symmetric(
            vertical=6
        ),
    )

    hero = neu(
        ft.Container(
            ft.Icon(
                ft.Icons.IMAGE_SEARCH,
                size=54,
                color="white",
            ),
            width=110,
            height=110,
            border_radius=55,
            alignment=ft.alignment.center,
            gradient=GRAD,
            shadow=ft.BoxShadow(
                blur_radius=26,
                color=W(0.5, PINK),
                offset=ft.Offset(
                    0,
                    10,
                ),
            ),
        ),
        radius=85,
        depth=12,
        width=170,
        height=170,
        alignment=ft.alignment.center,
        margin=ft.margin.only(
            top=12,
            bottom=22,
        ),
    )

    grid = ft.Container(
        ft.Column(
            [
                ft.Row(
                    [
                        feature(
                            "Inspect",
                            "See all metadata",
                            ft.Icons.IMAGE_SEARCH,
                            BLUE,
                            lambda e: start_pick(
                                "inspect"
                            ),
                        ),
                        feature(
                            "Locate",
                            "Open spot on map",
                            ft.Icons.LOCATION_ON,
                            ORANGE,
                            lambda e: start_pick(
                                "locate"
                            ),
                        ),
                    ],
                    spacing=16,
                ),
                ft.Row(
                    [
                        feature(
                            "Clean",
                            "Remove metadata",
                            ft.Icons.SHIELD,
                            TEAL,
                            lambda e: start_pick(
                                "clean"
                            ),
                        ),
                        feature(
                            "Edit",
                            "Change or add info",
                            ft.Icons.EDIT,
                            AMBER,
                            lambda e: start_pick(
                                "edit"
                            ),
                        ),
                    ],
                    spacing=16,
                ),
                ft.Row(
                    [
                        feature(
                            "Hide",
                            "Secret in a photo",
                            ft.Icons.LOCK,
                            PINK,
                            lambda e: start_pick(
                                "hide"
                            ),
                        ),
                        feature(
                            "Reveal",
                            "Read hidden secret",
                            ft.Icons.VISIBILITY,
                            BLUE,
                            lambda e: start_pick(
                                "reveal"
                            ),
                        ),
                    ],
                    spacing=16,
                ),
                ft.Row(
                    [
                        feature(
                            "Shrink",
                            "Smaller, easy to send",
                            ft.Icons.COMPRESS,
                            ORANGE,
                            lambda e: start_pick(
                                "shrink"
                            ),
                        ),
                        feature(
                            "Compare",
                            "Spot the differences",
                            ft.Icons.COMPARE,
                            TEAL,
                            lambda e: start_pick(
                                "compare"
                            ),
                        ),
                    ],
                    spacing=16,
                ),
            ],
            spacing=16,
        ),
        width=box_w,
        padding=ft.padding.only(
            right=2,
            bottom=12,
        ),
    )

    home_extra = ft.Column(
        [
            hero,
            grid,
            ft.Container(height=10),
        ],
        horizontal_alignment=(
            ft.CrossAxisAlignment.CENTER
        ),
    )

    privacy = ft.Row(
        [
            ft.Icon(
                ft.Icons.LOCK_OUTLINE,
                size=14,
                color=MUTED,
            ),
            ft.Text(
                "Photos never leave your phone",
                size=12,
                color=MUTED,
            ),
        ],
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=6,
    )

    header = ft.Row(
        [
            ft.Column(
                [
                    ft.Text(
                        "Photo Meta",
                        size=30,
                        weight=ft.FontWeight.W_800,
                        color=TEXT,
                    ),
                    ft.Text(
                        "Discover the hidden story of every photo",
                        size=12,
                        color=MUTED,
                    ),
                ],
                spacing=2,
                expand=True,
            ),
            badge(
                ft.Icons.IMAGE_SEARCH,
                PINK,
                48,
            ),
        ],
        vertical_alignment=(
            ft.CrossAxisAlignment.CENTER
        ),
    )

    body = ft.Column(
        [
            ft.Row([back_btn]),
            ft.Container(
                header,
                width=box_w,
            ),
            home_extra,
            ft.Row(
                [preview_box],
                alignment=(
                    ft.MainAxisAlignment.CENTER
                ),
            ),
            ft.Container(height=18),
            ft.Row(
                [done_btn, change_btn],
                alignment=(
                    ft.MainAxisAlignment.CENTER
                ),
                spacing=14,
            ),
            ft.Container(height=10),
            actions_wrap,
            ft.Container(height=6),
            ft.Container(
                results,
                width=box_w,
            ),
            ft.Container(height=14),
            privacy,
            ft.Container(height=24),
        ],
        horizontal_alignment=(
            ft.CrossAxisAlignment.CENTER
        ),
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    body_wrap = ft.Container(
        body,
        padding=20,
        expand=True,
        opacity=0,
        offset=ft.Offset(0, 0.04),
        animate_opacity=600,
        animate_offset=ft.Animation(
            600,
            ft.AnimationCurve.EASE_OUT,
        ),
    )

    # -----------------------------------------------------
    # Final UI mount
    # -----------------------------------------------------
    # No blocking splash animation: the real UI appears immediately.
    body_wrap.opacity = 1
    body_wrap.offset = ft.Offset(0, 0)

    page.add(
        ft.SafeArea(
            content=body_wrap,
            expand=True,
        )
    )
    page.update()


ft.app(
    target=main,
    assets_dir="assets",
)
