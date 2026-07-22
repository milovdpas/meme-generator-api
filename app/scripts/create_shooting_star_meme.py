import math
import os
import random

import cv2
import numpy as np
from PIL import Image, ImageOps
from moviepy.editor import (AudioFileClip, CompositeAudioClip,
                            CompositeVideoClip, VideoClip, VideoFileClip,
                            concatenate_videoclips)
from proglog import ProgressBarLogger

# Where the beat drop sits in audio.mp3 (measured; the default 23s intro was
# cut to match it). The song is always placed so the drop lands exactly on
# the intro -> template transition, whatever the intro length.
DROP_SECONDS = float(os.environ.get('DROP_SECONDS', 23.2))

# Sprite animation tuning (fractions of the video size)
BASE_HEIGHT_FRAC = 0.36   # sprite source is prepared at the largest size...
MIN_HEIGHT_FRAC = 0.20    # ...and per-instance zoom scales it down from there
MAX_WIDTH_FRAC = 0.45
ZOOM_RANGE = (0.55, 1.35)  # fly-away / fly-towards-camera extremes
WINDOW_SECONDS = 5


def _load_rgba(image_path):
    """Load an image as an RGBA numpy array (EXIF-rotated, alpha preserved)."""
    with Image.open(image_path) as img:
        img = ImageOps.exif_transpose(img)
        return np.array(img.convert('RGBA'))


def _prepare_sprite(image_path, video_width, video_height):
    """Resize the image and pad it onto a transparent square canvas.

    The canvas is as large as the image diagonal, so the image never gets
    clipped while rotating, and the transparent padding keeps the video
    visible behind it. The sprite is prepared at the LARGEST size an
    instance can use; instances zoom down/up from there.
    """
    rgba = _load_rgba(image_path)
    height, width = rgba.shape[:2]

    scale = min((video_height * BASE_HEIGHT_FRAC) / height,
                (video_width * MAX_WIDTH_FRAC) / width)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    rgba = cv2.resize(rgba, new_size, interpolation=cv2.INTER_AREA)
    height, width = rgba.shape[:2]

    size = int(math.ceil(math.hypot(width, height)))
    canvas = np.zeros((size, size, 4), dtype=np.uint8)
    top = (size - height) // 2
    left = (size - width) // 2
    canvas[top:top + height, left:left + width] = rgba
    return canvas


def _rotating_sprite_clip(sprite_rgba, duration, rot_speed=360.0, zoom=None):
    """Clip of the sprite tumbling (and optionally zooming), mask included.

    Rotation and zoom are baked into a single cv2.warpAffine per frame, with
    the alpha channel warped along and fed to moviepy as the clip mask — so
    the area around the image stays transparent instead of turning into a
    black square. (moviepy's own dynamic resize would corrupt the mask.)

    zoom: optional callable t -> scale factor (1.0 = prepared size). The
    canvas is padded so the sprite fits at the largest zoom, which keeps the
    frame size constant and center-anchored positioning trivial.
    """
    base = sprite_rgba.shape[0]
    zoom_max = 1.0
    if zoom is not None:
        zoom_max = max(zoom(t) for t in np.linspace(0, duration, 30))
    size = int(math.ceil(base * max(1.0, zoom_max)))
    if size > base:
        padded = np.zeros((size, size, 4), dtype=np.uint8)
        offset = (size - base) // 2
        padded[offset:offset + base, offset:offset + base] = sprite_rgba
        sprite_rgba = padded

    center = ((size - 1) / 2, (size - 1) / 2)
    last = {}  # frame and mask ask for the same t back-to-back: keep the last warp

    def warped(t):
        key = round(t, 5)
        if last.get('key') != key:
            angle = (rot_speed * t) % 360.0
            scale = zoom(t) if zoom is not None else 1.0
            matrix = cv2.getRotationMatrix2D(center, angle, scale)
            last['key'] = key
            last['frame'] = cv2.warpAffine(
                sprite_rgba, matrix, (size, size),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(0, 0, 0, 0),
            )
        return last['frame']

    clip = VideoClip(lambda t: warped(t)[:, :, :3], duration=duration)
    mask = VideoClip(lambda t: warped(t)[:, :, 3] / 255.0,
                     ismask=True, duration=duration)
    return clip.set_mask(mask)


def _sprite_instances(video_width, video_height, duration, rng=random):
    """Randomized flight plans: several overlapping sprites per 5s window.

    Inspired by the classic meme: instances enter from a random edge, cross
    in a random direction at a random speed, tumble either way at their own
    pace, and either keep their size, shrink away or grow towards the camera.
    Returns plain-data specs (kept testable; callables are built later).
    """
    specs = []
    windows = max(1, int(duration // WINDOW_SECONDS))
    for window in range(windows):
        window_start = window * WINDOW_SECONDS
        for i in range(rng.choice((1, 2, 2, 3))):
            # the first sprite of a window flies in right away (and the very
            # first right at the drop), extras come staggered
            start = window_start + (rng.uniform(0.0, 0.4) if i == 0
                                    else rng.uniform(0.8, 2.5))
            if start >= duration - 1:
                continue
            edge = rng.choice(('left', 'right', 'top', 'bottom'))
            if edge == 'left':
                pos = (0.0, rng.uniform(0.1, 0.9))
                heading = rng.uniform(-40, 40)
            elif edge == 'right':
                pos = (1.0, rng.uniform(0.1, 0.9))
                heading = 180 + rng.uniform(-40, 40)
            elif edge == 'top':
                pos = (rng.uniform(0.1, 0.9), 0.0)
                heading = 90 + rng.uniform(-40, 40)
            else:
                pos = (rng.uniform(0.1, 0.9), 1.0)
                heading = 270 + rng.uniform(-40, 40)

            zoom_mode = rng.choice(('constant', 'shrink', 'grow', 'shrink'))
            specs.append({
                'start': start,
                'duration': min(rng.uniform(4.0, 6.0), duration - start),
                'entry': (pos[0] * video_width, pos[1] * video_height),
                'heading_deg': heading,
                'speed': rng.uniform(0.10, 0.30) * video_width,  # px/s
                'height_frac': rng.uniform(MIN_HEIGHT_FRAC, BASE_HEIGHT_FRAC),
                'zoom_mode': zoom_mode,
                'rot_speed': rng.choice((-1, 1)) * rng.uniform(150, 540),
            })
    return specs


def _zoom_function(spec):
    """Scale factor over the instance's life, relative to the base sprite."""
    ratio = spec['height_frac'] / BASE_HEIGHT_FRAC
    lo, hi = ZOOM_RANGE
    if spec['zoom_mode'] == 'shrink':
        start, end = hi, lo
    elif spec['zoom_mode'] == 'grow':
        start, end = lo, hi
    else:
        start, end = 1.0, 1.0
    life = max(spec['duration'], 0.001)
    return lambda t: ratio * (start + (end - start) * min(t / life, 1.0))


def _build_sprite_clips(sprite, specs):
    clips = []
    for spec in specs:
        clip = _rotating_sprite_clip(sprite, spec['duration'],
                                     rot_speed=spec['rot_speed'],
                                     zoom=_zoom_function(spec))
        half = clip.size[0] / 2
        entry_x, entry_y = spec['entry']
        dx = spec['speed'] * math.cos(math.radians(spec['heading_deg']))
        dy = spec['speed'] * math.sin(math.radians(spec['heading_deg']))

        def motion(t, entry_x=entry_x, entry_y=entry_y, dx=dx, dy=dy, half=half):
            # entry/dx/dy describe the sprite CENTER; moviepy positions top-left
            return int(entry_x + dx * t - half), int(entry_y + dy * t - half)

        clips.append(clip.set_start(spec['start']).set_position(motion))
    return clips


def _song_window(intro_duration, video_duration, music_duration,
                 drop=DROP_SECONDS):
    """Where to cut and place the song so its drop hits the intro's end.

    Returns (skip, start_in_video, end): play music[skip:end] starting at
    start_in_video. Short intros lose the start of the buildup; long intros
    get the song later so the drop still lands exactly on the transition.
    """
    skip = max(0.0, drop - intro_duration)
    start_in_video = max(0.0, intro_duration - drop)
    end = min(music_duration, skip + (video_duration - start_in_video))
    return skip, start_in_video, end


class _WriteProgressLogger(ProgressBarLogger):
    """Forwards moviepy's write progress (audio, then video frames) as 0..1."""

    def __init__(self, progress_callback):
        super().__init__()
        self._progress_callback = progress_callback

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr != 'index':
            return
        total = self.bars[bar].get('total') or 0
        if total <= 0:
            return
        fraction = min(1.0, max(0.0, value / total))
        # The audio is written first and is fast: map it to 0-10%,
        # the video frames (the slow part) to 10-100%
        if bar == 'chunk':
            overall = 0.10 * fraction
        else:
            overall = 0.10 + 0.90 * fraction
        self._progress_callback(overall)


def create_shooting_star_meme(image_path, template_video_path, music_path,
                              intro_video_path, output_video_path,
                              progress_callback=None):
    """Render the meme video.

    progress_callback, if given, is called with a float 0..1 while the
    output file is being written.
    """
    template_video = VideoFileClip(template_video_path)
    intro_video = None
    music = None
    try:
        video_width, video_height = template_video.size

        sprite = _prepare_sprite(image_path, video_width, video_height)
        specs = _sprite_instances(video_width, video_height,
                                  template_video.duration)
        image_clips = _build_sprite_clips(sprite, specs)

        video = CompositeVideoClip([template_video] + image_clips)

        intro_duration = 0.0
        intro_audio = None
        if intro_video_path:
            intro_video = VideoFileClip(intro_video_path)
            # Letterbox the intro to the template's size so user-uploaded
            # intros with any aspect ratio concatenate cleanly
            fit = min(video_width / intro_video.w, video_height / intro_video.h)
            intro = intro_video.resize(fit)
            if tuple(intro.size) != (video_width, video_height):
                intro = CompositeVideoClip([intro.set_position('center')],
                                           size=(video_width, video_height))
            intro_duration = intro.duration
            intro_audio = intro.audio  # user intros keep their own sound
            video = concatenate_videoclips([intro, video])

        if music_path:
            music = AudioFileClip(music_path)
            skip, start_in_video, end = _song_window(intro_duration,
                                                     video.duration,
                                                     music.duration)
            audio_parts = []
            if intro_audio is not None:
                audio_parts.append(intro_audio.set_start(0))
            if end > skip:
                audio_parts.append(music.subclip(skip, end).set_start(start_in_video))
            if audio_parts:
                video = video.set_audio(CompositeAudioClip(audio_parts))

        logger = _WriteProgressLogger(progress_callback) if progress_callback else 'bar'
        video.write_videofile(output_video_path, fps=15,  # Reduced FPS for faster output
                              threads=os.cpu_count() or 2, preset='faster',
                              logger=logger)
    finally:
        # The worker is long-lived: release ffmpeg readers and file handles
        for clip in (template_video, intro_video, music):
            if clip is not None:
                clip.close()

# Example usage
# create_shooting_star_meme("image.png", "meme_template_2.mp4", "audio.mp3", "intro.mp4", "output.mp4")
