# Meme generator api

Flask API that generates "shooting star" meme videos. All routes are prefixed with
`/api/shooting-stars`.

Production: https://meme-creator-api.milovanderpas.fun

## How it works

Rendering runs asynchronously: the API queues a job in a SQLite store
(`data/renders.db`) and a separate worker process (`worker.py`) renders jobs
one at a time, writing real progress back to the store.

- `POST /api/shooting-stars/renders` — multipart form:
  - `image` (required): png/jpg/jpeg
  - `template`: `meme_template_2` (default) or `meme_template`
  - `remove_background`: `1` to auto-cut the subject out of the image (rembg)
  - `intro_mode`: `default` | `custom` | `none`
  - `intro` (when `intro_mode=custom`): mp4/mov/webm/m4v/avi, max 60s
  - Returns `202 {render_id, status_url}`
- `GET /api/shooting-stars/renders/<id>` — poll endpoint:
  `{status: queued|processing|finished|failed, stage, progress: 0-100,
  queue_position?, cutout_image?, output_video?, error?}`
  (`cutout_image` appears as soon as the background removal is done, while
  the video is still rendering)
- `GET /api/shooting-stars/outputs/<file>` — serves rendered videos/cutouts
- `GET /api/shooting-stars/remove_files` — cleanup (called hourly by Ofelia);
  skips files still needed by queued/processing jobs
- `POST /api/shooting-stars/upload` — legacy synchronous endpoint, kept for
  older frontend builds; new clients should use `/renders` + polling

The music is always placed so the beat drop lands exactly on the
intro → template transition, whatever the intro length: short intros skip the
start of the buildup, long intros delay the song, and without an intro the
video opens right on the drop. Custom intros keep their own audio, mixed
over the buildup. The drop sits at 23.2s in `audio.mp3` (measured; the
default 23s intro was cut to match) — override with `DROP_SECONDS` if the
song file ever changes.

Env vars (all optional): `UPLOAD_FOLDER`, `OUTPUT_FOLDER`, `DATA_DIR`,
`REMBG_MODEL` (default `isnet-general-use`), `INTRO_MAX_SECONDS` (default 60),
`DROP_SECONDS` (default 23.2), `PORT` (dev server only, default 5000).

## local testing

Use a virtual environment — installing into the global Python fails on
Windows when another process has `cv2.pyd` loaded, and this project's pins
would fight globally installed packages.

```powershell
cd app
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell — Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
python app.py      # API on :5000
python worker.py   # render worker (second terminal, activate the venv there too)
```

The first render with `remove_background=1` downloads the ~180MB ONNX model
to `~/.u2net` once (in the Docker image it is already baked in).

Or with Docker:
```sh
docker build -t meme-generator-api ./app
docker run --rm -p 5000:5000 meme-generator-api                     # API
docker run --rm meme-generator-api python worker.py                 # worker
```
(For a working end-to-end setup the two containers must share the
`uploads`, `outputs` and `data` directories — see `docker-compose.prod.yml`.)

## deployment

Push to `main` → GitHub Actions builds the image, pushes it to Docker Hub
(`milovdpas8/meme-generator-api`) and deploys it to the VPS via Docker Compose.
Compose runs two containers from the same image: `meme-generator` (API) and
`meme-generator-worker` (renderer), sharing named volumes for uploads,
outputs and the job database.
See the VPS docs (repo `vps`, doc 04) for the pattern and required GitHub secrets:
`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `VPS_HOST`, `VPS_USER`, `VPS_SSH_PRIVATE_KEY`.

## regenerating requirements.txt
```sh
pipreqs .
```
(Check the output — pipreqs once emitted `opencv-python=...` with a single `=`, which breaks `pip install`.
`rembg[cpu]` and `pillow` are hand-added; pipreqs won't pick the extra up.)
