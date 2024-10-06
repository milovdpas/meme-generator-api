import os
import time

# Time in seconds (5 minutes = 5 * 60)
TIME_THRESHOLD = 5 * 60

def remove_old_files(folder):
    current_time = time.time()

    # List all files in the uploads directory
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)

        # Check if it's a file and not a directory
        if os.path.isfile(file_path):
            # Get the last modification time of the file
            file_mod_time = os.path.getmtime(file_path)

            # If file is older than 5 minutes, delete it
            if current_time - file_mod_time > TIME_THRESHOLD:
                os.remove(file_path)
                print(f"Deleted {file_path}")
