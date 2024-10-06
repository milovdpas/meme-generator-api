from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import cv2
import numpy as np
from moviepy.editor import *
import random
from scripts.create_shooting_star_meme import create_shooting_star_meme
from scripts.remove_files import remove_old_files
import logging
import uuid

app = Flask(__name__)
CORS(app)  # Allow all origins for development

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

if not os.path.exists(app.config['OUTPUT_FOLDER']):
    os.makedirs(app.config['OUTPUT_FOLDER'])

if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        template = request.form.get('template', 'meme_template_2')  # Get the selected template
        output_file = str(uuid.uuid4()) + '.mp4'
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_file)
        create_shooting_star_meme(file_path, f'{template}.mp4', 'audio.mp3', "intro.mp4", output_path)
        return jsonify({'message': 'File processed successfully', 'output_video': f'/outputs/{output_file}'}), 200
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/remove_files', methods=['GET'])
def remove_files():
    try:
        remove_old_files(app.config['UPLOAD_FOLDER'])
        remove_old_files(app.config['OUTPUT_FOLDER'])
        return jsonify({"status": "success", "message": "Old files removed successfully!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'],filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0')
