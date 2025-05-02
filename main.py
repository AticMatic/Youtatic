import yt_dlp

ydl_opts = {
    'nocheckcertificate': True,
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download(['https://www.youtube.com/watch?v=K87aFjB7Ff0'])