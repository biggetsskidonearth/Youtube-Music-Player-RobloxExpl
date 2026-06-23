import asyncio
import json
import subprocess
import threading
import time
import os

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, ConnectionClosedError
except ImportError:
    print("FATAL: 'websockets' not installed. Run: pip install websockets")
    exit(1)

try:
    import yt_dlp
except ImportError:
    print("FATAL: 'yt-dlp' not installed. Run: pip install yt-dlp")
    exit(1)

# --- Configuration (Railway / Docker friendly) ---
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8765))
AUDIO_CACHE_DIR = os.getenv("AUDIO_CACHE_DIR", "cache")

os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

class PlayerState:
    def __init__(self):
        self.process = None
        self.is_playing = False
        self.is_paused = False
        self.current_url = None
        self.current_title = ""
        self.current_artist = ""
        self.duration = 0
        self.start_time = 0
        self.pause_time = 0
        self.volume = 0.5
        self.queue = []
        self.current_index = -1
        self.lock = threading.Lock()

state = PlayerState()
connected_clients = set()
loop = None

def get_duration(file_path):
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags
        )
        return float(result.stdout.strip())
    except:
        return 0.0

def search_youtube(query):
    print(f"[SEARCH] Query: {query}")
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': 'in_playlist', 'default_search': 'ytsearch15', 'forcejson': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch15:{query}", download=False)
            return [{'id': e.get('id'), 'title': e.get('title', 'Unknown'), 'artist': e.get('uploader', 'Unknown'), 'duration': e.get('duration', 0), 'url': f"https://www.youtube.com/watch?v={e.get('id')}"} for e in info.get('entries', []) if e]
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        return []

def extract_audio(video_id):
    print(f"[EXTRACT] ID: {video_id}")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{AUDIO_CACHE_DIR}/%(id)s.%(ext)s',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True, 'no_warnings': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            return f"{AUDIO_CACHE_DIR}/{video_id}.mp3", info.get('title', 'Unknown'), info.get('uploader', 'Unknown'), info.get('duration', 0)
    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        return None, None, None, 0

def play_audio(file_path):
    with state.lock:
        stop_audio()
        print(f"[PLAY] Starting: {file_path}")
        vol = max(0.01, state.volume * 2)
        cmd = ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', '-vn', '-ss', str(state.pause_time), '-af', f'volume={vol}', file_path]
        
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        state.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        state.is_playing = True
        state.is_paused = False
        state.start_time = time.time() - state.pause_time
        state.pause_time = 0

    def monitor():
        state.process.wait()
        with state.lock:
            if state.is_playing and not state.is_paused:
                state.is_playing = False
                state.pause_time = 0
                print("[EVENT] Song ended.")
                if state.current_index < len(state.queue) - 1:
                    state.current_index += 1
                    next_track = state.queue[state.current_index]
                    asyncio.run_coroutine_threadsafe(handle_play(next_track['id'], next_track.get('title'), next_track.get('artist'), next_track.get('duration')), loop)
                else:
                    asyncio.run_coroutine_threadsafe(broadcast_event('ended', {}), loop)

    threading.Thread(target=monitor, daemon=True).start()

def stop_audio():
    if state.process and state.process.poll() is None:
        try:
            state.process.stdin.write(b'q')
            state.process.stdin.flush()
            state.process.terminate()
        except: pass
    state.process = None
    state.is_playing = False
    state.is_paused = False
    state.pause_time = 0

def pause_audio():
    with state.lock:
        if state.process and state.process.poll() is None and not state.is_paused:
            state.pause_time = time.time() - state.start_time
            state.process.stdin.write(b'p')
            state.process.stdin.flush()
            state.is_paused = True
            state.is_playing = False

def resume_audio():
    with state.lock:
        if state.process and state.process.poll() is None and state.is_paused:
            state.process.stdin.write(b'p')
            state.process.stdin.flush()
            state.is_playing = True
            state.is_paused = False
            state.start_time = time.time() - state.pause_time

async def broadcast_event(event_type, data):
    msg = json.dumps({"type": "event", "event": event_type, "data": data})
    dead = []
    for ws in connected_clients:
        try: await ws.send(msg)
        except: dead.append(ws)
    for ws in dead: connected_clients.remove(ws)

async def send_state(ws):
    current_time = 0
    with state.lock:
        if state.is_playing: current_time = time.time() - state.start_time
        elif state.is_paused: current_time = state.pause_time
        
        state_msg = {
            "type": "sync",
            "data": {
                "is_playing": state.is_playing,
                "is_paused": state.is_paused,
                "title": state.current_title,
                "artist": state.current_artist,
                "duration": state.duration,
                "current_time": current_time,
                "volume": state.volume,
                "queue": state.queue,
                "current_index": state.current_index
            }
        }
    await ws.send(json.dumps(state_msg))

async def handle_play(video_id, title=None, artist=None, duration=0):
    await broadcast_event('loading', {'title': title or 'Loading...'})
    curr_loop = asyncio.get_running_loop()
    file_path, t, a, d = await curr_loop.run_in_executor(None, extract_audio, video_id)
    
    if file_path:
        with state.lock:
            state.current_url = video_id
            state.current_title = t or title or "Unknown"
            state.current_artist = a or artist or "Unknown"
            state.duration = d or duration
        play_audio(file_path)
    else:
        await broadcast_event('error', {'message': 'Failed to extract audio.'})

async def handler(websocket):
    connected_clients.add(websocket)
    print(f"[WS] + Client connected. Total: {len(connected_clients)}")
    try:
        await send_state(websocket)
        async for message in websocket:
            try:
                msg = json.loads(message)
                action = msg.get("action")
                payload = msg.get("data", {})

                if action == "search":
                    curr_loop = asyncio.get_running_loop()
                    results = await curr_loop.run_in_executor(None, search_youtube, payload.get("query", ""))
                    await websocket.send(json.dumps({"type": "search_results", "data": results}))

                elif action == "play":
                    vid = payload.get("id")
                    if vid:
                        if not any(q['id'] == vid for q in state.queue):
                            state.queue.append({'id': vid, 'title': payload.get('title', ''), 'artist': payload.get('artist', ''), 'duration': payload.get('duration', 0)})
                        state.current_index = next((i for i, q in enumerate(state.queue) if q['id'] == vid), len(state.queue)-1)
                        await handle_play(vid, payload.get('title'), payload.get('artist'), payload.get('duration'))

                elif action == "pause": pause_audio()
                elif action == "resume": resume_audio()
                elif action == "stop":
                    stop_audio()
                    await broadcast_event('stopped', {})
                elif action == "next":
                    if state.current_index < len(state.queue) - 1:
                        state.current_index += 1
                        t = state.queue[state.current_index]
                        await handle_play(t['id'], t['title'], t['artist'], t['duration'])
                elif action == "prev":
                    if state.current_index > 0:
                        state.current_index -= 1
                        t = state.queue[state.current_index]
                        await handle_play(t['id'], t['title'], t['artist'], t['duration'])
                elif action == "seek":
                    with state.lock:
                        if state.process and state.process.poll() is None:
                            seek_time = payload.get("time", 0)
                            stop_audio()
                            state.pause_time = seek_time
                            play_audio(f"{AUDIO_CACHE_DIR}/{state.current_url}.mp3")
                elif action == "volume":
                    state.volume = payload.get("volume", 0.5)
                elif action == "clear_queue":
                    stop_audio()
                    state.queue = []
                    state.current_index = -1
                    await broadcast_event('queue_cleared', {})
            except json.JSONDecodeError:
                pass
            except Exception as e:
                print(f"[ERROR] Msg handling: {e}")

    except (ConnectionClosed, ConnectionClosedError) as e:
        print(f"[WS] x Client disconnected. Code: {e.code}")
    except Exception as e:
        print(f"[WS] ! Client disconnected. Error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        print(f"[WS] - Client removed. Total: {len(connected_clients)}")

async def main():
    global loop
    loop = asyncio.get_running_loop()
    print(f"Starting Industrial YT Player on ws://{HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT, ping_interval=20, ping_timeout=60, close_timeout=5):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
