#!/usr/bin/env python3
"""Resize, convert, and optionally watermark a directory tree of images."""

import argparse
import os
import sys
import warnings
from contextlib import ExitStack
from pathlib import Path


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def jpeg_quality(value):
    number = positive_int(value)
    if number > 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return number


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="source directory")
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="destination directory (existing files are skipped)")
    parser.add_argument("--max-width", type=positive_int, help="width limit in pixels")
    parser.add_argument("--max-height", type=positive_int, help="height limit in pixels")
    parser.add_argument("--allow-upscale", action="store_true",
                        help="allow enlargement to fit the specified bounds")
    parser.add_argument("--format", choices=("jpg", "png", "webp"), default="jpg",
                        help="output format (default: jpg)")
    parser.add_argument("--quality", "--jpeg-quality", type=jpeg_quality, default=85,
                        help="JPEG quality, 1–100 (default: 85)")
    parser.add_argument("--watermark", metavar="TEXT", help="semi-transparent text stamp")
    parser.add_argument("--corner", choices=("top-left", "top-right", "bottom-left",
                                              "bottom-right"), default="bottom-right",
                        help="watermark position (default: bottom-right)")
    return parser.parse_args()


def fit_size(width, height, args):
    """Choose the tighter ratio using integers; round the other axis down."""
    w, h = args.max_width, args.max_height
    if w is None and h is None:
        return width, height
    if h is None or (w is not None and w * height <= h * width):
        numerator, denominator = w, width
    else:
        numerator, denominator = h, height
    if numerator >= denominator and not args.allow_upscale:
        return width, height
    return (max(1, width * numerator // denominator),
            max(1, height * numerator // denominator))


def stamp(image, text, corner, Image, ImageDraw):
    with Image.new("RGBA", image.size) as overlay:
        draw = ImageDraw.Draw(overlay)
        left, top, right, bottom = draw.multiline_textbbox((0, 0), text, stroke_width=1)
        pad = min(8, min(image.size) // 20)
        x = pad - left if corner.endswith("left") else image.width - pad - right
        y = pad - top if corner.startswith("top") else image.height - pad - bottom
        draw.multiline_text((x, y), text, fill=(255, 255, 255, 165),
                            stroke_width=1, stroke_fill=(0, 0, 0, 145))
        image.alpha_composite(overlay)


def output_parent(root, relative_dir):
    """Do not follow links encountered in the mirrored output tree."""
    parent = root
    for part in relative_dir.parts:
        parent = parent / part
        if parent.is_symlink() or parent.resolve() != parent:
            raise OSError(f"redirected output directory: {parent}")
        parent.mkdir(exist_ok=True)
    return parent


def process(source, relative, output, args, Image, ImageDraw, ImageOps):
    with ExitStack() as stack:
        def own(image):
            stack.callback(image.close)
            return image

        original = stack.enter_context(Image.open(source))
        oriented = own(ImageOps.exif_transpose(original))
        image = own(oriented.convert("RGBA"))
        size = fit_size(*image.size, args)
        if size != image.size:
            if Image.MAX_IMAGE_PIXELS is not None and size[0] * size[1] > Image.MAX_IMAGE_PIXELS:
                raise ValueError("requested output exceeds Pillow's pixel safety limit")
            image = own(image.resize(size, Image.Resampling.LANCZOS))
        if args.watermark:
            stamp(image, args.watermark, args.corner, Image, ImageDraw)
        options = {}
        if args.format == "jpg":
            flattened = own(Image.new("RGB", image.size, "white"))
            flattened.paste(image, mask=own(image.getchannel("A")))
            image = flattened
            options["quality"] = args.quality
        image.info.clear()
        parent = output_parent(output, relative.parent)
        target = parent / relative.with_suffix("." + args.format).name
        try:
            stream = target.open("xb")
        except FileExistsError:
            return False
        try:
            with stream:
                image.save(stream, format={"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}[
                    args.format], **options)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    return True


def warn(message):
    print(f"warning: {message}", file=sys.stderr)


def main():
    args = parse_args()
    try:
        from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError, features
        from PIL.Image import Resampling  # Present in supported Pillow versions.
    except ImportError as exc:
        print(f"error: Pillow is required ({exc}); install with: "
              'python -m pip install --upgrade "Pillow>=10"', file=sys.stderr)
        return 2
    if args.format == "webp" and not features.check("webp"):
        print("error: this Pillow build has no WebP codec", file=sys.stderr)
        return 2

    try:
        source = args.input_dir.resolve(strict=True)
        output = args.out_dir.resolve()
        if not source.is_dir():
            raise ValueError(f"not a directory: {source}")
        if output == source or output in source.parents:
            raise ValueError("output cannot be the source directory or its ancestor")
        output.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    written = skipped = errors = 0

    def walk_error(exc):
        nonlocal errors
        errors += 1
        warn(exc)

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        for base, dirs, files in os.walk(source, onerror=walk_error, followlinks=False):
            folder = Path(base)
            children = []
            for name in sorted(dirs):
                child = folder / name
                try:
                    if child != output and not child.is_symlink() and child.resolve() == child:
                        children.append(name)
                except (OSError, RuntimeError) as exc:
                    walk_error(exc)
            dirs[:] = children
            for name in sorted(files):
                path = folder / name
                try:
                    if path.is_symlink() or not path.is_file():
                        skipped += 1
                        warn(f"skipping link or non-regular file: {path}")
                    elif process(path, path.relative_to(source), output, args,
                                 Image, ImageDraw, ImageOps):
                        written += 1
                    else:
                        skipped += 1
                        warn(f"destination exists; skipped {path}")
                except UnidentifiedImageError:
                    skipped += 1
                    warn(f"unidentified image: {path}")
                except Exception as exc:
                    # Decoder plugins can raise format-specific exceptions.
                    errors += 1
                    warn(f"{path}: {type(exc).__name__}: {exc}")

    print(f"Written: {written} | Skipped: {skipped} | Errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
