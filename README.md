# Meme generator api

Flask API that generates "shooting star" meme videos. All routes are prefixed with
`/api/shooting-stars` (e.g. `POST /api/shooting-stars/upload`).

Production: https://meme-creator-api.milovanderpas.fun

## local testing
```sh
cd app
pip install -r requirements.txt
python app.py
```

Or with Docker:
```sh
docker build -t meme-generator-api ./app
docker run --rm -p 5000:5000 meme-generator-api
```

## deployment

Push to `main` → GitHub Actions builds the image, pushes it to Docker Hub
(`milovdpas8/meme-generator-api`) and deploys it to the VPS via Docker Compose.
See the VPS docs (repo `vps`, doc 04) for the pattern and required GitHub secrets:
`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `VPS_HOST`, `VPS_USER`, `VPS_SSH_PRIVATE_KEY`.

## regenerating requirements.txt
```sh
pipreqs .
```
(Check the output — pipreqs once emitted `opencv-python=...` with a single `=`, which breaks `pip install`.)
