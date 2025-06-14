from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, subprocess, uuid, shutil
from datetime import datetime, timedelta
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from pydub import AudioSegment

app = Flask(__name__)
CORS(app)

app.config.update({
    'UPLOAD_FOLDER': os.getenv("UPLOAD_FOLDER", "downloads"),
    'OUTPUT_FOLDER': os.getenv("OUTPUT_FOLDER", "outputs"),
    'MAX_CONTENT_LENGTH': int(os.getenv("MAX_CONTENT_LENGTH", 5 * 1024 * 1024 * 1024)),
    'ALLOWED_EXTENSIONS': set(os.getenv("ALLOWED_EXTENSIONS", "mp3,wav,mp4,mkv,avi,flac").split(",")),
    'CLEANUP_AGE_HOURS': int(os.getenv("CLEANUP_AGE_HOURS", 24)),
})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("media-converter")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

def get_file_size(path):
    return os.path.getsize(path) / (1024 * 1024) if os.path.isfile(path) else 0

def cleanup_old_files():
    cutoff = datetime.now() - timedelta(hours=app.config['CLEANUP_AGE_HOURS'])
    for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
        for item in os.listdir(folder):
            path = os.path.join(folder, item)
            try:
                if os.path.getmtime(path) < cutoff.timestamp():
                    if os.path.isfile(path):
                        os.remove(path)
                    else:
                        shutil.rmtree(path)
                    logger.info(f"🧹 Supprimé : {path}")
            except Exception as e:
                logger.error(f"⚠️ Erreur suppression : {e}")

@app.route("/")
def home():
    return send_from_directory('.', 'index.html')

@app.route("/convert", methods=["POST"])
def convert():
    uid = str(uuid.uuid4())
    work_dir = os.path.join(app.config["UPLOAD_FOLDER"], uid)
    os.makedirs(work_dir, exist_ok=True)
    zip_path = os.path.join(app.config["OUTPUT_FOLDER"], f"{uid}.zip")

    try:
        output_format = request.form.get("format", "mp3").lower()
        use_spleeter = request.form.get("useSpleeter") == "on"
        url = request.form.get("url")

        if url:
            cmd = ['yt-dlp', '-o', os.path.join(work_dir, '%(title)s.%(ext)s'), '-f', 'bestaudio/best', '--no-playlist', '--quiet', url]
            if output_format != "mp4":
                cmd += ['--extract-audio', '--audio-format', output_format]
            subprocess.run(cmd, check=True, timeout=3600)
        else:
            files = request.files.getlist("files")
            if not files:
                return jsonify({"success": False, "error": "Aucun fichier ni URL"}), 400
            for file in files:
                if file and '.' in file.filename:
                    ext = file.filename.rsplit('.', 1)[-1].lower()
                    if ext in app.config["ALLOWED_EXTENSIONS"]:
                        file.save(os.path.join(work_dir, f"{uuid.uuid4().hex}_{file.filename}"))

        input_files = [os.path.join(work_dir, f) for f in os.listdir(work_dir) if os.path.isfile(os.path.join(work_dir, f))]
        if not input_files:
            return jsonify({"success": False, "error": "Aucun fichier valide à traiter."}), 400

        if use_spleeter:
            for file in input_files:
                subprocess.run(["spleeter", "separate", "-o", work_dir, file], check=True)
        elif not url:
            converted_dir = os.path.join(work_dir, 'converted')
            os.makedirs(converted_dir, exist_ok=True)
            for file in input_files:
                base = os.path.splitext(os.path.basename(file))[0]
                output_file = os.path.join(converted_dir, f"{base}.{output_format}")
                AudioSegment.from_file(file).export(output_file, format=output_format)
            work_dir = converted_dir

        shutil.make_archive(zip_path[:-4], 'zip', work_dir)
        return jsonify({"success": True, "zip_url": f"/download/{uid}.zip", "size_mb": round(get_file_size(zip_path), 2)})
    except subprocess.CalledProcessError:
        return jsonify({"success": False, "error": "Erreur traitement subprocess"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_old_files, 'interval', hours=1)
    scheduler.start()

if __name__ == "__main__":
    start_scheduler()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))