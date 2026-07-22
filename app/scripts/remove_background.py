"""Automatic subject cutout: removes the background of an uploaded image.

Uses rembg (U²-Net / ISNet ONNX models on CPU). The model auto-detects the
salient person/object; the result is an RGBA PNG where everything else is
transparent. The ONNX session is loaded lazily and kept as a singleton, so
only the process that actually cuts out images (the worker) pays the RAM.
"""
import os

from PIL import Image, ImageOps

_session = None


def _get_session():
    global _session
    if _session is None:
        from rembg import new_session
        _session = new_session(os.environ.get('REMBG_MODEL', 'isnet-general-use'))
    return _session


def remove_background(input_path, output_path):
    """Cut the subject out of input_path and save it as an RGBA PNG."""
    from rembg import remove

    with Image.open(input_path) as img:
        img = ImageOps.exif_transpose(img).convert('RGBA')
        result = remove(img, session=_get_session(), post_process_mask=True)
    result.save(output_path, 'PNG')
    return output_path
