"""
PhotoMeta 2.0 - Metadata Engine
--------------------------------
Reads image/file metadata without changing the original file.

Supported:
- EXIF
- GPS
- Camera information
- Exposure information
- File information
- ICC profile presence
- XMP packet detection/extraction
- PNG textual metadata
- SHA-256 hash
- Perceptual image hash
"""

import os
import io
import re
import json
import hashlib
from fractions import Fraction

from PIL import Image, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS


# ---------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------

def _safe_text(value):
    """Convert metadata values into readable text."""
    if value is None:
        return ""

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace").strip()
        except Exception:
            return repr(value)

    if isinstance(value, tuple):
        return ", ".join(_safe_text(x) for x in value)

    return str(value).strip()


def _ratio(value):
    """Convert EXIF rational values into a readable number."""
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            if value.denominator == 0:
                return None
            return float(value.numerator) / float(value.denominator)

        if isinstance(value, Fraction):
            return float(value)

        if isinstance(value, tuple) and len(value) == 2:
            if value[1] == 0:
                return None
            return float(value[0]) / float(value[1])

        return float(value)
    except Exception:
        return None


def _format_number(value, decimals=2):
    number = _ratio(value)

    if number is None:
        return _safe_text(value)

    return f"{number:.{decimals}f}"


def _format_shutter(value):
    number = _ratio(value)

    if number is None:
        return _safe_text(value)

    if number <= 0:
        return _safe_text(value)

    if number < 1:
        denominator = round(1 / number)
        return f"1/{denominator} s"

    return f"{number:.2f} s"


def _gps_decimal(values):
    """Convert GPS DMS values into decimal degrees."""
    if not values or len(values) != 3:
        return None

    parts = []

    for value in values:
        number = _ratio(value)
        if number is None:
            return None
        parts.append(number)

    degrees, minutes, seconds = parts

    return degrees + minutes / 60 + seconds / 3600


def _gps_string(value):
    decimal = _gps_decimal(value)

    if decimal is None:
        return None

    return f"{decimal:.6f}"


# ---------------------------------------------------------
# File hashing
# ---------------------------------------------------------

def sha256_file(path, chunk_size=1024 * 1024):
    """Return SHA-256 hash of the original file."""
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        while True:
            chunk = file.read(chunk_size)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def _average_hash(image):
    """
    Simple perceptual hash.
    Returns a 16-character hexadecimal hash.
    """
    try:
        img = ImageOps.exif_transpose(image).convert("L")
        img = img.resize((8, 8))

        pixels = list(img.getdata())
        average = sum(pixels) / len(pixels)

        bits = 0

        for pixel in pixels:
            bits <<= 1
            if pixel >= average:
                bits |= 1

        return f"{bits:016x}"

    except Exception:
        return ""


# ---------------------------------------------------------
# XMP
# ---------------------------------------------------------

def _extract_xmp(raw_bytes):
    """
    Extract an XMP packet if one exists in the file.
    """
    if not raw_bytes:
        return ""

    start_markers = [
        b"<x:xmpmeta",
        b"<xmpmeta",
        b"<?xpacket begin",
    ]

    end_markers = [
        b"</x:xmpmeta>",
        b"</xmpmeta>",
        b"<?xpacket end",
    ]

    start = -1

    for marker in start_markers:
        position = raw_bytes.find(marker)

        if position != -1:
            if start == -1 or position < start:
                start = position

    if start == -1:
        return ""

    end = -1

    for marker in end_markers:
        position = raw_bytes.find(marker, start)

        if position != -1:
            candidate = position + len(marker)

            if end == -1 or candidate < end:
                end = candidate

    if end == -1:
        end = min(start + 200000, len(raw_bytes))

    packet = raw_bytes[start:end]

    return packet.decode("utf-8", errors="replace").strip()


def _xmp_summary(xmp):
    """Extract useful common XMP fields."""
    if not xmp:
        return {}

    result = {}

    patterns = {
        "Creator": [
            r'dc:creator[^>]*>(.*?)</',
            r'dc:creator="([^"]+)"',
        ],
        "Description": [
            r'dc:description[^>]*>(.*?)</',
            r'dc:description="([^"]+)"',
        ],
        "Title": [
            r'dc:title[^>]*>(.*?)</',
            r'dc:title="([^"]+)"',
        ],
        "Rating": [
            r'xmp:Rating="([^"]+)"',
        ],
        "CreatorTool": [
            r'xmp:CreatorTool="([^"]+)"',
        ],
        "ModifyDate": [
            r'xmp:ModifyDate="([^"]+)"',
        ],
        "CreateDate": [
            r'xmp:CreateDate="([^"]+)"',
        ],
    }

    for name, variants in patterns.items():
        for pattern in variants:
            match = re.search(
                pattern,
                xmp,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip()

                if value:
                    result[name] = value
                    break

    return result


# ---------------------------------------------------------
# PNG metadata
# ---------------------------------------------------------

def _png_text_metadata(image):
    """Read common PNG text metadata when available."""
    result = {}

    try:
        info = image.info or {}

        for key, value in info.items():
            if key in ("icc_profile", "exif", "xmp"):
                continue

            if isinstance(value, (str, int, float)):
                result[str(key)] = _safe_text(value)

    except Exception:
        pass

    return result


# ---------------------------------------------------------
# EXIF
# ---------------------------------------------------------

def _read_exif(image):
    """
    Read EXIF into human-readable dictionaries.
    """
    result = {
        "camera": {},
        "time": {},
        "location": {},
        "settings": {},
        "advanced": {},
        "raw": {},
    }

    try:
        exif = image.getexif()
    except Exception:
        exif = None

    if not exif:
        return result

    raw = {}

    for tag_id, value in exif.items():
        name = TAGS.get(tag_id, f"Tag {tag_id}")
        raw[name] = _safe_text(value)

    result["raw"] = raw

    # ---------------- Camera ----------------

    camera_map = {
        "Make": "Brand",
        "Model": "Model",
        "Software": "Software",
        "Artist": "Author",
        "Copyright": "Copyright",
        "ImageDescription": "Description",
        "LensMake": "Lens Make",
        "LensModel": "Lens Model",
        "BodySerialNumber": "Camera Serial Number",
        "LensSerialNumber": "Lens Serial Number",
    }

    for source, target in camera_map.items():
        if source in raw and raw[source]:
            result["camera"][target] = raw[source]

    # ---------------- Date ----------------

    date_map = {
        "DateTimeOriginal": "Taken on",
        "DateTimeDigitized": "Digitized on",
        "DateTime": "Modified on",
    }

    for source, target in date_map.items():
        if source in raw and raw[source]:
            result["time"][target] = raw[source]

    # ---------------- Settings ----------------

    if "ISOSpeedRatings" in raw:
        result["settings"]["ISO"] = raw["ISOSpeedRatings"]

    elif "PhotographicSensitivity" in raw:
        result["settings"]["ISO"] = raw["PhotographicSensitivity"]

    if "FNumber" in exif:
        result["settings"]["Aperture"] = (
            f"f/{_format_number(exif['FNumber'], 1)}"
        )

    if "ExposureTime" in exif:
        result["settings"]["Shutter"] = _format_shutter(
            exif["ExposureTime"]
        )

    if "FocalLength" in exif:
        result["settings"]["Focal length"] = (
            f"{_format_number(exif['FocalLength'], 2)} mm"
        )

    if "FocalLengthIn35mmFilm" in raw:
        result["settings"]["35mm equivalent"] = (
            f"{raw['FocalLengthIn35mmFilm']} mm"
        )

    if "Flash" in exif:
        try:
            flash_value = int(exif["Flash"])
            result["settings"]["Flash"] = (
                "Fired" if flash_value & 1 else "Off"
            )
        except Exception:
            result["settings"]["Flash"] = raw.get(
                "Flash",
                "",
            )

    advanced_map = [
        ("ExposureBiasValue", "Exposure bias"),
        ("ExposureProgram", "Exposure program"),
        ("MeteringMode", "Metering mode"),
        ("WhiteBalance", "White balance"),
        ("SceneCaptureType", "Scene capture"),
        ("LightSource", "Light source"),
        ("ColorSpace", "Color space"),
        ("Orientation", "Orientation"),
        ("PixelXDimension", "Pixel width"),
        ("PixelYDimension", "Pixel height"),
        ("ComponentsConfiguration", "Components"),
        ("SensingMethod", "Sensing method"),
        ("CustomRendered", "Custom rendered"),
        ("GainControl", "Gain control"),
        ("Contrast", "Contrast"),
        ("Saturation", "Saturation"),
        ("Sharpness", "Sharpness"),
    ]

    for source, target in advanced_map:
        if source in raw and raw[source]:
            result["advanced"][target] = raw[source]

    # ---------------- GPS ----------------

    try:
        gps_ifd = exif.get_ifd(0x8825)

        gps = {
            GPSTAGS.get(tag_id, tag_id): value
            for tag_id, value in gps_ifd.items()
        }

        lat = _gps_decimal(gps.get("GPSLatitude"))
        lon = _gps_decimal(gps.get("GPSLongitude"))

        if lat is not None and gps.get("GPSLatitudeRef") == "S":
            lat = -lat

        if lon is not None and gps.get("GPSLongitudeRef") == "W":
            lon = -lon

        if lat is not None and lon is not None:
            result["location"]["Latitude"] = f"{lat:.6f}"
            result["location"]["Longitude"] = f"{lon:.6f}"

            result["location"]["Map"] = (
                f"https://www.google.com/maps?q={lat},{lon}"
            )

        for source, target in [
            ("GPSAltitude", "Altitude"),
            ("GPSSpeed", "Speed"),
            ("GPSSpeedRef", "Speed unit"),
            ("GPSDateStamp", "GPS date"),
            ("GPSTimeStamp", "GPS time"),
        ]:
            if source in gps:
                result["location"][target] = _safe_text(
                    gps[source]
                )

    except Exception:
        pass

    return result


# ---------------------------------------------------------
# Main metadata reader
# ---------------------------------------------------------

def read_metadata(path):
    """
    Main PhotoMeta 2.0 metadata reader.

    Returns a structured dictionary suitable for:
    - UI cards
    - JSON export
    - comparison
    - privacy scanner
    """

    if not path:
        raise ValueError("No image path supplied.")

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    data = {
        "camera": {},
        "time": {},
        "location": {},
        "settings": {},
        "advanced": {},
        "file": {},
        "xmp": {},
        "png": {},
        "privacy": {},
        "hash": {},
        "raw": {},
    }

    # ---------------- File information ----------------

    file_size = os.path.getsize(path)

    data["file"]["Name"] = os.path.basename(path)
    data["file"]["Size"] = f"{file_size / 1024:.1f} KB"
    data["file"]["SHA-256"] = sha256_file(path)

    with open(path, "rb") as file:
        raw_bytes = file.read()

    data["file"]["Bytes"] = str(file_size)

    # ---------------- Image information ----------------

    with Image.open(path) as image:
        data["file"]["Format"] = image.format or "Unknown"
        data["file"]["Resolution"] = (
            f"{image.width} x {image.height}"
        )

        megapixels = (
            image.width * image.height
        ) / 1_000_000

        data["file"]["Megapixels"] = (
            f"{megapixels:.2f} MP"
        )

        data["file"]["Mode"] = image.mode

        if image.width and image.height:
            data["file"]["Aspect ratio"] = (
                f"{image.width / image.height:.3f}"
            )

        # ICC profile
        if image.info.get("icc_profile"):
            data["file"]["ICC profile"] = "Present"

        # EXIF
        exif_data = _read_exif(image)

        for section in (
            "camera",
            "time",
            "location",
            "settings",
            "advanced",
        ):
            data[section].update(
                exif_data.get(section, {})
            )

        data["raw"]["EXIF"] = exif_data.get(
            "raw",
            {},
        )

        # PNG textual metadata
        if image.format == "PNG":
            data["png"] = _png_text_metadata(image)

        # Perceptual hash
        data["hash"]["Perceptual"] = _average_hash(
            image
        )

        # XMP
        xmp = _extract_xmp(raw_bytes)

        if xmp:
            data["xmp"]["Present"] = "Yes"
            data["xmp"].update(
                _xmp_summary(xmp)
            )
            data["raw"]["XMP"] = xmp

    # ---------------- Privacy scan ----------------

    privacy = []

    if data["location"].get("Latitude") and data["location"].get(
        "Longitude"
    ):
        privacy.append("GPS location")

    if data["camera"].get("Brand") or data["camera"].get(
        "Model"
    ):
        privacy.append("Camera information")

    if data["time"].get("Taken on"):
        privacy.append("Capture date/time")

    if data["camera"].get("Author"):
        privacy.append("Author information")

    if data["camera"].get("Copyright"):
        privacy.append("Copyright information")

    if data["camera"].get("Software"):
        privacy.append("Software information")

    if data["xmp"].get("Present") == "Yes":
        privacy.append("XMP metadata")

    data["privacy"]["Detected"] = privacy
    data["privacy"]["Count"] = len(privacy)

    if data["location"].get("Latitude"):
        data["privacy"]["Risk"] = "HIGH"
    elif len(privacy) >= 2:
        data["privacy"]["Risk"] = "MEDIUM"
    elif privacy:
        data["privacy"]["Risk"] = "LOW"
    else:
        data["privacy"]["Risk"] = "NONE"

    return data


# ---------------------------------------------------------
# JSON export helper
# ---------------------------------------------------------

def metadata_to_json(data, pretty=True):
    """Convert metadata to JSON text."""

    return json.dumps(
        data,
        indent=2 if pretty else None,
        ensure_ascii=False,
        default=str,
    )


# ---------------------------------------------------------
# Flatten helper for Compare UI
# ---------------------------------------------------------

def flatten_metadata(data):
    """
    Convert nested metadata into a simple key/value dictionary.
    Useful for Compare.
    """

    result = {}

    for section, values in data.items():

        if not isinstance(values, dict):
            continue

        for key, value in values.items():

            if key == "Map":
                continue

            if isinstance(value, (dict, list)):
                value = json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                )

            result[f"{section}.{key}"] = str(value)

    return result
