"""Render a title card: the movie's name in bold white on black, as a PNG.

It is embedded as the MP4's cover art, so the TV app's thumbnail tells which
movie or episode a file is. Homebrew's ffmpeg can't draw text (no
`drawtext`), so the image is drawn with macOS's own AppKit through
`osascript` -- no extra dependency.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import Ipadmp4Error

# In points; on a Retina Mac the PNG gets twice as many pixels.
WIDTH, HEIGHT = 1280, 720

# JavaScript for Automation: run(argv) gets text, width, height, output path.
_SCRIPT = r"""
ObjC.import('AppKit');
function run(argv) {
  const [text, w, h, out] = [argv[0], Number(argv[1]), Number(argv[2]), argv[3]];
  const img = $.NSImage.alloc.initWithSize($.NSMakeSize(w, h));
  img.lockFocus;
  $.NSColor.blackColor.setFill;
  $.NSRectFill($.NSMakeRect(0, 0, w, h));
  const style = $.NSMutableParagraphStyle.alloc.init;
  style.setAlignment(1);  // centered ($.NSTextAlignmentCenter has a stale value in JXA)
  const margin = w * 0.08, width = w - 2 * margin;
  let size = h * 0.12, attrs, bounds;
  for (;;) {  // shrink the font until the wrapped text fits in 80% of the height
    attrs = $.NSMutableDictionary.dictionary;
    attrs.setObjectForKey($.NSFont.boldSystemFontOfSize(size), $.NSFontAttributeName);
    attrs.setObjectForKey($.NSColor.whiteColor, $.NSForegroundColorAttributeName);
    attrs.setObjectForKey(style, $.NSParagraphStyleAttributeName);
    bounds = $(text).boundingRectWithSizeOptionsAttributes(
      $.NSMakeSize(width, 1e6), $.NSStringDrawingUsesLineFragmentOrigin, attrs);
    if (bounds.size.height <= h * 0.8 || size < 12) break;
    size *= 0.9;
  }
  const rect = $.NSMakeRect(margin, (h - bounds.size.height) / 2, width, bounds.size.height);
  $(text).drawWithRectOptionsAttributes(rect, $.NSStringDrawingUsesLineFragmentOrigin, attrs);
  img.unlockFocus;
  const rep = $.NSBitmapImageRep.imageRepWithData(img.TIFFRepresentation);
  const png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $.NSDictionary.dictionary);
  if (!png.writeToFileAtomically(out, true)) throw new Error('cannot write ' + out);
}
"""


def wrappable(text: str) -> str:
    """Allow line breaks after "." "_" "-" too, so release names like
    "Show.S02E01.720p.BluRay" wrap between their parts, not mid-word."""
    return "".join(c + "\u200b" if c in "._-" else c for c in text)


def render_title_card(text: str, out: Path) -> None:
    args = [wrappable(text), str(WIDTH), str(HEIGHT), str(out)]
    cmd = ["osascript", "-l", "JavaScript", "-e", _SCRIPT, *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise Ipadmp4Error("cannot draw cover art: osascript not found (macOS only)") from None
    if result.returncode != 0 or not out.exists():
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise Ipadmp4Error(f"cannot draw cover art: {detail}")
