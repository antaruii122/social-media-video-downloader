import os
import uuid
import tempfile
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
    """Get cookies from local file or YOUTUBE_COOKIES env var."""
    local_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
    if os.path.exists(local_path):
        return local_path

    cookies_data = os.getenv('YOUTUBE_COOKIES')
    if cookies_data:
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        tmp.write(cookies_data)
        tmp.close()
        return tmp.name

    return None


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
            'proxy': os.getenv('PROXY_URL'),  # Optional: set in Railway vars
        }

        # Remove None values so yt-dlp doesn't choke
        base_opts = {k: v for k, v in base_opts.items() if v is not None}

        # Extract metadata first
        with yt_dlp.YoutubeDL({**base_opts, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "video").replace("/", "-").replace("\\", "-")
            filename = f"{title}.mp4"

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

        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during download: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Welcome to the Social Media Video Downloader API. Use /download?url=<video_url>&format=<video_format> to download videos."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)