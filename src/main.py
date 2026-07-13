import json
import os
import shutil
import logging
import subprocess
from google.cloud import storage, pubsub_v1


# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = "verse-dev-433901"
LOCATION = "us-east4"
SOURCE_BUCKET_NAME = "vodunprocessedgcp"
DESTINATION_BUCKET_NAME = "vodprocessedgcp"
PUBSUB_TOPIC_NAME = "verse-dev-433901-topic"


def transcoder_handler(environ, start_response):
    try:
        # Récupérer le corps de la requête
        content_length = int(environ.get('CONTENT_LENGTH', 0))
        body = environ['wsgi.input'].read(content_length)
        request_json = json.loads(body.decode('utf-8')) if body else {}

        # Vérifier si le corps de la requête contient les données nécessaires
        if not request_json or 'source_bucket' not in request_json or 'destination_bucket' not in request_json:
            response_body = json.dumps({
                "statusCode": 400, 
                "message": "Invalid input. JSON body with source_bucket and destination_bucket required."
            })
            status = '400 Bad Request'
            headers = [('Content-Type', 'application/json'), ('Content-Length', str(len(response_body)))]
            start_response(status, headers)
            return [response_body.encode('utf-8')]

        # Initialiser le client de stockage
        storage_client = storage.Client()

        # Extraire les informations du bucket source et destination
        source_bucket_name = request_json['source_bucket']
        destination_bucket_name = request_json['destination_bucket']
        bucket = storage_client.bucket(source_bucket_name)

        # Trouver la dernière vidéo .mp4 uploadée dans le bucket source
        blobs = [blob for blob in bucket.list_blobs() if blob.name.lower().endswith('.mp4')]
        if not blobs:
            response_body = json.dumps({
                "statusCode": 404,
                "message": "No .mp4 video found in the source bucket."
            })
            status = '404 Not Found'
            headers = [('Content-Type', 'application/json'), ('Content-Length', str(len(response_body)))]
            start_response(status, headers)
            return [response_body.encode('utf-8')]

        # Trier par date d'update (dernière upload)
        last_blob = max(blobs, key=lambda b: b.updated)
        source_blob_name = last_blob.name

        # Vérifier si le fichier existe (c'est déjà le cas)
        if not last_blob.exists():
            response_body = json.dumps({
                "statusCode": 404,
                "message": f"File '{source_blob_name}' not found in bucket '{source_bucket_name}'."
            })
            status = '404 Not Found'
            headers = [('Content-Type', 'application/json'), ('Content-Length', str(len(response_body)))]
            start_response(status, headers)
            return [response_body.encode('utf-8')]

        base_file_name, _ = os.path.splitext(os.path.basename(source_blob_name))
        logger.info(f"Processing latest uploaded file: gs://{source_bucket_name}/{source_blob_name}")

        # Logique de traitement de fichiers : copier le fichier, télécharger audio et sous-titres
        copy_original_file(storage_client, last_blob, base_file_name)
        download_audio_and_captions(base_file_name)

        # Générer les fichiers DASH
        dash_output_path = f"{base_file_name}/dash/"
        dash_output_dir = f"/tmp/{base_file_name}_dash"
        generate_dash_files(base_file_name, source_blob_name, dash_output_path, dash_output_dir)

        # Générer une vignette
        generate_thumbnail(base_file_name, source_blob_name)

        # Notification via Pub/Sub
        job_completed_notification(base_file_name)

        # Nettoyer les fichiers temporaires
        clear_tmp_files(base_file_name)

        # Préparer la réponse avec succès
        response_body = json.dumps({
            "statusCode": 200,
            "message": f"Transcoding and DASH packaging completed for {source_blob_name}.",
            "outputPath": dash_output_path,
        })
        status = '200 OK'
        headers = [('Content-Type', 'application/json'), ('Content-Length', str(len(response_body)))]
        start_response(status, headers)
        return [response_body.encode('utf-8')]

    except Exception as e:
        logger.error(f"Error during processing: {e}")
        response_body = json.dumps({
            "statusCode": 500,
            "message": "Internal server error.",
            "error": str(e)
        })
        status = '500 Internal Server Error'
        headers = [('Content-Type', 'application/json'), ('Content-Length', str(len(response_body)))]
        start_response(status, headers)
        return [response_body.encode('utf-8')]



def copy_original_file(storage_client, source_blob, base_file_name):
    """Copy the original video file to the destination bucket."""
    destination_bucket = storage_client.bucket(DESTINATION_BUCKET_NAME)
    new_blob_name = f"{base_file_name}/original/{source_blob.name}"
    copied_blob = source_blob.bucket.copy_blob(source_blob, destination_bucket, new_blob_name)
    logger.info(f"Original file copied to {copied_blob.name} in destination bucket.")


def detect_available_languages(base_file_name):
    """Detect all available languages (audio + captions) dynamically and save them."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(DESTINATION_BUCKET_NAME)
    audio_langs, caption_langs = set(), set()

    # Parcourir les audios disponibles
    for blob in bucket.list_blobs(prefix=f"{base_file_name}/audio/"):
        filename = os.path.basename(blob.name)
        if "_" in filename and "." in filename:
            lang = filename.split("_")[-1].split(".")[0]
            audio_langs.add(lang)

    # Parcourir les sous-titres disponibles
    for blob in bucket.list_blobs(prefix=f"{base_file_name}/caption/"):
        filename = os.path.basename(blob.name)
        if "_" in filename and "." in filename:
            lang = filename.split("_")[-1].split(".")[0]
            caption_langs.add(lang)

    langs_data = {"audio": sorted(audio_langs), "caption": sorted(caption_langs)}

    # Sauvegarde locale
    local_json_path = f"/tmp/{base_file_name}_langs.json"
    with open(local_json_path, "w", encoding="utf-8") as f:
        json.dump(langs_data, f, indent=2, ensure_ascii=False)
    logger.info(f"💾 Saved detected languages locally at: {local_json_path}")

    # Upload dans le bucket
    upload_blob(DESTINATION_BUCKET_NAME, local_json_path, f"{base_file_name}/metadata/langs.json")
    logger.info(f"☁️ Uploaded langs.json to: {DESTINATION_BUCKET_NAME}/{base_file_name}/metadata/langs.json")

    logger.info(f"🔊 Audio languages detected: {langs_data['audio']}")
    logger.info(f"💬 Caption languages detected: {langs_data['caption']}")
    return langs_data['audio'], langs_data['caption']


def download_audio_and_captions(base_file_name):
    """Download audio and caption files from GCP bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(DESTINATION_BUCKET_NAME)
    audio_langs, caption_langs = detect_available_languages(base_file_name)

    # Download audio files
    for lang in audio_langs:
        audio_blob_name = f"{base_file_name}/audio/{base_file_name}_{lang}.wav"
        local_audio_path = f"/tmp/{base_file_name}_{lang}.wav"
        if blob_exists(bucket, audio_blob_name):
            download_blob(DESTINATION_BUCKET_NAME, audio_blob_name, local_audio_path)
            logger.info(f"Downloaded audio file: {audio_blob_name}")
        else:
            logger.warning(f"Audio file not found: {audio_blob_name}")

    # Download caption files
    for lang in caption_langs:
        caption_blob_name = f"{base_file_name}/caption/{base_file_name}_{lang}.vtt"
        local_caption_path = f"/tmp/{base_file_name}_{lang}.vtt"
        if blob_exists(bucket, caption_blob_name):
            download_blob(DESTINATION_BUCKET_NAME, caption_blob_name, local_caption_path)
            logger.info(f"Downloaded caption file: {caption_blob_name}")
        else:
            logger.warning(f"Caption file not found: {caption_blob_name}")



def blob_exists(bucket, blob_name):
    """Check if a blob exists in the bucket."""
    blob = bucket.blob(blob_name)
    return blob.exists()



def generate_dash_files(base_file_name, source_blob_name, output_path, output_dir):
    """Transcodes video to SD, HD, UHD, adds subtitles and generates DASH manifest."""
    
    local_video_path = f"/tmp/{source_blob_name}"
    os.makedirs(output_dir, exist_ok=True)
    
    logging.info(f"Creating the output folder: {output_dir}")

    try:
        logging.info(f"Downloading video from GCP: {source_blob_name} -> {local_video_path}")
        download_blob(SOURCE_BUCKET_NAME, source_blob_name, local_video_path)
    except Exception as e:
        logging.error(f"Error downloading video file: {e}")
        return
    
    # Checking the existence of the downloaded file
    if not os.path.exists(local_video_path):
        logging.error(f"The source file {local_video_path} could not be found after downloading.")
        return
    else:
        logging.info(f"Source file downloaded successfully: {local_video_path}")

    dash_sd = f"{output_dir}/{base_file_name}_sd.mp4"
    dash_hd = f"{output_dir}/{base_file_name}_hd.mp4"
    dash_uhd = f"{output_dir}/{base_file_name}_uhd.mp4"

    audio_langs, caption_langs = detect_available_languages(base_file_name)
    audio_inputs = []

    for lang in audio_langs:
        audio_file = f"/tmp/{base_file_name}_{lang}.wav"
        if os.path.exists(audio_file):
            # 1. Encoder WAV → AAC
            dash_aac = f"/tmp/{base_file_name}_audio_{lang}.aac"
            ffmpeg_audio_command = [
                "ffmpeg",
                "-y",  # Overwrite output if exists
                "-i", audio_file,
                "-acodec", "aac",
                "-b:a", "128k",
                "-ar", "48000",
                "-vn",
                dash_aac
            ]
            logging.info(f"Encoding audio WAV to AAC: {' '.join(ffmpeg_audio_command)}")
            try:
                subprocess.run(ffmpeg_audio_command, check=True)
            except subprocess.CalledProcessError as e:
                logging.error(f"Error while encoding audio: {e}")
                return

            # 2. Muxer AAC → MP4 avec MP4Box et taguer la langue
            dash_audio = f"{output_dir}/{base_file_name}_audio_{lang}.mp4"
            mp4box_audio_command = [
                "MP4Box",
                "-add", f"{dash_aac}:lang={lang}",
                "-new", dash_audio
            ]
            logging.info(f"Muxing AAC to MP4 with MP4Box: {' '.join(mp4box_audio_command)}")
            try:
                subprocess.run(mp4box_audio_command, check=True)
                audio_inputs.append(dash_audio)
            except subprocess.CalledProcessError as e:
                logging.error(f"Error while muxing audio to MP4: {e}")
                return

    ffmpeg_command = [
        "ffmpeg", "-y", "-i", local_video_path,
        "-filter_complex",
        "[0:v]split=3[vsd][vhd][vuhd];"
        "[vsd]scale=854:480[voutsd];"
        "[vhd]scale=1280:720[vouthd];"
        "[vuhd]scale=1920:1080[voutuhd]",

        # SD Output
        "-map", "[voutsd]",
        "-b:v:0", "2M", "-c:v:0", "libx264", "-g", "120", "-keyint_min", "120",
        "-preset", "fast", "-profile:v:0", "main", "-an", "-f", "mp4", dash_sd,

        # HD Output
        "-map", "[vouthd]",
        "-b:v:1", "6M", "-c:v:1", "libx264", "-g", "120", "-keyint_min", "120",
        "-preset", "fast", "-profile:v:1", "main", "-an", "-f", "mp4", dash_hd,

        # UHD Output
        "-map", "[voutuhd]",
        "-b:v:2", "10M", "-c:v:2", "libx264", "-g", "120", "-keyint_min", "120",
        "-preset", "fast", "-profile:v:2", "high", "-an", "-f", "mp4", dash_uhd
    ]

    logging.info(f"Running the FFmpeg command for transcoding: {' '.join(ffmpeg_command)}")

    try:
        subprocess.run(ffmpeg_command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error while transcoding with FFmpeg: {e}")
        return

    # Checking created files
    for file in [dash_sd, dash_hd, dash_uhd]:
        if not os.path.exists(file):
            logging.error(f"The expected file {file} was not generated.")
            return
        else:
            logging.info(f"File generated successfully: {file}")

    subtitle_files = []
    for lang in caption_langs:
        vtt_file = f"/tmp/{base_file_name}_{lang}.vtt"
        if os.path.exists(vtt_file):
            subtitle_mp4 = f"{output_dir}/{base_file_name}_{lang}.mp4"
            mp4box_command = ["MP4Box", "-add", f"{vtt_file}:hdlr=sbtl:lang={lang}", "-new", subtitle_mp4]
            logging.info(f"Converting subtitles with MP4Box: {' '.join(mp4box_command)}")
            try:
                subprocess.run(mp4box_command, check=True)
                subtitle_files.append(subtitle_mp4)
            except subprocess.CalledProcessError as e:
                logging.error(f"Error converting subtitles: {e}")
                return

    dash_manifest_path = f"{output_dir}/manifest.mpd"
    
    mp4box_dash_command = [
        "MP4Box",
        "-dash", "2000",         # Segment every 2000 ms
        "-frag", "2000",         # 2000 ms fragments
        "-rap",                  # GOP Activation Points
        "-bs-switching", "no",   # No flow switching
        "-single-traf",
        "-url-template",         # URL template for segments
        "-segment-name", "segment-$RepresentationID$-$Number$", # Segment names
        "-out", dash_manifest_path
    ]

    # Adding video files (SD, HD, UHD streams) 
    mp4box_dash_command.extend([dash_sd, dash_hd, dash_uhd])
    mp4box_dash_command.extend(audio_inputs)        # fichiers audio, un par langue
    mp4box_dash_command.extend(subtitle_files)      # fichiers sous-titres, un par langue

    logging.info(f"Running the MP4Box command to generate the DASH manifest: {' '.join(mp4box_dash_command)}")

    try:
        subprocess.run(mp4box_dash_command, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error generating DASH manifest: {e}")
        return

    if os.path.exists(dash_manifest_path):
        logging.info(f"DASH manifest successfully generated: {dash_manifest_path}")
    else:
        logging.error(f"The DASH manifest {dash_manifest_path} has not been created.")

    try:
        logging.info(f"Uploading DASH files to GCP: {output_dir} -> {DESTINATION_BUCKET_NAME}/{output_path}")
        upload_directory(output_dir, DESTINATION_BUCKET_NAME, output_path)
    except Exception as e:
        logging.error(f"Error uploading DASH files to GCP: {e}")


def generate_thumbnail(base_file_name, source_blob_name):
    """Generate a thumbnail for the video."""
    local_video_path = f"/tmp/{source_blob_name}"
    local_thumbnail_path = f"/tmp/{base_file_name}.jpg"

    # FFmpeg command to generate the thumbnail
    ffmpeg_command = [
        "ffmpeg",
        "-loglevel", "error",
        "-y",
        "-i", local_video_path,
        "-ss", "00:00:10",
        "-vframes", "1",
        "-q:v", "2",
        local_thumbnail_path,
    ]
    subprocess.run(ffmpeg_command, check=True)
    logger.info(f"Thumbnail generated at: {local_thumbnail_path}")

    # Upload thumbnail to the destination bucket
    upload_blob(DESTINATION_BUCKET_NAME, local_thumbnail_path, f"{base_file_name}/thumbnail/{base_file_name}.jpg")


def job_completed_notification(file_name):
    """Send a Pub/Sub notification about job completion."""
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, PUBSUB_TOPIC_NAME)
    message = json.dumps({"message": f"Processing completed for {file_name}"}).encode("utf-8")
    publisher.publish(topic_path, message)
    logger.info(f"Notification sent to Pub/Sub: {message}")


def download_blob(bucket_name, source_blob_name, destination_file_name):
    """Download a blob from a bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(source_blob_name)
    blob.download_to_filename(destination_file_name)
    logger.info(f"Downloaded {source_blob_name} to {destination_file_name}.")


def upload_blob(bucket_name, source_file_name, destination_blob_name):
    """Upload a file to a bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    logger.info(f"Uploaded {source_file_name} to {destination_blob_name} in {bucket_name}.")


def upload_directory(local_directory, bucket_name, destination_prefix):
    """Upload a directory to a bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    for root, _, files in os.walk(local_directory):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, local_directory)
            destination_blob_name = os.path.join(destination_prefix, relative_path)
            upload_blob(bucket_name, local_path, destination_blob_name)


def clear_tmp_files(base_file_name):
    """Clear temporary files."""
    tmp_paths = [
        f"/tmp/{base_file_name}_dash",
        f"/tmp/{base_file_name}_txt",
        f"/tmp/{base_file_name}.jpg",
    ]
    for tmp_path in tmp_paths:
        if os.path.exists(tmp_path):
            if os.path.isdir(tmp_path):
                for root, _, files in os.walk(tmp_path):
                    for file in files:
                        os.remove(os.path.join(root, file))
                os.rmdir(tmp_path)
            else:
                os.remove(tmp_path)
            logger.info(f"Removed: {tmp_path}")

#if __name__ == "__main__":
    #app.run(host="0.0.0.0", port=8080)
