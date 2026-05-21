"""
Compress dashboard deal photos PNG → JPEG.

Walker (May 19 call) flagged that the hi-res PNGs Lilato shipped were slow
to load in the deal one-pager modal. JPEG at quality ~82 cuts each file to
roughly 1/10th the size with no perceptible quality loss at the modal's
display dimensions.

What this script does:
- Reads every `images/*.png`
- Writes `images/<name>.jpg` next to it at quality 82, optimize=True
- Skips files where a `.jpg` already exists and is newer than the source
- Preserves the original `.png` (non-destructive — Lilato can remove them
  in a separate housekeeping commit once the JPEGs are confirmed)
- Prints per-file shrink ratio + before/after total

Usage:
    python3 compress_images.py            # compress all
    python3 compress_images.py --force    # re-compress even if .jpg is newer
    python3 compress_images.py --quality 85  # custom quality (default 82)

Requires Pillow:  pip3 install pillow
"""
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("This script needs Pillow. Install with:  pip3 install pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
IMAGES_DIR = ROOT / "images"


def human(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f}{unit}"
        nbytes /= 1024
    return f"{nbytes:.1f}TB"


def compress_one(png_path: Path, quality: int, force: bool) -> tuple[int, int, str]:
    """Returns (orig_bytes, new_bytes, status)."""
    jpg_path = png_path.with_suffix(".jpg")
    orig_bytes = png_path.stat().st_size

    if jpg_path.exists() and not force:
        if jpg_path.stat().st_mtime >= png_path.stat().st_mtime:
            return orig_bytes, jpg_path.stat().st_size, "skipped (up-to-date)"

    with Image.open(png_path) as im:
        # JPEG doesn't support alpha — flatten transparent PNGs onto white.
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.save(
            jpg_path,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )

    new_bytes = jpg_path.stat().st_size
    return orig_bytes, new_bytes, "compressed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quality", type=int, default=82, help="JPEG quality, 1-95 (default: 82)")
    parser.add_argument("--force", action="store_true", help="Re-compress even if .jpg is newer than source")
    args = parser.parse_args()

    if not IMAGES_DIR.exists():
        print(f"missing: {IMAGES_DIR}", file=sys.stderr)
        return 1

    pngs = sorted(IMAGES_DIR.glob("*.png"))
    if not pngs:
        print("no PNGs found in images/")
        return 0

    total_orig = 0
    total_new = 0
    compressed_count = 0
    skipped_count = 0

    for png in pngs:
        try:
            orig, new, status = compress_one(png, args.quality, args.force)
        except Exception as e:
            print(f"  ! {png.name}: {e}", file=sys.stderr)
            continue
        total_orig += orig
        total_new += new
        ratio = (1 - new / orig) * 100 if orig > 0 else 0
        print(f"  {png.name:32s} {human(orig):>10s} -> {human(new):>10s}  ({ratio:+5.1f}%)  {status}")
        if status == "compressed":
            compressed_count += 1
        else:
            skipped_count += 1

    overall = (1 - total_new / total_orig) * 100 if total_orig > 0 else 0
    print()
    print(f"{compressed_count} compressed, {skipped_count} skipped")
    print(f"total: {human(total_orig)} -> {human(total_new)}  ({overall:+.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
