import os
import sys
# Ensure the current directory is in the path for relative imports if needed
sys.path.insert(0, os.path.dirname(__file__))

import yt_dlp
from flask import Flask, request, render_template, jsonify
import humanize # For filesize formatting
import logging # For logging events and errors
import math # Potentially useful for calculations (though not used currently)
import uuid # For generating API keys
from functools import wraps # For creating decorators (like require_api_key)

# --- Security & Validation Imports ---
from email_validator import validate_email, EmailNotValidError # For validating email formats
from flask_limiter import Limiter # For rate limiting requests
from flask_limiter.util import get_remote_address # To get client IP for rate limiting

# --- Database Imports ---
from flask_sqlalchemy import SQLAlchemy # ORM for database interaction

app = Flask(__name__)
# Secret key is needed for session management, flash messages (even if not used extensively), etc.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24)) # Use environment variable or random bytes

# --- Rate Limiter Configuration ---
limiter = Limiter(
    get_remote_address, # Identify clients by remote IP address
    app=app,
    default_limits=["200 per day", "50 per hour"], # Default limits for all routes unless overridden
    storage_uri="memory://", # Use in-memory storage (suitable for single-process dev/testing)
                             # In production, use persistent storage like Redis: "redis://localhost:6379"
    strategy="fixed-window" # Strategy for rate limiting ("fixed-window", "moving-window")
)

# --- Database Configuration ---
# Get DB URL from environment variable or use a default (replace with your actual credentials)
# Format: dialect+driver://username:password@host:port/database
default_db_uri = 'mysql+pymysql://aticmatic_youtatic_db:k6kRgoSSRAKA@localhost/aticmatic_youtatic_db'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', default_db_uri)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable modification tracking (saves resources)
db = SQLAlchemy(app)

# --- Logging Setup ---
# Configure logging level and format
logging.basicConfig(level=logging.INFO, # Change to DEBUG for more verbose output
                    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')

# --- Template Folder Setup ---
# Define the path to the templates directory relative to this file
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
# Create the directory if it doesn't exist
if not os.path.exists(template_dir):
    try:
        os.makedirs(template_dir)
        app.logger.info(f"Created templates directory at: {template_dir}")
    except OSError as e:
        app.logger.error(f"Failed to create templates directory: {e}")
# Set the template folder for Flask
app.template_folder = template_dir

# --- Jinja Filter Setup (Humanize for file sizes) ---
# Check if humanize library is available and set up a helper function
try:
    import humanize # Try importing
    humanize_available = True
    app.logger.info("Humanize library found.")
except ImportError:
    humanize_available = False
    app.logger.warning("Humanize library not found. File sizes will be shown in bytes or as 'N/A'. Install with 'pip install humanize'.")

def format_filesize(size):
    """Helper function to format file size, using humanize if available."""
    if isinstance(size, (int, float)) and size is not None:
        if humanize_available:
            # Use humanize for readable format (e.g., "1.2 MiB")
            return humanize.naturalsize(size, binary=True) # binary=True uses MiB, KiB etc.
        else:
            # Fallback to showing bytes
            return f"{size} B"
    return 'N/A' # Return 'N/A' if size is None or not a number

# --- Database Model ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False) # Added phone field
    # Generate a unique API key (UUID4) for each new user by default
    api_key = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    # Track the number of requests made by the user
    request_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        # String representation for debugging purposes
        return f'<User {self.email}>'

# --- Helper Function to Get Formats (extracted logic) ---
def fetch_and_process_formats(media_url):
    """
    Fetches media information using yt-dlp, processes format details,
    and sorts them. Returns a dictionary with title, original_url, and formats.
    Raises yt_dlp.utils.DownloadError or other exceptions on failure.
    """
    # Define yt-dlp options
    # These options prioritize fetching info quickly without downloading
    # Added User-Agent and Referer headers
    YDL_OPTS_INFO = {
        'nocheckcertificate': True, # Ignore SSL errors (use with caution)
        'quiet': True,              # Suppress yt-dlp console output
        'extract_flat': 'in_playlist', # Faster for playlists, gets basic info
        'forcejson': True,          # Ensure output is JSON
        'skip_download': True,      # Don't download media files
        'logger': app.logger,       # Use Flask's logger for yt-dlp messages
        'noplaylist': True,         # Process only single video if URL is both video and playlist
        # --- Attempt to look less like a bot ---
        'http_headers': {
             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36', # Example Chrome UA
             'Referer': 'https://www.google.com/', # Example Referer
             'Accept-Language': 'en-US,en;q=0.9', # Example language header
        },
        # ----------------------------------------
        # 'verbose': True, # Uncomment for very detailed yt-dlp logs
    }

    app.logger.info(f"Calling yt-dlp extract_info for: {media_url}")
    # Use a context manager to ensure yt-dlp resources are cleaned up
    with yt_dlp.YoutubeDL(YDL_OPTS_INFO) as ydl:
        # Extract information, this might raise DownloadError
        info_dict = ydl.extract_info(media_url, download=False)
    app.logger.info(f"Successfully extracted info for: {media_url}")

    # Get raw formats list and title from the extracted info
    formats_raw = info_dict.get('formats', [])
    title = info_dict.get('title', 'Untitled Media')
    app.logger.info(f"Found {len(formats_raw)} raw formats for '{title}'.")

    # Process each format to extract relevant details
    processed_formats = []
    for f in formats_raw:
        # Only include formats that have a direct download URL
        if f.get('url'):
            vcodec = f.get('vcodec', 'none') # Video codec (or 'none')
            acodec = f.get('acodec', 'none') # Audio codec (or 'none')

            # Determine the type of format based on codecs
            format_type = "Unknown"
            if vcodec != 'none' and acodec != 'none':
                format_type = "Video+Audio"
            elif vcodec != 'none':
                format_type = "Video Only"
            elif acodec != 'none':
                format_type = "Audio Only"

            # Get resolution string (e.g., "1920x1080") or create from height (e.g., "1080p")
            resolution_str = f.get('resolution')
            if not resolution_str and f.get('height'):
                resolution_str = f"{f['height']}p"
            # resolution_str remains None if neither is available

            # Get filesize (preferring approximate if exact is missing)
            filesize = f.get('filesize') or f.get('filesize_approx')

            # Append processed format data to the list
            processed_formats.append({
                'format_id': f.get('format_id'), # Unique ID for the format
                'url': f.get('url'),             # Direct download URL
                'ext': f.get('ext'),             # File extension (e.g., 'mp4')
                'resolution': resolution_str,    # Formatted resolution string
                'height': f.get('height'),       # Video height in pixels
                'width': f.get('width'),         # Video width in pixels
                'filesize': filesize,            # Filesize in bytes (or None)
                'filesize_display': format_filesize(filesize), # Human-readable filesize
                'fps': f.get('fps'),             # Frames per second (or None)
                'tbr': f.get('tbr'),             # Total bitrate (video+audio, kbps, or None)
                'abr': f.get('abr'),             # Audio bitrate (kbps, or None)
                'format_note': f.get('format_note'), # Additional note (e.g., 'medium')
                'type': format_type,             # Calculated type (Video+Audio, etc.)
                'vcodec': vcodec,                # Video codec name
                'acodec': acodec,                # Audio codec name
            })

    app.logger.info(f"Processed {len(processed_formats)} formats with URLs.")

    # Sort the processed formats:
    # 1. By type: Video+Audio first, then Video Only, then Audio Only
    # 2. By height (descending) - higher resolution first
    # 3. By total bitrate (descending) - higher quality first as tie-breaker
    processed_formats.sort(key=lambda x: (
        0 if x['type'] == 'Video+Audio' else 1 if x['type'] == 'Video Only' else 2, # Sort by type
        -(x.get('height') or 0),  # Sort by height descending (negative sign)
        -(x.get('tbr') or 0.0)    # Sort by tbr descending (negative sign)
    ))
    app.logger.info(f"Sorted formats for '{title}'.")

    # Return the results dictionary
    return {
        'title': title,
        'original_url': media_url,
        'formats': processed_formats
    }

# --- Authentication Decorator ---
def require_api_key(f):
    """Decorator to protect routes that require a valid API key."""
    @wraps(f) # Preserves original function metadata
    def decorated_function(*args, **kwargs):
        # Get API key from request header
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            app.logger.warning("API request missing X-API-Key header.")
            return jsonify({"success": False, "error": "API key required"}), 401 # Unauthorized

        # Check if the API key exists in the database
        user = User.query.filter_by(api_key=api_key).first()
        if not user:
            app.logger.warning(f"API request with invalid key: {api_key[:5]}...") # Log only prefix
            return jsonify({"success": False, "error": "Invalid API key"}), 401 # Unauthorized

        # --- Request Counting ---
        # Increment the user's request count
        try:
            user.request_count += 1
            db.session.commit() # Save the change to the database
            app.logger.info(f"Authenticated API request for user {user.email} (Key: {api_key[:5]}...). Count: {user.request_count}")
        except Exception as db_err:
            db.session.rollback() # Rollback DB changes on error
            app.logger.error(f"Failed to update request count for user {user.email}: {db_err}")
            # Decide if this error should block the request or just be logged
            # For now, just log it and continue the request.
            # Optionally, return an error:
            # return jsonify({"success": False, "error": "Database error during authentication"}), 500

        # --- Pass User Info (Optional) ---
        # You could pass the user object to the route function if needed
        # kwargs['user'] = user

        # Proceed with the original route function
        return f(*args, **kwargs)
    return decorated_function


# --- Flask Routes ---

@app.route('/')
def index():
    """Renders the main page (index_new.html)."""
    app.logger.info("Rendering index page.")
    # Assuming your main HTML file is named 'index_new.html' in the 'templates' folder
    return render_template('index_new.html')

# --- Developer Documentation Route ---
@app.route('/developer/doc')
def developer_doc():
    """Renders the API documentation page."""
    app.logger.info("Rendering developer documentation page.")
    # Define the path to the documentation file within the templates directory
    doc_path = os.path.join('developer', 'doc.html')
    full_doc_path = os.path.join(app.template_folder, doc_path)

    # Check if the documentation file actually exists
    if not os.path.exists(full_doc_path):
        app.logger.error(f"Developer documentation file not found at: {full_doc_path}")
        return "Documentation not found.", 404 # Not Found
    # Render the documentation template
    return render_template(doc_path)

# --- Route for the Web UI Form ---
@app.route('/get_formats', methods=['POST'])
@limiter.limit("10 per minute") # Apply specific rate limit to this endpoint
def get_formats():
    """
    Handles the POST request from the web UI form.
    Fetches formats and returns JSON data or error.
    Rate limited separately from the API.
    """
    media_url = request.form.get('media_url', '').strip()

    if not media_url:
        app.logger.warning("Web UI: Received empty URL submission.")
        return jsonify({'success': False, 'error': 'Please enter a valid media URL.'}), 400 # Bad Request

    app.logger.info(f"Web UI: Processing request for URL: {media_url}")

    try:
        # Call the helper function to get processed format data
        results_data = fetch_and_process_formats(media_url)

        # Check if any formats were actually found
        if not results_data['formats']:
             app.logger.warning(f"Web UI: No downloadable formats found for URL: {media_url}")
             return jsonify({'success': False, 'error': 'No downloadable formats found for this URL.'})

        # Prepare successful JSON response
        response_data = {
            'success': True,
            'data': results_data
        }
        return jsonify(response_data)

    except yt_dlp.utils.DownloadError as e:
        error_message = str(e)
        app.logger.error(f"Web UI: yt-dlp DownloadError for URL {media_url}: {error_message}", exc_info=False)
        user_error = 'Error fetching media details. Please check the URL or try again.' # Default error

        # --- Improved Error Message Handling ---
        if 'confirm you' in error_message and ('not a bot' in error_message or 'sign in' in error_message):
             user_error = 'Download failed: The source requires verification (e.g., CAPTCHA). Please try a different video or try again later.'
        elif 'Unsupported URL' in error_message:
            user_error = 'The provided URL is not supported.'
        elif 'Private video' in error_message or 'Login required' in error_message:
             user_error = 'This content is private or requires login.'
        elif 'Video unavailable' in error_message:
             user_error = 'This video is unavailable.'
        elif 'urlopen error' in error_message or 'Name or service not known' in error_message:
             user_error = 'Network error: Could not resolve the URL. Check the address or your connection.'
        # Add more specific checks as needed

        # Return JSON error response
        return jsonify({'success': False, 'error': user_error}), 500 # Internal Server Error or appropriate code

    except Exception as e:
        # Catch any other unexpected exceptions
        app.logger.error(f"Web UI: Unexpected error processing URL {media_url}: {e}", exc_info=True)
        # Return a generic server error message
        return jsonify({'success': False, 'error': 'An unexpected server error occurred. Please try again later.'}), 500

# --- API Endpoint ---
@app.route('/api/v1/formats', methods=['GET'])
@require_api_key # Apply the API key authentication decorator
@limiter.limit("60 per minute", key_func=lambda: request.headers.get('X-API-Key')) # Rate limit based on API Key
def api_get_formats():
    """
    Handles GET requests to the authenticated API endpoint.
    Expects 'url' query parameter and 'X-API-Key' header.
    Returns JSON format data or error. Rate limited by API key.
    """
    media_url = request.args.get('url', '').strip()

    if not media_url:
        app.logger.warning("API: Request missing 'url' query parameter.")
        return jsonify({'success': False, 'error': 'Missing required query parameter: url'}), 400 # Bad Request

    app.logger.info(f"API: Processing request for URL: {media_url} (Key: {request.headers.get('X-API-Key')[:5]}...)")

    try:
        # Call the helper function to get processed format data
        results_data = fetch_and_process_formats(media_url)

        # Check if any formats were actually found
        if not results_data['formats']:
             app.logger.warning(f"API: No downloadable formats found for URL: {media_url}")
             return jsonify({'success': False, 'error': 'No downloadable formats found for this URL.'})

        # Prepare successful JSON response
        response_data = {
            'success': True,
            'data': results_data
        }
        return jsonify(response_data)

    except yt_dlp.utils.DownloadError as e:
        error_message = str(e)
        app.logger.error(f"API: yt-dlp DownloadError for URL {media_url}: {error_message}", exc_info=False)
        user_error = 'Error fetching media details via API.' # Default API error

        # --- Improved Error Message Handling (API version) ---
        if 'confirm you' in error_message and ('not a bot' in error_message or 'sign in' in error_message):
             user_error = 'Download failed: Source requires verification (e.g., CAPTCHA).' # More concise for API
        elif 'Unsupported URL' in error_message:
            user_error = 'Unsupported URL.'
        elif 'Private video' in error_message or 'Login required' in error_message:
             user_error = 'Content is private or requires login.'
        elif 'Video unavailable' in error_message:
             user_error = 'Video unavailable.'
        elif 'urlopen error' in error_message or 'Name or service not known' in error_message:
             user_error = 'Network error resolving URL.'
        # Add more specific checks as needed

        return jsonify({'success': False, 'error': user_error}), 500 # Internal Server Error or appropriate code

    except Exception as e:
        # Catch any other unexpected exceptions
        app.logger.error(f"API: Unexpected error processing URL {media_url}: {e}", exc_info=True)
        # Return a generic server error message
        return jsonify({'success': False, 'error': 'An unexpected server error occurred.'}), 500


# --- Basic Registration Route (for demonstration) ---
# Apply rate limiting: 5 requests per minute per IP address
@app.route('/register_api_user', methods=['POST'])
@limiter.limit("5 per minute")
def register_api_user():
    """
    (Demo) Creates a user and returns their API key.
    Includes email/phone validation and rate limiting.
    Requires 'email' and 'phone' form parameters.
    """
    email = request.form.get('email', '').strip().lower() # Normalize to lowercase
    phone = request.form.get('phone', '').strip()

    # --- Input Validation ---
    if not email or not phone:
        app.logger.warning("Registration attempt with missing email or phone.")
        return jsonify({'success': False, 'error': 'Email and Phone are required.'}), 400

    # --- Email Validation ---
    # Define allowed domains (can be moved to config)
    allowed_domains = {'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com'}
    try:
        # Validate format and normalize (removes dots in gmail, etc.)
        email_info = validate_email(email, check_deliverability=False) # Deliverability check is slow/optional
        email = email_info.normalized # Use the normalized version for checks and storage

        # Check domain against allowed list
        domain = email.split('@')[1]
        if domain.lower() not in allowed_domains:
            app.logger.warning(f"Registration attempt with disallowed email domain: {domain}")
            allowed_list_str = ", ".join(sorted(allowed_domains))
            return jsonify({'success': False, 'error': f'Only emails from {allowed_list_str} are allowed.'}), 400

    except EmailNotValidError as e:
        # Email format is invalid
        app.logger.warning(f"Registration attempt with invalid email format: {email} - {e}")
        return jsonify({'success': False, 'error': str(e)}), 400 # Return the validation error message

    # --- Phone Validation (Basic Check) ---
    # This is a very basic check. Consider using 'phonenumbers' library for robust validation.
    # Allows digits and an optional leading '+'
    phone_to_check = phone.lstrip('+') # Remove leading '+' for digit check
    min_phone_length = 8 # Define minimum reasonable length

    if not phone_to_check.isdigit() or len(phone_to_check) < min_phone_length:
        app.logger.warning(f"Registration attempt with potentially invalid phone: {phone}")
        return jsonify({'success': False, 'error': f'Please provide a valid phone number (at least {min_phone_length} digits, optional leading +).'}), 400

    # --- Check for Existing User ---
    # Check if either the email or phone already exists in the database
    existing_user = User.query.filter((User.email == email) | (User.phone == phone)).first()
    if existing_user:
        app.logger.warning(f"Registration attempt for existing email/phone: {email}/{phone}")
        # Determine if email or phone caused the conflict for a slightly better message
        if existing_user.email == email:
            error_msg = 'Email address already registered.'
        else:
            error_msg = 'Phone number already registered.'
        return jsonify({'success': False, 'error': error_msg}), 409 # Conflict HTTP status

    # --- Create User ---
    try:
        # Create a new User instance (API key is generated by default)
        new_user = User(email=email, phone=phone)
        db.session.add(new_user) # Add to the session
        db.session.commit() # Commit changes to the database
        app.logger.info(f"Registered new API user: {email}, Key: {new_user.api_key[:5]}...")
        # Return success message and the new API key
        return jsonify({
            'success': True,
            'message': 'Registration successful! Please store your API key securely.',
            'api_key': new_user.api_key
        })
    except Exception as e:
        db.session.rollback() # Rollback database changes on error
        app.logger.error(f"Failed to register user {email}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to register user due to a server error.'}), 500


# --- Initialize Database ---
# Use app_context to ensure database operations have access to the application context
with app.app_context():
    try:
        db.create_all() # Create database tables based on models if they don't exist
        app.logger.info("Database tables checked/created.")
    except Exception as e:
        # Log error if database initialization fails (e.g., connection issues)
        app.logger.error(f"Failed to initialize database: {e}")
        # Depending on severity, you might want to exit or prevent the app from starting


# --- Run the Application (for local development) ---
# This block is typically not executed when running with a production WSGI server like Passenger
if __name__ == '__main__':
    # Get host/port/debug settings from environment variables or use defaults
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    # Default to debug mode True if FLASK_DEBUG is not set or not 'false'/'0'
    debug_mode = not os.environ.get('FLASK_DEBUG', 'True').lower() in ['false', '0', 'f']

    app.logger.info(f"Starting Flask development server on {host}:{port} (Debug: {debug_mode})")
    # Run the built-in Flask development server (NOT for production)
    app.run(host=host, port=port, debug=debug_mode)
