import cv2
import numpy as np
from moviepy.editor import *
import random
from concurrent.futures import ThreadPoolExecutor

def create_shooting_star_meme(image_path, template_video_path, music_path, intro_video_path, output_video_path):
    # Load the image and the meme template video
    image = ImageClip(image_path)
    template_video = VideoFileClip(template_video_path)

    # Get the dimensions of the video
    video_width, video_height = template_video.size
    new_image_height = video_height / 5
    image = image.resize(height=new_image_height)  # Resize once, reuse resized image
    image_width, image_height = image.size

    # Cache for rotating frames
    frames_cache = {}

    def rotate_image_cached(get_frame, t):
        if t not in frames_cache:
            frame = get_frame(t)
            rotation_matrix = cv2.getRotationMatrix2D(
                (frame.shape[1] // 2, frame.shape[0] // 2), 360 * t, 1
            )
            frames_cache[t] = cv2.warpAffine(frame, rotation_matrix, (frame.shape[1], frame.shape[0]))
        return frames_cache[t]

    # Define the motion pattern logic (with angles)
    def straight_line(angle, start_x, start_y):
        def motion(t):
            x_displacement = int(300 * t * np.cos(np.radians(angle)))
            y_displacement = int(300 * t * np.sin(np.radians(angle)))
            return start_x + x_displacement, start_y + y_displacement
        return motion

    def alreadyExists(old_values, new_value, threshold):
        return any(abs(old_value - new_value) < threshold for old_value in old_values)

    # Define motion patterns for each angle
    angles = [0, 45, 90, 135, 180, 225, 270, 315]
    motion_patterns = []
    width_check = video_width - image_width  # Ensure image stays within video bounds
    height_check = video_height - image_height

    for angle in angles:
        old_x_values = []
        old_y_values = []
        for _ in range(5):  # Generate 5 patterns for each angle
            x, y = 0, 0
            if angle == 0:
                y = random.randint(0, height_check)
                while alreadyExists(old_y_values, y, height_check/7):
                    y = random.randint(0, height_check)
            elif angle == 90:
                x = random.randint(0, width_check)
                while alreadyExists(old_x_values, x, width_check/10):
                    x = random.randint(0, width_check)
            elif angle == 135:
                x = width_check
            elif angle == 180:
                x = video_width
                y = random.randint(0, height_check)
                while alreadyExists(old_y_values, y, height_check/7):
                    y = random.randint(0, height_check)
            elif angle == 225:
                x = width_check
                y = height_check
            elif angle == 270:
                x = random.randint(0, width_check)
                while alreadyExists(old_x_values, x, width_check/10):
                    x = random.randint(0, width_check)
                y = height_check
            elif angle == 315:
                y = height_check

            motion_patterns.append(straight_line(angle, x, y))
            old_x_values.append(x)
            old_y_values.append(y)

    # Create a series of image clips with different motion patterns
    num_repeats = int(template_video.duration // 5)  # Image flies in every 5 seconds
    image_clips = []

    # Function for parallel processing of image clip creation
    def create_image_clip(i):
        pattern_func = random.choice(motion_patterns)
        start_time = i * 5
        return (image
                .set_duration(5)
                .set_start(start_time)
                .set_position(pattern_func)
                .fl(rotate_image_cached)  # Apply cached rotation function
                .set_opacity(0.8))

    # Parallelize clip creation
    with ThreadPoolExecutor() as executor:
        image_clips = list(executor.map(create_image_clip, range(num_repeats)))

    # Combine the template video and the image clips
    video = CompositeVideoClip([template_video] + image_clips)

    # Add intro video if provided
    if intro_video_path:
        intro_video = VideoFileClip(intro_video_path).resize(height=video_height)
        video = concatenate_videoclips([intro_video, video])

    # Add music if provided
    if music_path:
        audio = AudioFileClip(music_path).subclip(0, video.duration)
        video = video.set_audio(audio)

    # Write the output video
    video.write_videofile(output_video_path, fps=15)  # Reduced FPS for faster output

# Example usage
# create_shooting_star_meme("image.png", "meme_template_2.mp4", "audio.mp3", "intro.mp4", "output.mp4")
