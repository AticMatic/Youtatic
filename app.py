# app.py
import os
import yt_dlp
from flask import Flask, request, render_template, redirect, url_for, flash
import humanize # Import humanize if you installed it
import logging # Import logging

app = Flask(__name__)
app.secret_key = os.urandom(24) # Needed for flashing messages

# --- Logging Setup ---
# Configure logging for better debugging, especially in production
logging.basicConfig(level=logging.INFO, # Set to DEBUG for more detail
                    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')

# --- Template Folder Setup ---
# Ensure the templates directory exists relative to the script
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
if not os.path.exists(template_dir):
    try:
        os.makedirs(template_dir)
        app.logger.info(f"Created templates directory at: {template_dir}")
    except OSError as e:
        app.logger.error(f"Failed to create templates directory: {e}")
        # Depending on your setup, you might want to exit or handle this differently
app.template_folder = template_dir # Set the template folder

# --- Jinja Filter Setup (Humanize for file sizes) ---
try:
    # Register humanize filter for readable file sizes (e.g., "1.2 MB")
    app.jinja_env.filters['filesizeformat'] = humanize.naturalsize
    app.logger.info("Registered 'humanize.naturalsize' as 'filesizeformat' filter.")
except NameError:
    # Fallback if humanize is not installed (pip install humanize)
    # This simple fallback just returns the number as string or 'N/A'
    app.jinja_env.filters['filesizeformat'] = lambda size: f"{size} B" if isinstance(size, (int, float)) and size is not None else 'N/A'
    app.logger.warning("Humanize library not found. File sizes will be shown in bytes or as 'N/A'. Install with 'pip install humanize'.")


# --- yt-dlp Options ---
# Options specifically for fetching metadata (faster, less resource-intensive)
YDL_OPTS_INFO = {
    'nocheckcertificate': True, # Ignore SSL certificate errors (use cautiously)
    'quiet': True,              # Suppress yt-dlp console output during info extraction
    'extract_flat': 'in_playlist', # Can speed up playlist info fetching (might miss some details)
    'forcejson': True,          # Ensure yt-dlp output is JSON
    'skip_download': True,      # Crucial: Only fetch info, don't download media files
    'logger': app.logger,       # Integrate yt-dlp logging with Flask's logger
    'noplaylist': True,         # Process only single video if URL is video and playlist
    # 'verbose': True, # Uncomment for very detailed yt-dlp logs
}

# --- Flask Routes ---

@app.route('/')
def index():
    """
    Renders the main page (index.html) which contains the form
    for submitting a media URL.
    """
    app.logger.info("Rendering index page.")
    return render_template('index.html')

@app.route('/get_formats', methods=['POST'])
def get_formats():
    """
    Handles the POST request from the index page form.
    Fetches available formats for the submitted URL using yt-dlp.
    Renders the formats.html page to display download options or redirects
    back to index with an error message.
    """
    media_url = request.form.get('media_url', '').strip() # Get URL and remove whitespace

    if not media_url:
        flash('Please enter a valid media URL.', 'error')
        app.logger.warning("Received empty URL submission.")
        return redirect(url_for('index'))

    app.logger.info(f"Processing request for URL: {media_url}")

    try:
        # Use yt-dlp to extract information about the media
        with yt_dlp.YoutubeDL(YDL_OPTS_INFO) as ydl:
            app.logger.info(f"Calling yt-dlp extract_info for: {media_url}")
            # Use `extract_info` which fetches detailed format data needed for links
            info_dict = ydl.extract_info(media_url, download=False) # download=False is redundant due to skip_download, but good practice
            app.logger.info(f"Successfully extracted info for: {media_url}")

        # --- Process Extracted Information ---
        formats = info_dict.get('formats', [])
        title = info_dict.get('title', 'Untitled Media')
        app.logger.info(f"Found {len(formats)} formats for '{title}'.")

        # --- Filter and Sort Formats ---
        # 1. Filter out formats that don't have a direct URL (essential for linking)
        usable_formats_all = [f for f in formats if f.get('url')]
        app.logger.info(f"Filtered down to {len(usable_formats_all)} formats with direct URLs.")

        # 2. Categorize formats for better sorting and display
        video_audio = [f for f in usable_formats_all if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
        video_only = [f for f in usable_formats_all if f.get('vcodec') != 'none' and f.get('acodec') == 'none']
        audio_only = [f for f in usable_formats_all if f.get('vcodec') == 'none' and f.get('acodec') != 'none']

        # 3. Sort each category (prioritize quality: resolution/height, then bitrate)
        #    Handle potential None values by treating them as 0 for sorting purposes.
        #    Higher values first (reverse=True)
        video_audio.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0.0), reverse=True)
        video_only.sort(key=lambda x: (x.get('height') or 0, x.get('tbr') or 0.0), reverse=True)
        audio_only.sort(key=lambda x: (x.get('tbr') or 0.0), reverse=True) # Audio sorted by bitrate

        # 4. Combine sorted lists in preferred order (Video+Audio > Video > Audio)
        usable_formats_sorted = video_audio + video_only + audio_only
        app.logger.info(f"Sorted formats: {len(video_audio)} V+A, {len(video_only)} V-only, {len(audio_only)} A-only.")

        if not usable_formats_sorted:
             flash('Could not find any downloadable formats with direct URLs for this media.', 'warning')
             app.logger.warning(f"No usable formats with direct URLs found for: {media_url}")
             return redirect(url_for('index'))

        # --- Render Formats Page ---
        app.logger.info(f"Rendering formats page for '{title}'.")
        return render_template('formats.html',
                               formats=usable_formats_sorted,
                               title=title,
                               original_url=media_url)

    except yt_dlp.utils.DownloadError as e:
        # Handle specific errors reported by yt-dlp
        error_message = str(e)
        app.logger.error(f"yt-dlp DownloadError for URL {media_url}: {error_message}", exc_info=False) # Log full yt-dlp error

        # Provide user-friendly messages for common errors
        if 'Unsupported URL' in error_message:
            flash('The provided URL is not supported by yt-dlp.', 'error')
        elif 'Private video' in error_message or 'Login required' in error_message:
             flash('This content is private or requires login.', 'error')
        elif 'Video unavailable' in error_message:
             flash('This video is unavailable.', 'error')
        elif 'urlopen error [Errno -2] Name or service not known' in error_message or 'urlopen error [Errno -3]' in error_message:
             flash('Could not resolve the URL. Check the address or your network connection.', 'error')
        else:
            # Generic yt-dlp error for less common cases
            flash(f'Error fetching media details. Please check the URL or try again.', 'error')
        return redirect(url_for('index'))

    except Exception as e:
        # Handle other unexpected errors (network issues, programming errors, etc.)
        # Log the full traceback for unexpected errors
        app.logger.error(f"Unexpected error processing URL {media_url}: {e}", exc_info=True)
        flash('An unexpected server error occurred. Please try again later.', 'error')
        return redirect(url_for('index'))

# --- Run the Application ---
if __name__ == '__main__':
    # Get host and port from environment variables or use defaults
    # Useful for containerized deployments (like Docker)
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1') # Default to localhost
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))  # Default to 5000
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 't'] # Default to True for dev

    app.logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    # Run the Flask development server
    # Set debug=False in a production environment for security and performance
    app.run(host=host, port=port, debug=debug_mode)
