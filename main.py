import os
import re
import uuid
import tempfile
import urllib.parse
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from dotenv import load_dotenv

app = FastAPI()

# Load environment variables from .env file
load_dotenv()

# CORS configuration
app.add_middleware(CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_cookies_path():
    """Get cookies from local file or COOKIES env var."""
    local_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
    if os.path.exists(local_path):
        return local_path

    cookies_data = os.getenv('COOKIES')
    if cookies_data:
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        tmp.write(cookies_data)
        tmp.close()
        return tmp.name

    return None


def safe_filename(title: str) -> str:
    """Make a filename safe for HTTP headers (ASCII-only) and filesystems."""
    # Replace path separators
    title = title.replace("/", "-").replace("\\", "-")
    # Remove characters that are invalid in filenames
    title = re.sub(r'[<>:"|?*]', '', title)
    # Strip non-ASCII characters (emojis, special chars) for header safety
    ascii_title = title.encode('ascii', errors='ignore').decode('ascii').strip()
    # Fallback if title becomes empty after stripping
    if not ascii_title:
        ascii_title = "video"
    return ascii_title


@app.get("/download")
async def download_video(url: str = Query(...), format: str = Query("best")):
    try:
        cookies_path = get_cookies_path()

        base_opts = {
            'quiet': True,
            'cookiefile': cookies_path,
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb', 'android', 'ios', 'tv_embedded'],
                }
            },
            'user_agent': 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
            'sleep_interval': 1,
            'max_sleep_interval': 5,
            'proxy': os.getenv('PROXY_URL'),
        }

        # Remove None values so yt-dlp doesn't choke
        base_opts = {k: v for k, v in base_opts.items() if v is not None}

        # Extract metadata first
        with yt_dlp.YoutubeDL({**base_opts, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            raw_title = info.get("title", "video")
            ascii_name = safe_filename(raw_title)
            filename = f"{ascii_name}.mp4"
            # URL-encoded version preserves Unicode for modern browsers
            filename_utf8 = urllib.parse.quote(f"{raw_title}.mp4")

        # Create a unique output template
        uid = uuid.uuid4().hex[:8]
        output_template = f"/tmp/{uid}.%(ext)s"

        ydl_opts = {
            **base_opts,
            'format': format,
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
        }

        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find actual downloaded file
        actual_file_path = None
        for f in os.listdir("/tmp"):
            if f.startswith(uid):
                actual_file_path = os.path.join("/tmp", f)
                break

        if not actual_file_path or not os.path.exists(actual_file_path):
            raise HTTPException(status_code=500, detail="Download failed or file not found.")

        # Stream file
        def iterfile():
            with open(actual_file_path, "rb") as f:
                yield from f
            os.unlink(actual_file_path)  # clean up after stream

        # Use both filename (ASCII fallback) and filename* (UTF-8 for modern browsers)
        content_disposition = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename_utf8}'

        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": content_disposition}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during download: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Welcome to the Social Media Video Downloader API. Use /download?url=<video_url>&format=<video_format> to download videos."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)