# Youtatic Media Downloader

An open‑source Flask application for extracting and downloading audio and video from YouTube and hundreds of other supported platforms. Offers both a sleek web UI and a simple JSON API for easy integration into your own projects.

> ⚠️ **Educational Purpose Only**
> This repository is provided by Aticmatic purely for educational use. Respect all source site terms of service and fair use policies.

---

## Features

* 🚀 **Fast extraction** of available media formats using `yt-dlp`.
* 🎨 **Responsive web interface** built with TailwindCSS and Alpine.js.
* 🔑 **API access** with API key registration and rate limiting.
* 📊 **Download stats** (filesize, resolution, codecs, bitrates).
* 🔒 **Security** via request throttling and API key authentication.
* 📦 **Persistent user tracking** with Flask‑SQLAlchemy and MySQL (or MariaDB).

---

## Prerequisites

* Python 3.7 or higher
* MySQL or MariaDB server

### Python Dependencies

```
yt-dlp
certifi
flask
humanize
Flask-SQLAlchemy
PyMySQL
email_validator
Flask-Limiter
```

---

## Installation

1. **Clone this repository**

   ```bash
   git clone https://github.com/AticMatic/media-downloader.git
   cd media-downloader
   ```

2. **Create & activate a virtual environment**

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Create a `.env` file in the project root with:

   ```ini
   FLASK_APP=main.py
   FLASK_ENV=development      # or production
   DATABASE_URL=mysql+pymysql://<user>:<pass>@<host>/<database>
   SECRET_KEY=your-secret-key
   ```

5. **Initialize the database**

   ```bash
   flask db upgrade    # if using migrations, or
   python -c "from main import db; db.create_all()"
   ```

6. **Run the server**

   ```bash
   flask run --host 0.0.0.0 --port 5000
   ```

   Then visit [http://localhost:5000](http://localhost:5000) in your browser.

---

## Usage

### Web UI

1. Paste any supported media URL in the input field.
2. Click **"Find Download Options"**.
3. Browse and download your desired format.

### JSON API

1. **Register for an API key**:

   ```bash
   curl -X POST http://localhost:5000/register_api_user \
     -d "email=user@example.com" -d "phone=+1234567890"
   ```

   Response:

   ```json
   {
     "success": true,
     "email": "user@example.com",
     "api_key": "YOUR-API-KEY"
   }
   ```

2. **Fetch formats**:

   ```bash
   curl -G http://localhost:5000/api/v1/formats \
     -H "X-API-Key: YOUR-API-KEY" \
     --data-urlencode "url=https://youtu.be/abc123"
   ```

   Sample response:

   ```json
   {
     "success": true,
     "data": {
       "title": "Video Title",
       "original_url": "https://youtu.be/abc123",
       "formats": [ /* array of format objects */ ]
     }
   }
   ```

3. **Error format**:

   ```json
   { "success": false, "error": "Description of error" }
   ```

---

## Configuration & Rate Limiting

* Rate limiting per IP or per API key is enforced via `Flask-Limiter`.
* Adjust limits in the application configuration (see `main.py`).

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m "Add feature"\`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

Please keep PRs focused and write clear commit messages.

---

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.

---

> Provided by **Aticmatic** for educational purposes only.
