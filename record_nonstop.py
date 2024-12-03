import os
import threading
from time import sleep, time
from datetime import datetime
import logging
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import Output
from libcamera import controls
import subprocess

#-------------------------------------------------------------------------------------------------------
# Variables - update as needed
this_pi = 'raspi0'  # Identifier for the recording
brightness = 50
contrast = 50
chunk_length = 3600  # Record in chunks (seconds). E.g., 3600 secs = 1 hour
rclone_config = 'lowell_lab:Recordings/'
video_save_path = '/home/nadia/Videos/'
log_save_path = '/home/nadia/Documents/Logs/'
#-------------------------------------------------------------------------------------------------------

def ensure_directory_exists(path):
    """Ensures that a directory exists."""
    if not os.path.exists(path):
        os.makedirs(path)

def get_timestamp():
    """Returns the current timestamp formatted for filenames."""
    return datetime.now().strftime('%d_%m_%Y__%H_%M_%S')

def convert_and_upload(h264_file, mp4_file):
    """Converts the H264 file to MP4 and uploads it."""
    try:
        # Convert to MP4
        command = f"ffmpeg -y -i {h264_file} -r 10 -c:v copy {mp4_file}"
        subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
        logging.info(f"Conversion to MP4 successful: {mp4_file}")

        # Upload to cloud
        upload_command = f"rclone copy {mp4_file} {rclone_config} --contimeout=40m"
        os.system(upload_command)
        logging.info(f"Upload successful: {mp4_file}")

        # Remove original H264 file
        os.remove(h264_file)
        logging.info(f"Original H264 file removed: {h264_file}")

    except subprocess.CalledProcessError as e:
        logging.exception(f"Conversion/upload failed: {e.output}")
    except Exception as e:
        logging.exception(f"Error during conversion/upload: {str(e)}")

class ContinuousRecording:
    def __init__(self, camera, encoder, output, chunk_length):
        self.camera = camera
        self.encoder = encoder
        self.output = output
        self.chunk_length = chunk_length
        self.start_time = time()
        self.lock = threading.Lock()
        self.recording = True

    def start(self):
        threading.Thread(target=self._monitor).start()

    def _monitor(self):
        while self.recording:
            sleep(self.chunk_length)
            with self.lock:
                self._split_recording()

    def _split_recording(self):
        # Generate new file names
        timestamp = get_timestamp()
        name = f"{this_pi}_{timestamp}"
        h264_file = os.path.join(video_save_path, f"{name}.h264")
        mp4_file = os.path.join(video_save_path, f"{name}.mp4")

        # Switch the output file
        logging.info(f"Switching recording to new file: {h264_file}")
        new_output = FileOutput(h264_file)
        self.encoder.output = new_output

        # Start conversion and upload in a separate thread
        threading.Thread(target=convert_and_upload, args=(self.output.filepath, self._get_mp4_filename(self.output.filepath))).start()

        # Update the current output
        self.output = new_output

    def stop(self):
        self.recording = False

    def _get_mp4_filename(self, h264_filename):
        """Generates the MP4 filename from the H264 filename."""
        return h264_filename.replace('.h264', '.mp4')

class FileOutput(Output):
    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath
        self.file = open(self.filepath, 'wb')

    def outputframe(self, frame, keyframe=True):
        self.file.write(frame)

    def close(self):
        self.file.close()

def main():
    # Initialize logging
    ensure_directory_exists(log_save_path)
    log_file = os.path.join(log_save_path, f"{this_pi}_{datetime.now().strftime('%d_%m_%Y__%H_%M')}.log")
    logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s:%(levelname)s:%(message)s')

    # Initialize Picamera2
    camera = Picamera2(0)
    video_config = camera.create_video_configuration(main={"size": (1920, 1080), "format": "H264"})
    camera.configure(video_config)
    camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
    camera.set_controls({"FrameDurationLimits": (100000, 100000)})

    ensure_directory_exists(video_save_path)

    try:
        camera.start_preview()
        logging.info("Camera preview started.")

        # Generate initial file names
        timestamp = get_timestamp()
        name = f"{this_pi}_{timestamp}"
        h264_file = os.path.join(video_save_path, f"{name}.h264")
        mp4_file = os.path.join(video_save_path, f"{name}.mp4")

        # Create initial output
        output = FileOutput(h264_file)
        encoder = H264Encoder(bitrate=1000000)
        encoder.output = output

        # Start recording
        camera.start_recording(encoder)
        logging.info(f"Recording started: {h264_file}")

        # Start continuous recording handler
        continuous_recorder = ContinuousRecording(camera, encoder, output, chunk_length)
        continuous_recorder.start()

        # Keep the main thread alive
        while True:
            sleep(1)

    except Exception as e:
        logging.exception(f"Recording error: {str(e)}")
    finally:
        continuous_recorder.stop()
        camera.stop_recording()
        camera.stop_preview()
        logging.info("Camera recording and preview stopped.")

if __name__ == "__main__":
    main()
