import os
import yt_dlp
from flask import Flask, request, render_template, jsonify # Import jsonify
import humanize # Import humanize if you installed it
import logging # Import logging
import math # For rounding ABR

app = Flask(__name__)
app.secret_key = os.urandom(24) # Still useful if you add other features needing flash

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')

# --- Template Folder Setup ---
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
if not os.path.exists(template_dir):
    try:
        os.makedirs(template_dir)
        app.logger.info(f"Created templates directory at: {template_dir}")
    except OSError as e:
        app.logger.error(f"Failed to create templates directory: {e}")
app.template_folder = template_dir

# --- Jinja Filter Setup (Humanize for file sizes) ---
# Keep this as it's used by the filesizeformat function below
try:
    humanize_available = True
    app.logger.info("Humanize library found.")
except ImportError:
    humanize_available = False
    app.logger.warning("Humanize library not found. File sizes will be shown in bytes or as 'N/A'. Install with 'pip install humanize'.")

def format_filesize(size):
    """Helper function to format file size, using humanize if available."""
    if isinstance(size, (int, float)) and size is not None:
        if humanize_available:
            return humanize.naturalsize(size)
        else:
            return f"{size} B"
    return 'N/A'

# --- yt-dlp Options ---
YDL_OPTS_INFO = {
    'nocheckcertificate': True,
    'quiet': True,
    'extract_flat': 'in_playlist',
    'forcejson': True,
    'skip_download': True,
    'logger': app.logger,
    'noplaylist': True,
}

# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main page (index.html)."""
    app.logger.info("Rendering index page.")
    return render_template('index_new.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    """
    Handles the POST request from the index page form.
    Fetches available formats for the submitted URL using yt-dlp.
    Returns a JSON response with format data or an error message.
    """
    media_url = request.form.get('media_url', '').strip()

    if not media_url:
        app.logger.warning("Received empty URL submission.")
        # Return JSON error response
        return jsonify({'success': False, 'error': 'Please enter a valid media URL.'}), 400 # Bad Request

    app.logger.info(f"Processing request for URL: {media_url}")

    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_INFO) as ydl:
            app.logger.info(f"Calling yt-dlp extract_info for: {media_url}")
            info_dict = ydl.extract_info(media_url, download=False)
            app.logger.info(f"Successfully extracted info for: {media_url}")

        formats_raw = info_dict.get('formats', [])
        title = info_dict.get('title', 'Untitled Media')
        app.logger.info(f"Found {len(formats_raw)} raw formats for '{title}'.")

        # --- Filter, Process, and Sort Formats ---
        processed_formats = []
        for f in formats_raw:
            if f.get('url'): # Only include formats with a direct URL
                # Determine type
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                format_type = "Unknown"
                if vcodec != 'none' and acodec != 'none':
                    format_type = "Video+Audio"
                elif vcodec != 'none':
                    format_type = "Video Only"
                elif acodec != 'none':
                    format_type = "Audio Only"

                # Get resolution or height string
                resolution_str = f.get('resolution')
                if not resolution_str and f.get('height'):
                    resolution_str = f"{f['height']}p"
                elif not resolution_str:
                     resolution_str = None # Explicitly None if neither exists

                processed_formats.append({
                    'id': f.get('format_id'),
                    'url': f.get('url'),
                    'ext': f.get('ext'),
                    'resolution': resolution_str, # Use the combined string
                    'height': f.get('height'), # Keep raw height for sorting
                    'filesize': f.get('filesize') or f.get('filesize_approx'),
                    'filesize_display': format_filesize(f.get('filesize') or f.get('filesize_approx')),
                    'tbr': f.get('tbr'), # Total bitrate for sorting
                    'abr': f.get('abr'), # Audio bitrate for display
                    'note': f.get('format_note'),
                    'type': format_type,
                    'vcodec': vcodec,
                    'acodec': acodec,
                })

        app.logger.info(f"Processed {len(processed_formats)} formats with URLs.")

        # Sort formats: V+A (by height, tbr) > V (by height, tbr) > A (by tbr)
        processed_formats.sort(key=lambda x: (
            0 if x['type'] == 'Video+Audio' else 1 if x['type'] == 'Video Only' else 2, # Category order
            -(x.get('height') or 0),  # Height descending (negative for reverse)
            -(x.get('tbr') or 0.0)    # Bitrate descending (negative for reverse)
        ))

        app.logger.info(f"Sorted formats for '{title}'.")

        # --- Prepare JSON Response ---
        response_data = {
            'success': True,
            'data': {
                'title': title,
                'original_url': media_url,
                'formats': processed_formats
            }
        }
        return jsonify(response_data)

    except yt_dlp.utils.DownloadError as e:
        error_message = str(e)
        app.logger.error(f"yt-dlp DownloadError for URL {media_url}: {error_message}", exc_info=False)
        user_error = 'Error fetching media details. Please check the URL or try again.'
        if 'Unsupported URL' in error_message:
            user_error = 'The provided URL is not supported.'
        elif 'Private video' in error_message or 'Login required' in error_message:
             user_error = 'This content is private or requires login.'
        elif 'Video unavailable' in error_message:
             user_error = 'This video is unavailable.'
        elif 'urlopen error' in error_message:
             user_error = 'Network error: Could not resolve the URL.'
        # Return JSON error response
        return jsonify({'success': False, 'error': user_error}), 500 # Internal Server Error or appropriate code

    except Exception as e:
        app.logger.error(f"Unexpected error processing URL {media_url}: {e}", exc_info=True)
        # Return JSON error response
        return jsonify({'success': False, 'error': 'An unexpected server error occurred.'}), 500

# --- Run the Application ---
if __name__ == '__main__':
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 't']

    app.logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    app.run(host=host, port=port, debug=debug_mode)
