import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import yt_dlp
from flask import Flask, request, render_template, jsonify
import humanize
import logging
import math
import uuid # For generating API keys
from functools import wraps # For decorator

# --- Security & Validation Imports ---
from email_validator import validate_email, EmailNotValidError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# --- Database Imports ---
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Rate Limiter Configuration ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://", # Use "redis://localhost:6379" or other persistent storage in production
    strategy="fixed-window" # or "moving-window"
)

# --- Database Configuration ---
# Replace with your actual MySQL connection details
# Format: mysql+pymysql://username:password@host/database_name
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'mysql+pymysql://aticmatic_youtatic_db:k6kRgoSSRAKA@localhost/aticmatic_youtatic_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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

# --- Database Model ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False) # Added phone
    api_key = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    request_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<User {self.email}>'

# --- Helper Function to Get Formats (extracted logic) ---
def fetch_and_process_formats(media_url):
    """Fetches and processes formats for a given URL."""
    app.logger.info(f"Calling yt-dlp extract_info for: {media_url}")
    with yt_dlp.YoutubeDL(YDL_OPTS_INFO) as ydl:
        info_dict = ydl.extract_info(media_url, download=False)
    app.logger.info(f"Successfully extracted info for: {media_url}")

    formats_raw = info_dict.get('formats', [])
    title = info_dict.get('title', 'Untitled Media')
    app.logger.info(f"Found {len(formats_raw)} raw formats for '{title}'.")

    processed_formats = []
    for f in formats_raw:
        if f.get('url'):
            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            format_type = "Unknown"
            if vcodec != 'none' and acodec != 'none':
                format_type = "Video+Audio"
            elif vcodec != 'none':
                format_type = "Video Only"
            elif acodec != 'none':
                format_type = "Audio Only"

            resolution_str = f.get('resolution')
            if not resolution_str and f.get('height'):
                resolution_str = f"{f['height']}p"
            elif not resolution_str:
                 resolution_str = None

            filesize = f.get('filesize') or f.get('filesize_approx')

            processed_formats.append({
                'format_id': f.get('format_id'), # Renamed from 'id' for clarity
                'url': f.get('url'),
                'ext': f.get('ext'),
                'resolution': resolution_str,
                'height': f.get('height'),
                'width': f.get('width'), # Added width
                'filesize': filesize,
                'filesize_display': format_filesize(filesize),
                'fps': f.get('fps'), # Added fps
                'tbr': f.get('tbr'),
                'abr': f.get('abr'),
                'format_note': f.get('format_note'), # Renamed from 'note'
                'type': format_type,
                'vcodec': vcodec,
                'acodec': acodec,
            })

    app.logger.info(f"Processed {len(processed_formats)} formats with URLs.")

    processed_formats.sort(key=lambda x: (
        0 if x['type'] == 'Video+Audio' else 1 if x['type'] == 'Video Only' else 2,
        -(x.get('height') or 0),
        -(x.get('tbr') or 0.0)
    ))
    app.logger.info(f"Sorted formats for '{title}'.")

    return {
        'title': title,
        'original_url': media_url,
        'formats': processed_formats
    }

# --- Authentication Decorator ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            app.logger.warning("API request missing X-API-Key header.")
            return jsonify({"success": False, "error": "API key required"}), 401

        user = User.query.filter_by(api_key=api_key).first()
        if not user:
            app.logger.warning(f"API request with invalid key: {api_key[:5]}...")
            return jsonify({"success": False, "error": "Invalid API key"}), 401

        # Increment request count
        try:
            user.request_count += 1
            db.session.commit()
            app.logger.info(f"Authenticated API request for user {user.email} (Key: {api_key[:5]}...). Count: {user.request_count}")
        except Exception as db_err:
            db.session.rollback()
            app.logger.error(f"Failed to update request count for user {user.email}: {db_err}")
            # Decide if you want to fail the request or just log the error
            # return jsonify({"success": False, "error": "Database error during authentication"}), 500

        # Pass user object to the decorated function if needed (optional)
        # kwargs['user'] = user
        return f(*args, **kwargs)
    return decorated_function

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

# --- Add route for Developer Documentation ---
@app.route('/developer/doc')
def developer_doc():
    """Renders the API documentation page."""
    app.logger.info("Rendering developer documentation page.")
    # Ensure the doc file is in the 'templates/developer' subdirectory
    doc_path = os.path.join('developer', 'doc.html')
    if not os.path.exists(os.path.join(app.template_folder, doc_path)):
        app.logger.error(f"Developer documentation file not found at: {os.path.join(app.template_folder, doc_path)}")
        return "Documentation not found.", 404
    return render_template(doc_path)

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
        results_data = fetch_and_process_formats(media_url)
        response_data = {
            'success': True,
            'data': results_data
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

# --- New API Endpoint ---
@app.route('/api/v1/formats', methods=['GET'])
@require_api_key
def api_get_formats():
    """
    Handles GET requests to the authenticated API endpoint.
    Expects 'url' query parameter and 'X-API-Key' header.
    Returns JSON format data or error.
    """
    media_url = request.args.get('url', '').strip()

    if not media_url:
        app.logger.warning("API request missing 'url' query parameter.")
        return jsonify({'success': False, 'error': 'Missing required query parameter: url'}), 400

    app.logger.info(f"Processing API request for URL: {media_url}")

    try:
        results_data = fetch_and_process_formats(media_url)
        response_data = {
            'success': True,
            'data': results_data
        }
        return jsonify(response_data)

    except yt_dlp.utils.DownloadError as e:
        error_message = str(e)
        app.logger.error(f"API yt-dlp DownloadError for URL {media_url}: {error_message}", exc_info=False)
        user_error = 'Error fetching media details via API.'
        # Simplified error mapping for API
        if 'Unsupported URL' in error_message: user_error = 'Unsupported URL.'
        elif 'Private video' in error_message: user_error = 'Content is private or requires login.'
        elif 'Video unavailable' in error_message: user_error = 'Video unavailable.'
        elif 'urlopen error' in error_message: user_error = 'Network error resolving URL.'
        return jsonify({'success': False, 'error': user_error}), 500

    except Exception as e:
        app.logger.error(f"API Unexpected error processing URL {media_url}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'An unexpected server error occurred.'}), 500


# --- Basic Registration Route (for demonstration) ---
# Apply rate limiting: 5 requests per minute per IP address
@app.route('/register_api_user', methods=['POST'])
@limiter.limit("5 per minute")
def register_api_user():
    """(Demo) Creates a user and returns their API key. Includes validation and rate limiting."""
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip() # Strip whitespace

    # --- Input Validation ---
    if not email or not phone:
        app.logger.warning("Registration attempt with missing email or phone.")
        return jsonify({'success': False, 'error': 'Email and Phone are required.'}), 400

    # --- Email Validation ---
    allowed_domains = {'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com'}
    try:
        # Validate format and normalize
        email_info = validate_email(email, check_deliverability=False) # Deliverability check optional/can be slow
        email = email_info.normalized # Use the normalized version

        # Check domain
        domain = email.split('@')[1]
        if domain.lower() not in allowed_domains:
            app.logger.warning(f"Registration attempt with disallowed email domain: {domain}")
            return jsonify({'success': False, 'error': f'Only emails from {", ".join(sorted(allowed_domains))} are allowed.'}), 400

    except EmailNotValidError as e:
        # Email format is invalid
        app.logger.warning(f"Registration attempt with invalid email format: {email} - {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

    # --- Phone Validation (Basic Check - allows leading '+') ---
    # Add more robust validation if needed (e.g., using phonenumbers library)
    phone_to_check = phone
    if phone.startswith('+'):
        phone_to_check = phone[1:] # Check digits after the '+'

    if not phone_to_check.isdigit() or len(phone) < 8: # Adjusted min length slightly for '+' cases
         app.logger.warning(f"Registration attempt with potentially invalid phone: {phone}")
         # Decide whether to reject or just log. Rejecting for now.
         return jsonify({'success': False, 'error': 'Please provide a valid phone number (digits only, optional leading +).'}), 400

    # --- Check for Existing User ---
    if User.query.filter((User.email == email) | (User.phone == phone)).first():
         app.logger.warning(f"Registration attempt for existing email/phone: {email}/{phone}")
         return jsonify({'success': False, 'error': 'Email or Phone already registered.'}), 409 # Conflict

    # --- Create User ---
    try:
        # Note: No password hashing needed as we only store email/phone/key
        new_user = User(email=email, phone=phone) # API key generated by default
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"Registered new API user: {email}, Key: {new_user.api_key[:5]}...")
        # Return limited info upon success
        return jsonify({'success': True, 'message': 'Registration successful. Your API key is provided below.', 'api_key': new_user.api_key})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to register user {email}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to register user due to a server error.'}), 500


# --- Initialize Database ---
with app.app_context():
    try:
        db.create_all()
        app.logger.info("Database tables checked/created.")
    except Exception as e:
        app.logger.error(f"Failed to initialize database: {e}")


# --- Run the Application ---
if __name__ == '__main__':
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 't']

    app.logger.info(f"Starting Flask server on {host}:{port} (Debug: {debug_mode})")
    app.run(host=host, port=port, debug=debug_mode)
