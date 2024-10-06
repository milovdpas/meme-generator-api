import cv2
import numpy as np
from moviepy.editor import *
import random
import array

def create_shooting_star_meme(image_path, template_video_path, music_path, intro_video_path, output_video_path):
    # Load the image and the meme template video
    image = ImageClip(image_path)
    template_video = VideoFileClip(template_video_path)

    # Get the dimensions of the video
    video_width, video_height = template_video.size
    image_width, image_height = image.size
    new_image_height = video_height/5
    image_width = int(image_width * (new_image_height / image_height))
    image_height = new_image_height

    # Define custom motion patterns
    def rotate_image(get_frame, t):
        frame = get_frame(t)
        rotation_matrix = cv2.getRotationMatrix2D(
            (frame.shape[1] // 2, frame.shape[0] // 2), 360 * t, 1
        )
        rotated_frame = cv2.warpAffine(frame, rotation_matrix, (frame.shape[1], frame.shape[0]))
        return rotated_frame

    # Straight Line (from any angle with correct starting position)
    def straight_line(angle, start_x, start_y):
        def motion(t):
            # Calculate displacement based on time and angle
            x_displacement = int(300 * t * np.cos(np.radians(angle)))
            y_displacement = int(300 * t * np.sin(np.radians(angle)))

            # Calculate the final position
            x = start_x + x_displacement
            y = start_y + y_displacement
            return x, y
        return motion

    # Curved Path (sinusoidal)
    def curved_path(t):
        return int(300 * t), int(300 + 100 * np.sin(2 * np.pi * t))

    def alreadyExists(old_values, new_value, range):
        for old_value in old_values:
            if abs(old_value-new_value) < range:
                return True
        return False

    # List of patterns with various angles
    angles = [0, 45, 90, 135, 180, 225, 270, 315]
    motion_patterns = []
    width_check = int(video_width-image_width)
    height_check = int(video_height-image_height)
    for angle in angles:
        old_x_values = []
        old_y_values = []
        for i in range(5):
            x = 0
            y = 0
            if angle == 0:
                y = random.randint(0, height_check)
                while alreadyExists(old_y_values, y, height_check/7):
                    y = random.randint(0, height_check)
                motion_patterns.append(straight_line(0, x, y))
            elif angle == 45:
                motion_patterns.append(straight_line(45, x, y))
            elif angle == 90:
                x = random.randint(0, width_check)
                while alreadyExists(old_x_values, x, width_check/10):
                    x = random.randint(0, width_check)
                motion_patterns.append(straight_line(90, x, y))
            elif angle == 135:
                y = height_check
                motion_patterns.append(straight_line(135, x, y))
            elif angle == 180:
                x = video_width
                y = random.randint(0, height_check)
                while alreadyExists(old_y_values, y, height_check/7):
                    y = random.randint(0, height_check)
                motion_patterns.append(straight_line(180, x, y))
            elif angle == 225:
                x = width_check
                y = height_check
                motion_patterns.append(straight_line(225, x, y))
            elif angle == 270:
                x = random.randint(0, width_check)
                while alreadyExists(old_x_values, x, width_check/10):
                    x = random.randint(0, width_check)
                y = height_check
                motion_patterns.append(straight_line(270, x, y))
            elif angle == 315:
                y = height_check
                motion_patterns.append(straight_line(315, x, y))
            old_x_values.append(x)
            old_y_values.append(y)


    # Create a series of image clips with different motion patterns
    image_clips = []
    num_repeats = int(template_video.duration // 5)  # Image flies in every 5 seconds

    for i in range(num_repeats):
        pattern_func = random.choice(motion_patterns)  # Choose a random motion pattern
        start_time = i * 5
        image_clip = (image
                      .resize(height=new_image_height)
                      .set_duration(5)  # Each image fly-in lasts 5 seconds
                      .set_start(start_time)
                      .set_position(pattern_func)
                      .fl(rotate_image)
                      .set_opacity(0.8))  # Adjust opacity if needed
        image_clips.append(image_clip)

    # Combine the template video and the image clips
    video = CompositeVideoClip([template_video] + image_clips)

    if intro_video_path:
        intro_video = VideoFileClip(intro_video_path)
        intro_video = intro_video.resize(height=video_height)
        video = concatenate_videoclips([intro_video, video])

    # Add music if provided
    if music_path:
        audio = AudioFileClip(music_path).subclip(0, video.duration)
        video = video.set_audio(audio)

    # Write the output video
    video.write_videofile(output_video_path, fps=template_video.fps)

# Example usage
# create_shooting_star_meme("image.png", "meme_template_2.mp4", "audio.mp3", "intro.mp4", "output.mp4")
