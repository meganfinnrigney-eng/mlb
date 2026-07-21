"""
Claude Artifacts block external font-CDN requests via CSP, so a plain
<link href="https://fonts.googleapis.com/..."> silently falls back to
system fonts inside the published artifact. This fetches Oswald/Inter from
Google Fonts (works fine here since it runs inside GitHub Actions, which has
normal internet access) and inlines the woff2 files as base64 data URIs
into a @font-face CSS block, so the published artifact needs no external
font request at all.

Only the basic-latin subset is kept (this report is English-only) to keep
the inlined payload small.
"""

import base64
import re

import requests

CSS2_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Oswald:wght@500;700&family=Inter:wght@400;600&display=swap"
)

# a browser UA is required - Google serves woff2 only to modern browsers
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_FONT_FACE_RE = re.compile(r"@font-face\s*\{([^}]*)\}", re.S)
_PROP_RE = re.compile(r"([\w-]+):\s*([^;]+);")
_SRC_URL_RE = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+)\)\s*format\('woff2'\)")


def build_inline_font_css(timeout=20):
    r = requests.get(CSS2_URL, headers=BROWSER_HEADERS, timeout=timeout)
    r.raise_for_status()
    css = r.text

    blocks = []
    for block_match in _FONT_FACE_RE.finditer(css):
        block = block_match.group(1)
        props = dict(_PROP_RE.findall(block))
        if "U+0000-00FF" not in props.get("unicode-range", ""):
            continue  # keep only the basic-latin subset per weight/family

        src_m = _SRC_URL_RE.search(block)
        if not src_m:
            continue

        font_bytes = requests.get(src_m.group(1), headers=BROWSER_HEADERS, timeout=timeout).content
        b64 = base64.b64encode(font_bytes).decode("ascii")

        family = props.get("font-family", "").strip("'\"")
        weight = props.get("font-weight", "400")
        style = props.get("font-style", "normal")
        blocks.append(
            f"@font-face {{ font-family: '{family}'; font-style: {style}; font-weight: {weight}; "
            f"font-display: swap; src: url(data:font/woff2;base64,{b64}) format('woff2'); }}"
        )

    if not blocks:
        raise ValueError("no matching @font-face blocks found in Google Fonts response")
    return "\n".join(blocks)
