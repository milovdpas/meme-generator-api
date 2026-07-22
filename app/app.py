from flask import Flask, Blueprint, request, jsonify, send_from_directory, url_for
from flask_cors import CORS
import os
from scripts.create_shooting_star_meme import create_shooting_star_meme
from scripts.remove_files import remove_old_files
import job_store
import logging
import uuid

app = Flask(__name__)
CORS(app)  # Allow all origins for development

# All public routes live under this prefix (the domain only serves this API)
api = Blueprint('shooting_stars', __name__, url_prefix='/api/shooting-stars')

# Absolute paths: file saves resolve against the process cwd while
# send_from_directory resolves against the app root — pin them to one place
app.config['UPLOAD_FOLDER'] = os.path.abspath(os.environ.get('UPLOAD_FOLDER', 'uploads'))
app.config['OUTPUT_FOLDER'] = os.path.abspath(os.environ.get('OUTPUT_FOLDER', 'outputs'))
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}
app.config['ALLOWED_INTRO_EXTENSIONS'] = {'mp4', 'mov', 'webm', 'm4v', 'avi'}
app.config['TEMPLATES'] = {'meme_template', 'meme_template_2'}
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # uploads incl. intro videos

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
job_store.init_db()

if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)


def file_extension(filename, allowed):
    if '.' not in filename:
        return None
    ext = filename.rsplit('.', 1)[1].lower()
    return ext if ext in allowed else None


@api.route('/renders', methods=['POST'])
def start_render():
    """Queue a render job; the worker container picks it up.

    Returns 202 with a render_id that can be polled on GET /renders/<id>.
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    ext = file_extension(file.filename, app.config['ALLOWED_EXTENSIONS'])
    if not ext:
        return jsonify({'error': 'Invalid file type'}), 400

    template = request.form.get('template', 'meme_template_2')
    if template not in app.config['TEMPLATES']:
        return jsonify({'error': 'Unknown template'}), 400

    remove_bg = request.form.get('remove_background', '0').lower() in ('1', 'true', 'yes', 'on')
    intro_mode = request.form.get('intro_mode', 'default')
    if intro_mode not in ('default', 'custom', 'none'):
        return jsonify({'error': 'Invalid intro_mode'}), 400

    render_id = str(uuid.uuid4())
    image_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{render_id}.{ext}')
    file.save(image_path)

    intro_path = None
    if intro_mode == 'custom':
        intro = request.files.get('intro')
        if intro is None or intro.filename == '':
            return jsonify({'error': 'No intro video uploaded'}), 400
        intro_ext = file_extension(intro.filename, app.config['ALLOWED_INTRO_EXTENSIONS'])
        if not intro_ext:
            return jsonify({'error': 'Invalid intro video type'}), 400
        intro_path = os.path.join(app.config['UPLOAD_FOLDER'],
                                  f'{render_id}_intro.{intro_ext}')
        intro.save(intro_path)

    job_store.create_job(render_id, template, image_path, remove_bg=remove_bg,
                         intro_mode=intro_mode, intro_path=intro_path)
    return jsonify({
        'render_id': render_id,
        'status_url': url_for('shooting_stars.render_status', render_id=render_id),
    }), 202


@api.route('/renders/<render_id>', methods=['GET'])
def render_status(render_id):
    job = job_store.get_job(render_id)
    if job is None:
        return jsonify({'error': 'Render not found'}), 404

    payload = {
        'id': job['id'],
        'status': job['status'],
        'stage': job['stage'],
        'progress': int(round(job['progress'])),
    }
    if job['status'] == 'queued':
        payload['queue_position'] = job['queue_position']
    if job['cutout_file']:
        payload['cutout_image'] = url_for('shooting_stars.serve_output',
                                          filename=job['cutout_file'])
    if job['status'] == 'finished':
        payload['output_video'] = url_for('shooting_stars.serve_output',
                                          filename=job['output_file'])
    if job['status'] == 'failed':
        payload['error'] = job['error']
    return jsonify(payload), 200


# Legacy synchronous endpoint, kept so older frontend builds keep working
# during the rollout. New clients should use POST /renders + polling.
@api.route('/upload', methods=['POST'])
def upload_file():
    if 'image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    ext = file_extension(file.filename, app.config['ALLOWED_EXTENSIONS'])
    if not ext:
        return jsonify({'error': 'Invalid file type'}), 400
    template = request.form.get('template', 'meme_template_2')
    if template not in app.config['TEMPLATES']:
        return jsonify({'error': 'Unknown template'}), 400
    file_id = str(uuid.uuid4())
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{file_id}.{ext}')
    file.save(file_path)
    output_file = f'{file_id}.mp4'
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_file)
    create_shooting_star_meme(file_path, f'{template}.mp4', 'audio.mp3', 'intro.mp4', output_path)
    return jsonify({'message': 'File processed successfully', 'output_video': url_for('shooting_stars.serve_output', filename=output_file)}), 200


@api.route('/remove_files', methods=['GET'])
def remove_files():
    try:
        # Never delete files a queued/processing job still needs
        keep = job_store.active_input_files(app.config['OUTPUT_FOLDER'])
        remove_old_files(app.config['UPLOAD_FOLDER'], keep=keep)
        remove_old_files(app.config['OUTPUT_FOLDER'], keep=keep)
        removed_jobs = job_store.cleanup_old_jobs()
        return jsonify({"status": "success",
                        "message": f"Old files removed successfully! ({removed_jobs} old job records purged)"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api.route('/outputs/<filename>')
def serve_output(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

app.register_blueprint(api)

# Unprefixed: used by the Docker healthcheck, not exposed publicly
@app.route('/health')
def health():
    return 'ok', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
