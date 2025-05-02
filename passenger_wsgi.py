import os
import sys

# Add the project directory to the Python path
# Ensure this path points to the directory containing your app.py
project_directory = os.path.dirname(__file__)
# If passenger_wsgi.py is *not* in the same directory as app.py,
# adjust the path accordingly. For example:
# project_directory = '/home/aticmatic/you.aticmatic.com'
sys.path.insert(0, project_directory)

# Import the Flask app instance from your app.py file
# Make sure app.py is in the project_directory specified above
try:
    # The name 'app' here must match the Flask instance variable name in your app.py
    # We alias it to 'application' because that's what Passenger/WSGI servers expect.
    from app import app as application
    print("Successfully imported Flask app as application.") # Add a print statement for confirmation
except ImportError as e:
    # Log the error to help diagnose path or import issues
    print(f"Error importing Flask app from app.py: {e}")
    # Re-raise the error to make the failure clear in Passenger logs
    raise
except Exception as e:
    # Catch other potential errors during import
    print(f"An unexpected error occurred during import: {e}")
    raise


# Optional: Add any environment variable settings needed for production here
# Example: Setting Flask environment to production
# os.environ['FLASK_ENV'] = 'production'
# Example: Setting Database URL if not already set by the server environment
# os.environ['DATABASE_URL'] = 'mysql+pymysql://user:pass@host/db'

# The 'application' variable is now the Flask app instance,
# ready for the WSGI server (Passenger) to use.
