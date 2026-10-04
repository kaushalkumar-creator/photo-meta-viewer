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
OUT_DIR = "/storage/emulated/0/Pictures/PhotoMeta"


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


def save_out(prefix, path, ext, data):
    os.makedirs(OUT_DIR, exist_ok=True)

    base = os.path.splitext(os.path.basename(path))[0]
    name = f"{prefix}_{base}_{time.strftime('%H%M%S')}.{ext}"

    full = os.path.join(OUT_DIR, name)

    with open(full, "wb") as f:
        f.write(data)

    return full


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
    page.padding = 0
    page.bgcolor = BASE

    # ---------------------------------------------------------
    # Local app settings
    # ---------------------------------------------------------
    def storage_get(key, default=None):
        try:
            value = page.client_storage.get(key)
            return default if value is None else value
        except Exception:
            return default

    def storage_set(key, value):
        try:
            page.client_storage.set(key, value)
        except Exception:
            pass

    language = storage_get("photometa.language", "en")
    saved_theme = storage_get("photometa.theme", "light")
    privacy_ack = bool(storage_get("photometa.privacy_ack", False))

    page.theme_mode = (
        ft.ThemeMode.DARK
        if saved_theme == "dark"
        else ft.ThemeMode.LIGHT
    )

    # ---------------------------------------------------------
    # Translation
    # ---------------------------------------------------------
    T = {
        "en": {
            "home": "Home",
            "tools": "Tools",
            "privacy": "Privacy",
            "settings": "Settings",
            "profile": "Profile",
            "inspect": "Inspect",
            "inspect_sub": "Read photo metadata",
            "locate": "Locate",
            "locate_sub": "See embedded location",
            "clean": "Clean",
            "clean_sub": "Remove sensitive metadata",
            "edit": "Edit",
            "edit_sub": "Change metadata",
            "hide": "Hide",
            "hide_sub": "Hide a private message",
            "reveal": "Reveal",
            "reveal_sub": "Read a hidden message",
            "shrink": "Shrink",
            "shrink_sub": "Make a smaller copy",
            "compare": "Compare",
            "compare_sub": "Compare two photos",
            "analyze": "Analyze a photo",
            "welcome": "Understand what your photo reveals",
            "home_sub": "Private, local metadata tools for your photos.",
            "quick": "Quick actions",
            "privacy_title": "Privacy Center",
            "privacy_sub": "Check what sensitive information is inside a photo.",
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW",
            "none": "NONE",
            "remove_location": "Remove location",
            "protect": "Protect photo",
            "protect_sub": "Create a copy without metadata",
            "language": "Language",
            "theme": "Theme",
            "light": "Light",
            "dark": "Dark",
            "app_profile": "App profile",
            "local_profile": "Local app profile",
            "local_profile_sub": "No account or sign-in is required.",
            "about": "About PhotoMeta",
            "about_sub": "Photo metadata viewer and privacy toolkit.",
            "privacy_note": "Use only photos you own or have permission to inspect.",
            "privacy_note_sub": "PhotoMeta does not verify ownership or permission.",
            "consent_title": "Use responsibly",
            "consent_body": "Only inspect photos that belong to you or that you have permission to inspect. Location and camera metadata can be sensitive.",
            "agree": "I understand",
            "export_json": "Export JSON",
            "export_json_sub": "Save all detected metadata as a JSON file",
            "copy": "Copy",
            "share": "Share",
            "done": "Done",
            "change": "Change",
            "back": "Back",
            "save_copy": "Save copy",
            "cancel": "Cancel",
            "no_location": "No location in this photo",
            "location_warning": "Location is inside this photo",
            "location_warning_sub": "Anyone you send it to may be able to find where it was taken.",
            "privacy_risk": "Privacy Risk",
            "camera": "Camera / Phone",
            "date_time": "Date & Time",
            "location": "Location",
            "camera_settings": "Camera Settings",
            "advanced": "Advanced",
            "file_info": "File Info",
            "xmp": "XMP",
            "png_metadata": "PNG Metadata",
            "hashes": "Hashes",
            "json_help": "JSON is a structured text file containing the metadata found in the photo.",
            "save_cancelled": "Save cancelled",
            "saved": "Saved successfully",
            "error": "Something went wrong",
            "inspect_first": "Inspect a photo first",
            "original_untouched": "Original photo stays untouched.",
            "privacy_first": "Your photo is processed locally on this device.",
        },
        "hi": {
            "home": "होम",
            "tools": "टूल्स",
            "privacy": "प्राइवेसी",
            "settings": "सेटिंग्स",
            "profile": "प्रोफ़ाइल",
            "inspect": "Inspect",
            "inspect_sub": "फोटो का metadata देखें",
            "locate": "Locate",
            "locate_sub": "फोटो की location देखें",
            "clean": "Clean",
            "clean_sub": "Sensitive metadata हटाएँ",
            "edit": "Edit",
            "edit_sub": "Metadata बदलें",
            "hide": "Hide",
            "hide_sub": "Private message छिपाएँ",
            "reveal": "Reveal",
            "reveal_sub": "Hidden message पढ़ें",
            "shrink": "Shrink",
            "shrink_sub": "छोटी copy बनाएँ",
            "compare": "Compare",
            "compare_sub": "दो photos compare करें",
            "analyze": "फोटो Analyze करें",
            "welcome": "देखें आपकी फोटो क्या जानकारी बताती है",
            "home_sub": "आपकी photos के लिए private, local metadata tools.",
            "quick": "Quick actions",
            "privacy_title": "Privacy Center",
            "privacy_sub": "फोटो में मौजूद sensitive जानकारी जाँचें।",
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW",
            "none": "NONE",
            "remove_location": "Location हटाएँ",
            "protect": "Photo protect करें",
            "protect_sub": "बिना metadata वाली copy बनाएँ",
            "language": "भाषा",
            "theme": "Theme",
            "light": "Light",
            "dark": "Dark",
            "app_profile": "App profile",
            "local_profile": "Local app profile",
            "local_profile_sub": "किसी account या sign-in की जरूरत नहीं।",
            "about": "PhotoMeta के बारे में",
            "about_sub": "Photo metadata viewer और privacy toolkit.",
            "privacy_note": "केवल अपनी या permission वाली photos का निरीक्षण करें।",
            "privacy_note_sub": "PhotoMeta ownership या permission verify नहीं करता।",
            "consent_title": "जिम्मेदारी से इस्तेमाल करें",
            "consent_body": "केवल उन्हीं photos को inspect करें जो आपकी हैं या जिन्हें inspect करने की आपको permission मिली है। Location और camera metadata sensitive हो सकता है।",
            "agree": "मैं समझता/समझती हूँ",
            "export_json": "JSON Export",
            "export_json_sub": "फोटो का metadata JSON file में save करें",
            "copy": "Copy",
            "share": "Share",
            "done": "Done",
            "change": "Change",
            "back": "Back",
            "save_copy": "Copy Save करें",
            "cancel": "Cancel",
            "no_location": "इस फोटो में location नहीं है",
            "location_warning": "इस फोटो में location मौजूद है",
            "location_warning_sub": "जिसे आप photo भेजेंगे, वह location पता कर सकता है।",
            "privacy_risk": "Privacy Risk",
            "camera": "Camera / Phone",
            "date_time": "Date & Time",
            "location": "Location",
            "camera_settings": "Camera Settings",
            "advanced": "Advanced",
            "file_info": "File Info",
            "xmp": "XMP",
            "png_metadata": "PNG Metadata",
            "hashes": "Hashes",
            "json_help": "JSON एक structured text file है जिसमें फोटो से मिली metadata जानकारी रहती है।",
            "save_cancelled": "Save cancel हो गया",
            "saved": "Successfully save हुआ",
            "error": "कुछ गलत हो गया",
            "inspect_first": "पहले फोटो Inspect करें",
            "original_untouched": "Original photo में कोई बदलाव नहीं होगा।",
            "privacy_first": "फोटो इसी device पर local process होती है।",
        },
    }

    def tr(key):
        return T.get(language, T["en"]).get(key, key)

    # ---------------------------------------------------------
    # Runtime state
    # ---------------------------------------------------------
    st = {
        "path": None,
        "data": None,
        "screen": "home",
        "mode": "inspect",
    }

    picker = ft.FilePicker()
    page.overlay.append(picker)

    # ---------------------------------------------------------
    # Palette
    # ---------------------------------------------------------
    def colors():
        dark = page.theme_mode == ft.ThemeMode.DARK
        if dark:
            return {
                "bg": "#111827",
                "surface": "#182235",
                "surface2": "#202C42",
                "text": "#F3F6FB",
                "muted": "#AAB5C8",
                "border": "#2D3B53",
                "pink": "#FF7BAC",
                "orange": "#FF9A6B",
                "blue": "#6EA8FF",
                "teal": "#42D6C7",
                "amber": "#FFC45C",
                "red": "#FF6670",
                "white": "#FFFFFF",
                "shadow": "#0A0F18",
            }
        return {
            "bg": "#E8EEF6",
            "surface": "#E8EEF6",
            "surface2": "#F4F7FB",
            "text": "#2E3647",
            "muted": "#8A94A6",
            "border": "#CBD5E1",
            "pink": "#FF7BAC",
            "orange": "#FF9A6B",
            "blue": "#5B8DEF",
            "teal": "#2EC4B6",
            "amber": "#FFB547",
            "red": "#E5484D",
            "white": "#FFFFFF",
            "shadow": "#BDC9DA",
        }

    # ---------------------------------------------------------
    # Basic UI helpers
    # ---------------------------------------------------------
    def neu(content=None, radius=22, padding=0, width=None, height=None, **kw):
        c = colors()
        shadows = []
        if page.theme_mode == ft.ThemeMode.LIGHT:
            shadows = [
                ft.BoxShadow(blur_radius=18, offset=ft.Offset(6, 6), color="#BDC9DA"),
                ft.BoxShadow(blur_radius=18, offset=ft.Offset(-6, -6), color="#FFFFFF"),
            ]
        else:
            shadows = [
                ft.BoxShadow(blur_radius=18, offset=ft.Offset(5, 5), color="#0B1220"),
            ]
        return ft.Container(
            content=content,
            padding=padding,
            width=width,
            height=height,
            border_radius=radius,
            bgcolor=c["surface"],
            shadow=shadows,
            **kw,
        )

    def icon_badge(icon, color, size=44):
        return neu(
            ft.Icon(icon, color=color, size=size * 0.5),
            radius=size / 2,
            width=size,
            height=size,
            alignment=ft.alignment.center,
            padding=0,
        )

    def snack(message, error=False):
        c = colors()
        page.open(
            ft.SnackBar(
                ft.Text(message, color="white"),
                bgcolor=c["red"] if error else c["text"],
                behavior=ft.SnackBarBehavior.FLOATING,
            )
        )

    def title_text(text, size=28):
        return ft.Text(
            text,
            size=size,
            weight=ft.FontWeight.W_800,
            color=colors()["text"],
        )

    def sub_text(text):
        return ft.Text(text, size=13, color=colors()["muted"])

    def primary_button(text, icon, on_click, width=None):
        c = colors()
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, color="white", size=20),
                    ft.Text(
                        text,
                        color="white",
                        weight=ft.FontWeight.W_700,
                        size=15,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            ),
            width=width,
            height=52,
            border_radius=26,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
                colors=[c["pink"], c["orange"]],
            ),
            ink=True,
            on_click=on_click,
        )

    def soft_button(text, icon, on_click, width=None):
        c = colors()
        return neu(
            ft.Row(
                [
                    ft.Icon(icon, color=c["pink"], size=20),
                    ft.Text(
                        text,
                        color=c["text"],
                        weight=ft.FontWeight.W_600,
                        size=14,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            ),
            width=width,
            height=50,
            radius=25,
            padding=8,
            ink=True,
            on_click=on_click,
        )

    def tool_card(label, subtitle, icon, color, on_click):
        c = colors()
        return neu(
            ft.Column(
                [
                    icon_badge(icon, color, 46),
                    ft.Text(
                        label,
                        color=c["text"],
                        size=15,
                        weight=ft.FontWeight.W_700,
                    ),
                    ft.Text(
                        subtitle,
                        color=c["muted"],
                        size=11,
                    ),
                ],
                spacing=6,
            ),
            radius=22,
            padding=14,
            expand=True,
            ink=True,
            on_click=on_click,
        )

    def section_header(title, subtitle=None):
        controls = [title_text(title, 21)]
        if subtitle:
            controls.append(sub_text(subtitle))
        return ft.Column(controls, spacing=3)

    # ---------------------------------------------------------
    # Android-safe output
    # ---------------------------------------------------------
    async def save_bytes(data, filename, extension, label=None):
        if not data:
            snack(tr("error"), True)
            return False

        try:
            file_type = ft.FilePickerFileType.CUSTOM
            path = await picker.save_file(
                dialog_title=label or "Save file",
                file_name=filename,
                file_type=file_type,
                allowed_extensions=[extension],
                src_bytes=data,
            )
            if path:
                snack(f"{tr('saved')}: {filename}")
                return True
            snack(tr("save_cancelled"))
            return False
        except Exception as ex:
            # Never expose the raw Android path/permission error.
            snack(f"{tr('error')}: {str(ex)}", True)
            return False

    def save_bytes_task(data, filename, extension, label=None):
        page.run_task(save_bytes, data, filename, extension, label)

    # ---------------------------------------------------------
    # Metadata cards
    # ---------------------------------------------------------
    def metadata_card(title, icon, color, rows):
        c = colors()
        items = []
        for k, v in rows.items():
            if k == "Map":
                items.append(
                    ft.TextButton(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.MAP, size=18, color=color),
                                ft.Text(
                                    "Open map",
                                    color=color,
                                    weight=ft.FontWeight.W_600,
                                ),
                            ],
                            tight=True,
                        ),
                        url=v,
                    )
                )
                continue
            if isinstance(v, (dict, list)):
                v = str(v)
            items.append(
                ft.Row(
                    [
                        ft.Text(
                            str(k),
                            color=c["muted"],
                            size=12,
                            width=105,
                        ),
                        ft.Text(
                            str(v),
                            color=c["text"],
                            size=13,
                            expand=True,
                            selectable=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )

        return neu(
            ft.Column(
                [
                    ft.Row(
                        [
                            icon_badge(icon, color, 40),
                            ft.Text(
                                title,
                                color=c["text"],
                                size=16,
                                weight=ft.FontWeight.W_700,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Divider(height=1, color=c["border"]),
                    *items,
                ],
                spacing=9,
            ),
            padding=16,
            radius=22,
        )

    def privacy_card(data):
        c = colors()
        privacy = data.get("privacy") or {}
        risk = privacy.get("Risk", "NONE")
        detected = privacy.get("Detected") or []

        risk_color = {
            "HIGH": c["red"],
            "MEDIUM": c["amber"],
            "LOW": c["orange"],
        }.get(risk, c["teal"])

        detected_text = (
            ", ".join(map(str, detected))
            if detected
            else "No obvious privacy-sensitive metadata detected"
        )

        return neu(
            ft.Column(
                [
                    ft.Row(
                        [
                            icon_badge(ft.Icons.SECURITY, risk_color, 42),
                            ft.Column(
                                [
                                    ft.Text(
                                        tr("privacy_risk"),
                                        color=c["text"],
                                        size=16,
                                        weight=ft.FontWeight.W_700,
                                    ),
                                    ft.Text(
                                        risk,
                                        color=risk_color,
                                        size=12,
                                        weight=ft.FontWeight.W_800,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Text(
                        detected_text,
                        color=c["text"],
                        size=13,
                    ),
                ],
                spacing=8,
            ),
            padding=16,
            radius=22,
        )

    # ---------------------------------------------------------
    # Picker / actions
    # ---------------------------------------------------------
    def start_pick(mode):
        st["mode"] = mode
        st["screen"] = "tools"
        try:
            picker.pick_files(
                dialog_title="Choose photo",
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=mode in ("clean", "shrink", "compare"),
            )
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def on_pick(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        paths = [f.path for f in e.files if f.path]
        if not paths:
            snack("This file picker did not return a readable path.", True)
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
        st["screen"] = "analyze"
        render()

    picker.on_result = on_pick

    def show_result():
        if not st["path"]:
            snack(tr("inspect_first"), True)
            return
        try:
            st["data"] = read_metadata(st["path"])
            st["screen"] = "analyze"
            render()
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def locate(path):
        try:
            d = read_metadata(path)
            url = (d.get("location") or {}).get("Map")
            if url:
                page.launch_url(url)
            else:
                snack(tr("no_location"))
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def copy_meta():
        if not st["data"]:
            snack(tr("inspect_first"), True)
            return
        try:
            page.set_clipboard(report_text(st["data"]))
            snack("Metadata copied")
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def share_meta():
        if not st["data"]:
            snack(tr("inspect_first"), True)
            return
        try:
            text = urllib.parse.quote(report_text(st["data"]))
            page.launch_url("https://wa.me/?text=" + text)
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def export_json():
        if not st["data"] or not st["path"]:
            snack(tr("inspect_first"), True)
            return
        try:
            data = metadata_to_json(st["data"], pretty=True).encode("utf-8")
            base = os.path.splitext(os.path.basename(st["path"]))[0]
            filename = f"PhotoMeta_{base}.json"
            save_bytes_task(
                data,
                filename,
                "json",
                tr("export_json"),
            )
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def clean_one(path, mode):
        try:
            data = clean_bytes(path, mode)
            base = os.path.splitext(os.path.basename(path))[0]
            filename = (
                f"PhotoMeta_no_location_{base}.jpg"
                if mode == "gps"
                else f"PhotoMeta_clean_{base}.jpg"
            )
            save_bytes_task(data, filename, "jpg", tr("clean"))
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)

    def ask_clean(paths):
        c = colors()

        def choose(mode):
            page.close(dlg)
            for p in paths:
                clean_one(p, mode)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(
                f"{tr('clean')} {len(paths)} photo(s)",
                color=c["text"],
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Text(
                tr("original_untouched"),
                color=c["muted"],
            ),
            actions=[
                ft.TextButton(
                    tr("cancel"),
                    on_click=lambda e: page.close(dlg),
                ),
                ft.TextButton(
                    "Location only",
                    on_click=lambda e: choose("gps"),
                ),
                ft.TextButton(
                    "Everything",
                    on_click=lambda e: choose("all"),
                ),
            ],
        )
        page.open(dlg)

    def open_edit(path):
        c = colors()
        try:
            d = read_metadata(path)
        except Exception:
            d = {"camera": {}, "time": {}}

        cam = d.get("camera") or {}
        tm = d.get("time") or {}

        def fld(label, value=""):
            return ft.TextField(
                label=label,
                value="" if value is None else str(value),
                color=c["text"],
                border_color=c["border"],
                focused_border_color=c["pink"],
                label_style=ft.TextStyle(color=c["muted"]),
            )

        f_author = fld("Author", cam.get("Author", ""))
        f_copy = fld("Copyright", cam.get("Copyright", ""))
        f_desc = fld("Description", cam.get("Description", ""))
        f_date = fld("Date taken", tm.get("Taken on", ""))
        f_make = fld("Brand", cam.get("Brand", ""))
        f_model = fld("Model", cam.get("Model", ""))

        def save_edit(e):
            fields = {
                "Author": f_author.value,
                "Copyright": f_copy.value,
                "Description": f_desc.value,
                "Date": f_date.value,
                "Make": f_make.value,
                "Model": f_model.value,
            }
            if not any((v or "").strip() for v in fields.values()):
                snack("Fill at least one field", True)
                return
            try:
                data = edit_bytes(path, fields)
                base = os.path.splitext(os.path.basename(path))[0]
                filename = f"PhotoMeta_edited_{base}.jpg"
                page.close(dlg)
                save_bytes_task(data, filename, "jpg", tr("edit"))
            except Exception as ex:
                snack(f"{tr('error')}: {ex}", True)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(
                tr("edit"),
                color=c["text"],
                weight=ft.FontWeight.W_700,
            ),
            content=ft.Container(
                ft.Column(
                    [
                        ft.Text(
                            tr("original_untouched"),
                            color=c["muted"],
                            size=12,
                        ),
                        f_author,
                        f_copy,
                        f_desc,
                        f_date,
                        f_make,
                        f_model,
                    ],
                    spacing=10,
                    scroll=ft.ScrollMode.HIDDEN,
                ),
                width=320,
                height=390,
            ),
            actions=[
                ft.TextButton(
                    tr("cancel"),
                    on_click=lambda e: page.close(dlg),
                ),
                ft.TextButton(
                    tr("save_copy"),
                    on_click=save_edit,
                ),
            ],
        )
        page.open(dlg)

    def open_hide(path):
        c = colors()
        f_msg = ft.TextField(
            label="Secret message",
            multiline=True,
            min_lines=3,
            max_lines=6,
            color=c["text"],
        )
        f_pw = ft.TextField(
            label="Password (optional)",
            password=True,
            can_reveal_password=True,
            color=c["text"],
        )

        def hide(e):
            msg = (f_msg.value or "").strip()
            if not msg:
                snack("Write a message first", True)
                return
            try:
                data = embed_bytes(path, msg, f_pw.value or "")
                base = os.path.splitext(os.path.basename(path))[0]
                filename = f"PhotoMeta_secret_{base}.png"
                page.close(dlg)
                save_bytes_task(data, filename, "png", tr("hide"))
            except Exception as ex:
                snack(f"{tr('error')}: {ex}", True)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(tr("hide"), color=c["text"]),
            content=ft.Column(
                [f_msg, f_pw],
                tight=True,
                spacing=12,
                scroll=ft.ScrollMode.HIDDEN,
            ),
            actions=[
                ft.TextButton(tr("cancel"), on_click=lambda e: page.close(dlg)),
                ft.TextButton("Hide", on_click=hide),
            ],
        )
        page.open(dlg)

    def open_reveal(path):
        c = colors()
        f_pw = ft.TextField(
            label="Password (if any)",
            password=True,
            can_reveal_password=True,
            color=c["text"],
        )

        def reveal(e):
            try:
                text = extract_text(path, f_pw.value or "")
                page.close(dlg)

                def copy_it(ev):
                    page.set_clipboard(text)
                    snack("Message copied")

                out = ft.AlertDialog(
                    modal=True,
                    bgcolor=c["surface"],
                    title=ft.Text("Hidden message", color=c["text"]),
                    content=ft.Container(
                        ft.Text(
                            text,
                            color=c["text"],
                            selectable=True,
                            size=15,
                        ),
                        width=320,
                    ),
                    actions=[
                        ft.TextButton("Copy", on_click=copy_it),
                        ft.TextButton(
                            "Close",
                            on_click=lambda ev: page.close(out),
                        ),
                    ],
                )
                page.open(out)
            except Exception as ex:
                snack(f"{tr('error')}: {ex}", True)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(tr("reveal"), color=c["text"]),
            content=f_pw,
            actions=[
                ft.TextButton(tr("cancel"), on_click=lambda e: page.close(dlg)),
                ft.TextButton("Reveal", on_click=reveal),
            ],
        )
        page.open(dlg)

    def ask_shrink(paths):
        c = colors()
        rg = ft.RadioGroup(
            value="1600",
            content=ft.Column(
                [
                    ft.Radio(value="1080", label="Small - 1080 px"),
                    ft.Radio(value="1600", label="Medium - 1600 px"),
                    ft.Radio(value="2400", label="Large - 2400 px"),
                ],
                tight=True,
            ),
        )
        chk = ft.Checkbox(
            label="Also remove metadata",
            value=True,
            active_color=c["pink"],
        )

        def go(e):
            size = int(rg.value or "1600")
            strip = bool(chk.value)
            page.close(dlg)
            for p in paths:
                try:
                    data = shrink_bytes(p, size, strip)
                    base = os.path.splitext(os.path.basename(p))[0]
                    filename = f"PhotoMeta_small_{base}.jpg"
                    save_bytes_task(data, filename, "jpg", tr("shrink"))
                except Exception as ex:
                    snack(f"{tr('error')}: {ex}", True)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(tr("shrink"), color=c["text"]),
            content=ft.Column([rg, chk], tight=True, spacing=10),
            actions=[
                ft.TextButton(tr("cancel"), on_click=lambda e: page.close(dlg)),
                ft.TextButton("Shrink", on_click=go),
            ],
        )
        page.open(dlg)

    def compare(paths):
        if len(paths) < 2:
            snack("Select 2 photos to compare", True)
            return
        try:
            diff, same = compare_rows(
                read_metadata(paths[0]),
                read_metadata(paths[1]),
            )
        except Exception as ex:
            snack(f"{tr('error')}: {ex}", True)
            return

        c = colors()
        items = [
            ft.Text(
                f"{len(diff)} different, {same} same",
                color=c["muted"],
            )
        ]
        for k, va, vb in diff:
            items.append(
                ft.Column(
                    [
                        ft.Text(k, color=c["text"], weight=ft.FontWeight.W_700),
                        ft.Text(f"Photo 1: {va}", color=c["blue"], selectable=True),
                        ft.Text(f"Photo 2: {vb}", color=c["orange"], selectable=True),
                    ],
                    spacing=2,
                )
            )

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(tr("compare"), color=c["text"]),
            content=ft.Container(
                ft.Column(
                    items,
                    spacing=12,
                    scroll=ft.ScrollMode.HIDDEN,
                ),
                width=320,
                height=min(430, 90 + len(diff) * 78),
            ),
            actions=[
                ft.TextButton(
                    tr("cancel"),
                    on_click=lambda e: page.close(dlg),
                )
            ],
        )
        page.open(dlg)

    # ---------------------------------------------------------
    # Screens
    # ---------------------------------------------------------
    content_area = ft.Container(expand=True)

    def app_header(title, subtitle=None, show_profile=True):
        c = colors()
        actions = []
        if show_profile:
            actions.append(
                ft.Container(
                    content=ft.Icon(ft.Icons.PERSON_OUTLINE, color=c["text"]),
                    width=44,
                    height=44,
                    border_radius=22,
                    bgcolor=c["surface2"],
                    alignment=ft.alignment.center,
                    ink=True,
                    on_click=lambda e: set_screen("settings"),
                )
            )
        return ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(
                            title,
                            color=c["text"],
                            size=27,
                            weight=ft.FontWeight.W_800,
                        ),
                        ft.Text(
                            subtitle,
                            color=c["muted"],
                            size=12,
                        ) if subtitle else ft.Container(),
                    ],
                    spacing=2,
                    expand=True,
                ),
                *actions,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def home_screen():
        c = colors()
        return ft.Column(
            [
                app_header(
                    "PhotoMeta",
                    tr("welcome"),
                ),
                ft.Container(height=10),
                neu(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    icon_badge(ft.Icons.IMAGE_SEARCH, c["pink"], 56),
                                    ft.Column(
                                        [
                                            ft.Text(
                                                tr("analyze"),
                                                color=c["text"],
                                                size=19,
                                                weight=ft.FontWeight.W_800,
                                            ),
                                            sub_text(tr("home_sub")),
                                        ],
                                        spacing=3,
                                        expand=True,
                                    ),
                                ],
                                spacing=14,
                            ),
                            primary_button(
                                tr("analyze"),
                                ft.Icons.SEARCH,
                                lambda e: start_pick("inspect"),
                            ),
                        ],
                        spacing=14,
                    ),
                    padding=18,
                    radius=26,
                ),
                ft.Container(height=22),
                section_header(tr("quick"), tr("privacy_first")),
                ft.Container(height=10),
                ft.Row(
                    [
                        tool_card(
                            tr("inspect"),
                            tr("inspect_sub"),
                            ft.Icons.IMAGE_SEARCH,
                            c["blue"],
                            lambda e: start_pick("inspect"),
                        ),
                        tool_card(
                            tr("clean"),
                            tr("clean_sub"),
                            ft.Icons.SHIELD,
                            c["teal"],
                            lambda e: start_pick("clean"),
                        ),
                    ],
                    spacing=14,
                ),
                ft.Container(height=14),
                ft.Row(
                    [
                        tool_card(
                            tr("edit"),
                            tr("edit_sub"),
                            ft.Icons.EDIT,
                            c["amber"],
                            lambda e: start_pick("edit"),
                        ),
                        tool_card(
                            tr("compare"),
                            tr("compare_sub"),
                            ft.Icons.COMPARE,
                            c["teal"],
                            lambda e: start_pick("compare"),
                        ),
                    ],
                    spacing=14,
                ),
                ft.Container(height=18),
                neu(
                    ft.Row(
                        [
                            icon_badge(ft.Icons.LOCK_OUTLINE, c["teal"], 42),
                            ft.Column(
                                [
                                    ft.Text(
                                        "Local processing",
                                        color=c["text"],
                                        weight=ft.FontWeight.W_700,
                                    ),
                                    sub_text(tr("privacy_first")),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                    ),
                    padding=14,
                    radius=20,
                ),
            ],
            spacing=0,
            scroll=ft.ScrollMode.HIDDEN,
            expand=True,
        )

    def tools_screen():
        c = colors()
        tools = [
            ("inspect", ft.Icons.IMAGE_SEARCH, c["blue"]),
            ("locate", ft.Icons.LOCATION_ON, c["orange"]),
            ("clean", ft.Icons.SHIELD, c["teal"]),
            ("edit", ft.Icons.EDIT, c["amber"]),
            ("hide", ft.Icons.LOCK, c["pink"]),
            ("reveal", ft.Icons.VISIBILITY, c["blue"]),
            ("shrink", ft.Icons.COMPRESS, c["orange"]),
            ("compare", ft.Icons.COMPARE, c["teal"]),
        ]
        rows = []
        for i in range(0, len(tools), 2):
            a = tools[i]
            b = tools[i + 1]
            rows.append(
                ft.Row(
                    [
                        tool_card(
                            tr(a[0]),
                            tr(a[0] + "_sub"),
                            a[1],
                            a[2],
                            lambda e, mode=a[0]: start_pick(mode),
                        ),
                        tool_card(
                            tr(b[0]),
                            tr(b[0] + "_sub"),
                            b[1],
                            b[2],
                            lambda e, mode=b[0]: start_pick(mode),
                        ),
                    ],
                    spacing=14,
                )
            )
            rows.append(ft.Container(height=12))

        return ft.Column(
            [
                app_header(tr("tools"), "All PhotoMeta tools"),
                ft.Container(height=12),
                *rows,
            ],
            scroll=ft.ScrollMode.HIDDEN,
            expand=True,
        )

    def privacy_screen():
        c = colors()
        if not st["data"]:
            return ft.Column(
                [
                    app_header(tr("privacy_title"), tr("privacy_sub")),
                    ft.Container(height=16),
                    neu(
                        ft.Column(
                            [
                                icon_badge(ft.Icons.SECURITY, c["teal"], 54),
                                title_text("Privacy-first workflow", 20),
                                sub_text(tr("privacy_note")),
                                sub_text(tr("privacy_note_sub")),
                                primary_button(
                                    tr("analyze"),
                                    ft.Icons.IMAGE_SEARCH,
                                    lambda e: start_pick("inspect"),
                                ),
                            ],
                            spacing=12,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=20,
                        radius=26,
                    ),
                ],
                scroll=ft.ScrollMode.HIDDEN,
                expand=True,
            )

        d = st["data"]
        location = d.get("location") or {}
        cards = [privacy_card(d)]

        if location.get("Map"):
            cards.append(
                neu(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    icon_badge(ft.Icons.WARNING_AMBER_ROUNDED, c["red"], 44),
                                    ft.Text(
                                        tr("location_warning"),
                                        color=c["red"],
                                        size=17,
                                        weight=ft.FontWeight.W_800,
                                        expand=True,
                                    ),
                                ],
                                spacing=10,
                            ),
                            ft.Text(
                                tr("location_warning_sub"),
                                color=c["text"],
                                size=13,
                            ),
                            ft.Row(
                                [
                                    soft_button(
                                        tr("locate"),
                                        ft.Icons.LOCATION_ON,
                                        lambda e: locate(st["path"]),
                                    ),
                                    soft_button(
                                        tr("remove_location"),
                                        ft.Icons.SHIELD,
                                        lambda e: clean_one(st["path"], "gps"),
                                    ),
                                ],
                                spacing=10,
                            ),
                        ],
                        spacing=10,
                    ),
                    padding=16,
                    radius=22,
                )
            )
        else:
            cards.append(
                neu(
                    ft.Row(
                        [
                            icon_badge(ft.Icons.CHECK_CIRCLE_OUTLINE, c["teal"], 42),
                            ft.Column(
                                [
                                    ft.Text(
                                        tr("no_location"),
                                        color=c["text"],
                                        weight=ft.FontWeight.W_700,
                                    ),
                                    sub_text("No GPS map link detected."),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=10,
                    ),
                    padding=15,
                    radius=20,
                )
            )

        cards.append(
            neu(
                ft.Column(
                    [
                        ft.Text(
                            tr("protect"),
                            color=c["text"],
                            size=17,
                            weight=ft.FontWeight.W_800,
                        ),
                        sub_text(tr("protect_sub")),
                        primary_button(
                            tr("protect"),
                            ft.Icons.SHIELD,
                            lambda e: clean_one(st["path"], "all"),
                        ),
                    ],
                    spacing=10,
                ),
                padding=16,
                radius=22,
            )
        )

        return ft.Column(
            [
                app_header(tr("privacy_title"), tr("privacy_sub")),
                ft.Container(height=12),
                *cards,
                ft.Container(height=20),
            ],
            spacing=12,
            scroll=ft.ScrollMode.HIDDEN,
            expand=True,
        )

    def settings_screen():
        c = colors()

        language_dd = ft.Dropdown(
            value=language,
            options=[
                ft.dropdown.Option("en", "English"),
                ft.dropdown.Option("hi", "हिन्दी"),
            ],
            label=tr("language"),
            width=160,
            border_color=c["border"],
            color=c["text"],
        )

        theme_switch = ft.Switch(
            value=page.theme_mode == ft.ThemeMode.DARK,
            active_color=c["pink"],
        )

        def language_change(e):
            nonlocal language
            language = e.control.value
            storage_set("photometa.language", language)
            render()

        def theme_change(e):
            page.theme_mode = (
                ft.ThemeMode.DARK
                if e.control.value
                else ft.ThemeMode.LIGHT
            )
            storage_set(
                "photometa.theme",
                "dark" if e.control.value else "light",
            )
            render()

        return ft.Column(
            [
                app_header(tr("settings"), tr("profile")),
                ft.Container(height=12),
                neu(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.PERSON,
                                    color="white",
                                    size=30,
                                ),
                                width=64,
                                height=64,
                                border_radius=32,
                                gradient=ft.LinearGradient(
                                    colors=[c["pink"], c["orange"]]
                                ),
                                alignment=ft.alignment.center,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        tr("local_profile"),
                                        color=c["text"],
                                        size=18,
                                        weight=ft.FontWeight.W_800,
                                    ),
                                    sub_text(tr("local_profile_sub")),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                        ],
                        spacing=14,
                    ),
                    padding=16,
                    radius=24,
                ),
                ft.Container(height=12),
                neu(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.LANGUAGE, color=c["blue"]),
                                    ft.Text(
                                        tr("language"),
                                        color=c["text"],
                                        size=15,
                                        weight=ft.FontWeight.W_700,
                                        expand=True,
                                    ),
                                    language_dd,
                                ]
                            ),
                            ft.Divider(height=1, color=c["border"]),
                            ft.Row(
                                [
                                    ft.Icon(
                                        ft.Icons.DARK_MODE,
                                        color=c["pink"],
                                    ),
                                    ft.Text(
                                        tr("theme"),
                                        color=c["text"],
                                        size=15,
                                        weight=ft.FontWeight.W_700,
                                        expand=True,
                                    ),
                                    ft.Text(
                                        tr("dark")
                                        if theme_switch.value
                                        else tr("light"),
                                        color=c["muted"],
                                    ),
                                    theme_switch,
                                ]
                            ),
                        ],
                        spacing=14,
                    ),
                    padding=16,
                    radius=24,
                ),
                ft.Container(height=12),
                neu(
                    ft.Column(
                        [
                            ft.Row(
                                [
                                    icon_badge(ft.Icons.SECURITY, c["teal"], 42),
                                    ft.Text(
                                        tr("privacy_note"),
                                        color=c["text"],
                                        size=15,
                                        weight=ft.FontWeight.W_700,
                                        expand=True,
                                    ),
                                ],
                                spacing=10,
                            ),
                            sub_text(tr("privacy_note_sub")),
                        ],
                        spacing=8,
                    ),
                    padding=16,
                    radius=24,
                ),
                ft.Container(height=12),
                neu(
                    ft.Column(
                        [
                            ft.Text(
                                tr("about"),
                                color=c["text"],
                                size=16,
                                weight=ft.FontWeight.W_800,
                            ),
                            sub_text(tr("about_sub")),
                            ft.Text(
                                "PhotoMeta 2.0",
                                color=c["muted"],
                                size=12,
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=16,
                    radius=24,
                ),
                ft.Container(height=20),
            ],
            spacing=0,
            scroll=ft.ScrollMode.HIDDEN,
            expand=True,
        )

        # Keep handlers alive through closures.
        language_dd.on_change = language_change
        theme_switch.on_change = theme_change

    def analyze_screen():
        c = colors()
        if not st["path"]:
            return home_screen()

        preview = ft.Image(
            src_base64=TINY,
            width=260,
            height=260,
            fit=ft.ImageFit.CONTAIN,
        )
        try:
            preview.src_base64 = make_preview(st["path"])
        except Exception:
            pass

        top_actions = ft.Row(
            [
                soft_button(tr("copy"), ft.Icons.CONTENT_COPY, lambda e: copy_meta()),
                soft_button(tr("share"), ft.Icons.SHARE, lambda e: share_meta()),
                soft_button(
                    tr("export_json"),
                    ft.Icons.DATA_OBJECT,
                    lambda e: export_json(),
                ),
            ],
            spacing=8,
        )

        if not st["data"]:
            inspect_button = primary_button(
                tr("done"),
                ft.Icons.CHECK,
                lambda e: show_result(),
            )
            result_cards = []
        else:
            inspect_button = None
            d = st["data"]
            result_cards = [privacy_card(d)]

            specs = [
                (tr("camera"), ft.Icons.PHONE_ANDROID, c["blue"], d.get("camera") or {}),
                (tr("date_time"), ft.Icons.SCHEDULE, c["pink"], d.get("time") or {}),
                (tr("location"), ft.Icons.LOCATION_ON, c["orange"], d.get("location") or {}),
                (tr("camera_settings"), ft.Icons.CAMERA_ALT, c["amber"], d.get("settings") or {}),
                (tr("advanced"), ft.Icons.TUNE, c["blue"], d.get("advanced") or {}),
                (tr("file_info"), ft.Icons.INSERT_DRIVE_FILE, c["teal"], d.get("file") or {}),
                (tr("xmp"), ft.Icons.DATA_OBJECT, c["pink"], d.get("xmp") or {}),
                (tr("png_metadata"), ft.Icons.IMAGE, c["orange"], d.get("png") or {}),
                (tr("hashes"), ft.Icons.TAG, c["teal"], d.get("hash") or {}),
            ]
            for title, icon, color, rows in specs:
                if rows:
                    result_cards.append(metadata_card(title, icon, color, rows))

            if (d.get("location") or {}).get("Map"):
                result_cards.insert(
                    0,
                    neu(
                        ft.Column(
                            [
                                ft.Text(
                                    tr("location_warning"),
                                    color=c["red"],
                                    size=16,
                                    weight=ft.FontWeight.W_800,
                                ),
                                sub_text(tr("location_warning_sub")),
                                primary_button(
                                    tr("remove_location"),
                                    ft.Icons.SHIELD,
                                    lambda e: clean_one(st["path"], "gps"),
                                ),
                            ],
                            spacing=8,
                        ),
                        padding=16,
                        radius=22,
                    ),
                )

        controls = [
            ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        icon_color=c["text"],
                        on_click=lambda e: set_screen("home"),
                    ),
                    ft.Text(
                        tr("inspect"),
                        color=c["text"],
                        size=22,
                        weight=ft.FontWeight.W_800,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.SWAP_HORIZ,
                        icon_color=c["text"],
                        on_click=lambda e: start_pick("inspect"),
                    ),
                ]
            ),
            neu(
                ft.Column(
                    [
                        ft.Container(
                            preview,
                            alignment=ft.alignment.center,
                        ),
                        ft.Text(
                            os.path.basename(st["path"]),
                            color=c["text"],
                            size=13,
                            weight=ft.FontWeight.W_700,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=12,
                radius=24,
            ),
            ft.Container(height=10),
        ]

        if inspect_button:
            controls.append(inspect_button)
        else:
            controls.append(top_actions)
            controls.append(
                ft.Row(
                    [
                        soft_button(
                            tr("clean"),
                            ft.Icons.SHIELD,
                            lambda e: clean_one(st["path"], "all"),
                        ),
                        soft_button(
                            tr("edit"),
                            ft.Icons.EDIT,
                            lambda e: open_edit(st["path"]),
                        ),
                    ],
                    spacing=10,
                )
            )
            controls.extend(result_cards)

        return ft.Column(
            controls,
            spacing=12,
            scroll=ft.ScrollMode.HIDDEN,
            expand=True,
        )

    def set_screen(screen):
        st["screen"] = screen
        render()

    def render():
        c = colors()
        page.bgcolor = c["bg"]

        if st["screen"] == "home":
            view = home_screen()
            selected = 0
        elif st["screen"] == "tools":
            view = tools_screen()
            selected = 1
        elif st["screen"] == "privacy":
            view = privacy_screen()
            selected = 2
        elif st["screen"] == "settings":
            view = settings_screen()
            selected = 3
        elif st["screen"] == "analyze":
            view = analyze_screen()
            selected = 0
        else:
            view = home_screen()
            selected = 0

        content_area.content = ft.Container(
            view,
            padding=18,
            expand=True,
        )

        nav = ft.NavigationBar(
            selected_index=selected,
            destinations=[
                ft.NavigationBarDestination(
                    icon=ft.Icons.HOME_OUTLINED,
                    selected_icon=ft.Icons.HOME,
                    label=tr("home"),
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.APPS_OUTLINED,
                    selected_icon=ft.Icons.APPS,
                    label=tr("tools"),
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.SECURITY_OUTLINED,
                    selected_icon=ft.Icons.SECURITY,
                    label=tr("privacy"),
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label=tr("settings"),
                ),
            ],
            on_change=lambda e: set_screen(
                ["home", "tools", "privacy", "settings"][
                    e.control.selected_index
                ]
            ),
            bgcolor=c["surface"],
            indicator_color=c["pink"],
        )

        page.navigation_bar = nav
        page.update()

    # ---------------------------------------------------------
    # First-run privacy notice
    # ---------------------------------------------------------
    render()

    if not privacy_ack:
        c = colors()

        def accept(e):
            nonlocal privacy_ack
            privacy_ack = True
            storage_set("photometa.privacy_ack", True)
            page.close(dlg)

        dlg = ft.AlertDialog(
            modal=True,
            bgcolor=c["surface"],
            title=ft.Text(
                tr("consent_title"),
                color=c["text"],
                weight=ft.FontWeight.W_800,
            ),
            content=ft.Text(
                tr("consent_body"),
                color=c["text"],
                size=14,
            ),
            actions=[
                ft.TextButton(
                    tr("agree"),
                    on_click=accept,
                )
            ],
        )
        page.open(dlg)


ft.app(
    target=main,
    assets_dir="assets",
)
