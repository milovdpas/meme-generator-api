"""Render worker: claims queued render jobs and processes them one at a time.

Runs as its own container (see docker-compose.prod.yml) next to the web API,
sharing the uploads/outputs/data volumes. Progress is written back to the job
store, where the API's poll endpoint reads it.
"""
import logging
import os
import time

import job_store
from scripts.create_shooting_star_meme import create_shooting_star_meme

UPLOAD_FOLDER = os.path.abspath(os.environ.get('UPLOAD_FOLDER', 'uploads'))
OUTPUT_FOLDER = os.path.abspath(os.environ.get('OUTPUT_FOLDER', 'outputs'))
DEFAULT_INTRO = 'intro.mp4'
MUSIC_FILE = 'audio.mp3'
INTRO_MAX_SECONDS = float(os.environ.get('INTRO_MAX_SECONDS', 60))
POLL_INTERVAL = 1.0

HEARTBEAT_FILE = os.path.join(job_store.DATA_DIR, 'worker_heartbeat')

log = logging.getLogger('worker')


def beat():
    """Touch the heartbeat file (used by the container healthcheck)."""
    with open(HEARTBEAT_FILE, 'w') as f:
        f.write(str(time.time()))


def _resolve_intro(job):
    if job['intro_mode'] == 'none':
        return None
    if job['intro_mode'] == 'custom':
        intro_path = job['intro_path']
        if not intro_path or not os.path.exists(intro_path):
            raise ValueError('The uploaded intro video is no longer available.')
        _check_intro_duration(intro_path)
        return intro_path
    return DEFAULT_INTRO


def _check_intro_duration(intro_path):
    from moviepy.editor import VideoFileClip
    clip = VideoFileClip(intro_path)
    try:
        duration = clip.duration
    finally:
        clip.close()
    if duration > INTRO_MAX_SECONDS:
        raise ValueError(
            f'Intro video is too long ({duration:.0f}s, max {INTRO_MAX_SECONDS:.0f}s).')


def process_job(job):
    job_id = job['id']
    image_path = job['image_path']
    if not os.path.exists(image_path):
        raise ValueError('The uploaded image is no longer available.')

    if job['remove_bg']:
        job_store.set_progress(job_id, 1, stage='removing_background')
        beat()
        from scripts.remove_background import remove_background  # lazy: loads the ONNX model
        cutout_file = f'{job_id}_cutout.png'
        remove_background(image_path, os.path.join(OUTPUT_FOLDER, cutout_file))
        job_store.set_cutout(job_id, cutout_file)
        image_path = os.path.join(OUTPUT_FOLDER, cutout_file)

    intro_path = _resolve_intro(job)
    job_store.set_progress(job_id, 5, stage='rendering')

    # Throttle DB writes to whole-percent changes (the callback fires per frame)
    last_percent = -1

    def on_progress(fraction):
        nonlocal last_percent
        percent = int(5 + fraction * 94)
        if percent != last_percent:
            last_percent = percent
            job_store.set_progress(job_id, percent, stage='rendering')
            beat()

    output_file = f'{job_id}.mp4'
    create_shooting_star_meme(image_path, f"{job['template']}.mp4", MUSIC_FILE,
                              intro_path, os.path.join(OUTPUT_FOLDER, output_file),
                              progress_callback=on_progress)
    job_store.finish_job(job_id, output_file)
    log.info('Job %s finished', job_id)


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    job_store.init_db()

    requeued, failed = job_store.recover_interrupted_jobs()
    if requeued or failed:
        log.info('Recovered interrupted jobs: %d requeued, %d failed',
                 requeued, failed)

    log.info('Worker started, waiting for render jobs')
    while True:
        beat()
        try:
            job = job_store.claim_next_job()
        except Exception:
            log.exception('Failed to claim a job')
            time.sleep(POLL_INTERVAL)
            continue

        if job is None:
            time.sleep(POLL_INTERVAL)
            continue

        log.info('Processing job %s (template=%s, remove_bg=%s, intro=%s)',
                 job['id'], job['template'], bool(job['remove_bg']),
                 job['intro_mode'])
        try:
            process_job(job)
        except Exception as exc:
            log.exception('Job %s failed', job['id'])
            job_store.fail_job(job['id'], exc)


if __name__ == '__main__':
    main()
