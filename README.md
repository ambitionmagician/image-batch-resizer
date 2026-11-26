# Image Batch Resizer

Convert a folder of images to JPEG, PNG, or WebP while preserving its directory structure. Files are identified by content, not extension. EXIF orientation is applied before fitting the image within the requested bounds.

## Install

Save the script as `image_batch_resizer.py`. Use Python 3.8+ with a compatible Pillow release:

    python -m pip install "Pillow>=10"

## Usage

    python image_batch_resizer.py --help
    python image_batch_resizer.py photos --out-dir exports --max-width 1600 --max-height 1200 --format jpg --quality 90
    python image_batch_resizer.py photos --out-dir photos/previews --max-width 800 --format webp --watermark "Proof" --corner bottom-left
    python image_batch_resizer.py icons --out-dir enlarged --max-height 128 --allow-upscale --format png

Either dimension may be omitted. With neither bound, dimensions stay unchanged. Resizing preserves proportions to within integer-pixel rounding; it does not crop or pad. JPEG is the default format and uses quality 85 unless overridden.

## Behavior and limits

- An output directory inside the source tree is excluded from traversal. The source itself and its ancestors are not valid destinations.
- Existing destinations are never replaced. If two inputs map to the same output name, the first successfully written file wins. Use separate, trusted directories that are not being moved or modified during the run.
- Unidentified files and existing destinations produce warnings and count as skips. Read, encode, and traversal errors are reported separately. Exit status: `0` for completion without errors (skips allowed), `1` for batch errors, `2` for setup or argument errors.
- Only the first frame or page is processed. Output uses 8-bit channels; PNG and WebP retain transparency, while JPEG composites onto white. Metadata and color profiles are not preserved.
- Watermarks use Pillow’s default font at a fixed size. Long text may clip, and glyph coverage depends on the font. WebP requires a WebP-enabled Pillow build.
- Images are processed one at a time in memory. Pillow’s oversized-input warning is treated as an error. Output files are created exclusively, but a hard interruption can leave a partial file; remove it before retrying.
