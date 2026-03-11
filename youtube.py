import yt_dlp
import os
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from os import getenv
from dotenv import load_dotenv
load_dotenv()

API_ID = getenv("API_ID")
API_HASH = getenv("API_HASH")
BOT_TOKEN = getenv("BOT_TOKEN")

app = Client("mybot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

LOG_CHANNEL = getenv("LOG_CHANNEL")  # your channel id

async def log_download(client, user_id, username, url):
    try:
        await client.send_message(
            LOG_CHANNEL,
            f"👤 User: {user_id} (@{username or 'no username'})\n"
            f"🔗 URL: {url}\n"
        )
    except Exception as e:
        pass
user_state = {}

SILENT_LOGGER = type("L", (), {
    "debug": staticmethod(lambda msg: None),
    "info": staticmethod(lambda msg: None),
    "warning": staticmethod(lambda msg: None),
    "error": staticmethod(lambda msg: None),
})()

# ─────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────

def main_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📎 YouTube Link")]],
        resize_keyboard=True
    )

def format_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎬 Video"), KeyboardButton("♫ Audio")],
            [KeyboardButton("🔙 Back")]
        ],
        resize_keyboard=True
    )

def quality_keyboard(formats):
    buttons = []
    for f in formats:
        size = f"~{f['filesize']/1024/1024:.1f}MB" if f["filesize"] else ""
        buttons.append([KeyboardButton(f"📹 {f['height']}p  {size}")])
    buttons.append([KeyboardButton("🔙 Back")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def audio_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("♫ MP3"), KeyboardButton("♫ M4A")],
            [KeyboardButton("🔙 Back")]
        ],
        resize_keyboard=True
    )

def playlist_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⬇️ All"), KeyboardButton("🔢 Specific Range")],
            [KeyboardButton("🔙 Back")]
        ],
        resize_keyboard=True
    )

# ─────────────────────────────────────────
# YT-DLP HELPERS
# ─────────────────────────────────────────

def is_valid_youtube_url(url):
    return any(x in url for x in [
        "youtube.com/watch?v=",
        "youtu.be/",
        "youtube.com/playlist?list=",
        "youtube.com/shorts/"
    ])

def is_playlist(url):
    return "playlist?list=" in url

def clean_url(url):
    # strip &list= from single video urls
    if "watch?v=" in url and "&list=" in url:
        return url.split("&list=")[0]
    return url

def get_info(url):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "logger": SILENT_LOGGER}) as ydl:
            return ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        error = str(e).lower()
        if "private" in error:
            return "private"
        elif "age" in error or "inappropriate" in error:
            return "age"
        elif "not available" in error or "unavailable" in error:
            return "unavailable"
        else:
            return "error"
    except Exception:
        return "error"

def get_playlist_info(url):
    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "logger": SILENT_LOGGER,
            "extract_flat": True,
        }) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception:
        return None

def get_formats(info):
    best_audio_size = 0
    for f in info["formats"]:
        if f.get("vcodec") == "none" and f.get("acodec") != "none" and f.get("ext") == "m4a":
            size = f.get("filesize") or f.get("filesize_approx") or 0
            if size > best_audio_size:
                best_audio_size = size

    formats = []
    seen = set()
    for f in info["formats"]:
        height = f.get("height")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        ext = f.get("ext")
        if height and vcodec != "none" and acodec == "none" and ext == "mp4":
            if height not in seen:
                seen.add(height)
                video_size = f.get("filesize") or f.get("filesize_approx") or 0
                formats.append({
                    "height": height,
                    "filesize": video_size + best_audio_size if video_size else None,
                })
    formats.sort(key=lambda x: x["height"])
    return formats

# ─────────────────────────────────────────
# PLAYLIST DOWNLOADER
# ─────────────────────────────────────────

async def download_playlist(message, user_id, state, height=None, audio_fmt=None):
    url = state["url"]
    start = state["start"]
    end = state["end"]
    total = end - start + 1

    await message.reply(
        f"⏳ Starting download of {total} videos...",
        reply_markup=ReplyKeyboardRemove()
    )

    for i, index in enumerate(range(start, end + 1), 1):
        msg = await message.reply(f"⏳ Downloading video {i}/{total}...")

        if height:
            ydl_opts = {
                "format": (
                    f"bestvideo[height={height}][vcodec^=av01]+bestaudio[ext=m4a]/"
                    f"bestvideo[height={height}][vcodec^=vp9]+bestaudio[ext=m4a]/"
                    f"bestvideo[height={height}]+bestaudio"
                ),
                "merge_output_format": "mp4",
                "outtmpl": "/tmp/%(title)s.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "logger": SILENT_LOGGER,
                "playlist_items": str(index),
            }
        else:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": "/tmp/%(title)s.%(ext)s",
                "quiet": True,
                "no_warnings": True,
                "logger": SILENT_LOGGER,
                "playlist_items": str(index),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_fmt,
                }],
            }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                entry = dl_info["entries"][0] if "entries" in dl_info else dl_info
                filepath = ydl.prepare_filename(entry)
                if height and not filepath.endswith(".mp4"):
                    filepath = filepath.rsplit(".", 1)[0] + ".mp4"
                if audio_fmt:
                    filepath = filepath.rsplit(".", 1)[0] + f".{audio_fmt}"

            await msg.edit(f"📤 Uploading video {i}/{total}...")
            caption = f"{'🎬' if height else '🎵'} {entry['title']} ({i}/{total})"
            await message.reply_document(filepath, caption=caption)
            os.remove(filepath)

        except Exception as e:
            await msg.edit(f"✘ Video {i} failed: {e}")

    user_state[user_id] = {"step": "idle"}
    await message.reply(f"✅ Done! {total} videos sent.", reply_markup=main_keyboard())

# ─────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────

@app.on_message(filters.command("start"))
async def start(client, message):
    user_state[message.from_user.id] = {"step": "idle"}
    await message.reply(
        "👋 Welcome! Press the button below to download a YouTube video.",
        reply_markup=main_keyboard()
    )

@app.on_message(filters.text & ~filters.command("start"))
async def handle_text(client, message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_state.get(user_id, {"step": "idle"})

    # ── Back ──
    if text == "🔙 Back":
        user_state[user_id] = {"step": "idle"}
        await message.reply("🏠 Main menu.", reply_markup=main_keyboard())
        return

    # ── Main menu ──
    if text == "📎 YouTube Link":
        user_state[user_id] = {"step": "awaiting_url"}
        await message.reply("🔗 Paste your YouTube URL:", reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("🔙 Back")]], resize_keyboard=True
        ))
        return

    # ── Awaiting URL ──
    if state["step"] == "awaiting_url":
        if not is_valid_youtube_url(text):
            await message.reply("✘ Invalid URL. Please send a valid YouTube link.")
            return

        text = clean_url(text)
        await log_download(client, user_id, message.from_user.username, text)
        
        msg = await message.reply("🔍 Fetching info...")

        if is_playlist(text):
            info = get_playlist_info(text)
            if not info:
                await msg.edit("✘ Could not fetch playlist. Try again.")
                return

            count = len(info.get("entries", []))
            title = info.get("title", "Playlist")

            if count == 0:
                await msg.edit("✘ Playlist is empty.")
                return

            user_state[user_id] = {
                "step": "awaiting_playlist_range",
                "url": text,
                "playlist_count": count,
            }
            await msg.edit(f"📋 {title}\n{count} videos\n\nChoose download range:")
            await message.reply("👇", reply_markup=playlist_keyboard())

        else:
            info = get_info(text)
            if info == "private":
                await msg.edit("✘ This video is private.")
                return
            elif info == "age":
                await msg.edit("✘ This video is age restricted.")
                return
            elif info in ("unavailable", "error"):
                await msg.edit("✘ Could not fetch video. Try again.")
                return

            user_state[user_id] = {
                "step": "awaiting_format",
                "url": text,
                "formats": get_formats(info)
            }
            await msg.edit(f"✓ {info['title']}\n\nChoose format:")
            await message.reply("👇", reply_markup=format_keyboard())
        return

    # ── Awaiting format (single video) ──
    if state["step"] == "awaiting_format":
        if text == "🎬 Video":
            formats = state["formats"]
            if not formats:
                await message.reply("✘ No video formats found.")
                return
            user_state[user_id]["step"] = "awaiting_quality"
            await message.reply("🎬 Choose resolution:", reply_markup=quality_keyboard(formats))

        elif text == "♫ Audio":
            user_state[user_id]["step"] = "awaiting_audio_fmt"
            await message.reply("♫ Choose audio format:", reply_markup=audio_keyboard())
        return

    # ── Awaiting quality (single video) ──
    if state["step"] == "awaiting_quality":
        try:
            height = int(text.split("p")[0].split()[-1])
        except:
            await message.reply("✘ Invalid choice.")
            return

        url = state["url"]
        await message.reply("⏳ Downloading...", reply_markup=ReplyKeyboardRemove())
        msg = await message.reply("⏳ Please wait...")

        ydl_opts = {
            "format": (
                f"bestvideo[height={height}][vcodec^=av01]+bestaudio[ext=m4a]/"
                f"bestvideo[height={height}][vcodec^=vp9]+bestaudio[ext=m4a]/"
                f"bestvideo[height={height}]+bestaudio"
            ),
            "merge_output_format": "mp4",
            "outtmpl": "/tmp/%(title)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "logger": SILENT_LOGGER,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(dl_info)
                if not filepath.endswith(".mp4"):
                    filepath = filepath.rsplit(".", 1)[0] + ".mp4"
            await msg.edit("📤 Uploading...")
            await message.reply_document(filepath, caption=f"🎬 {dl_info['title']}")
            os.remove(filepath)
        except Exception as e:
            await msg.edit(f"✘ Download failed: {e}")

        user_state[user_id] = {"step": "idle"}
        await message.reply("✓ Done!", reply_markup=main_keyboard())
        return

    # ── Awaiting audio format (single video) ──
    if state["step"] == "awaiting_audio_fmt":
        if text not in ["♫ MP3", "♫ M4A"]:
            await message.reply("✘ Invalid choice.")
            return

        fmt = "mp3" if "MP3" in text else "m4a"
        url = state["url"]
        await message.reply("⏳ Downloading audio...", reply_markup=ReplyKeyboardRemove())
        msg = await message.reply("⏳ Please wait...")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "/tmp/%(title)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "logger": SILENT_LOGGER,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": fmt,
            }],
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                filepath = f"/tmp/{dl_info['title']}.{fmt}"
            await msg.edit("📤 Uploading...")
            await message.reply_document(filepath, caption=f"🎵 {dl_info['title']}")
            os.remove(filepath)
        except Exception as e:
            await msg.edit(f"✘ Download failed: {e}")

        user_state[user_id] = {"step": "idle"}
        await message.reply("✓ Done!", reply_markup=main_keyboard())
        return

    # ── Awaiting playlist range ──
    if state["step"] == "awaiting_playlist_range":
        count = state["playlist_count"]

        if text == "⬇️ All":
            if count > 50:
                await message.reply(
                    f"⚠️ Playlist has {count} videos. Max is 50.\n"
                    f"Use Specific Range to pick up to 50."
                )
                return
            user_state[user_id]["start"] = 1
            user_state[user_id]["end"] = count
            user_state[user_id]["step"] = "awaiting_playlist_format"
            await message.reply("Choose format:", reply_markup=format_keyboard())

        elif text == "🔢 Specific Range":
            user_state[user_id]["step"] = "awaiting_range_input"
            await message.reply(
                f"Playlist has {count} videos.\nSend range e.g: 1-10\nMax 50 videos.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("🔙 Back")]], resize_keyboard=True
                )
            )
        else:
            await message.reply("✘ Please use the buttons.")
        return

    # ── Awaiting range input ──
    if state["step"] == "awaiting_range_input":
        try:
            parts = text.strip().split("-")
            start = int(parts[0].strip())
            end = int(parts[1].strip())
            count = state["playlist_count"]

            if start < 1 or end > count or start > end:
                await message.reply(f"✘ Invalid range. Must be between 1 and {count}.")
                return
            if end - start + 1 > 50:
                await message.reply("✘ Max 50 videos. Narrow your range.")
                return
        except:
            await message.reply("✘ Send range like: 1-10")
            return

        user_state[user_id]["start"] = start
        user_state[user_id]["end"] = end
        user_state[user_id]["step"] = "awaiting_playlist_format"
        await message.reply("Choose format:", reply_markup=format_keyboard())
        return

    # ── Awaiting playlist format ──
    if state["step"] == "awaiting_playlist_format":
        if text == "🎬 Video":
            msg = await message.reply("🔍 Fetching available qualities...")
            playlist_info = get_playlist_info(state["url"])
            if not playlist_info or not playlist_info.get("entries"):
                await msg.edit("✘ Could not fetch formats.")
                return

            first_url = f"https://www.youtube.com/watch?v={playlist_info['entries'][0]['id']}"
            info = get_info(first_url)
            if not info or isinstance(info, str):
                await msg.edit("✘ Could not fetch formats.")
                return

            formats = get_formats(info)
            if not formats:
                await msg.edit("✘ No formats found.")
                return

            user_state[user_id]["step"] = "awaiting_playlist_quality"
            user_state[user_id]["formats"] = formats
            await msg.edit("🎬 Choose resolution:")
            await message.reply("👇", reply_markup=quality_keyboard(formats))

        elif text == "♫ Audio":
            user_state[user_id]["step"] = "awaiting_playlist_audio_fmt"
            await message.reply("♫ Choose audio format:", reply_markup=audio_keyboard())
        return

    # ── Awaiting playlist quality ──
    if state["step"] == "awaiting_playlist_quality":
        try:
            height = int(text.split("p")[0].split()[-1])
        except:
            await message.reply("✘ Invalid choice.")
            return
        await download_playlist(message, user_id, state, height=height)
        return

    # ── Awaiting playlist audio format ──
    if state["step"] == "awaiting_playlist_audio_fmt":
        if text not in ["♫ MP3", "♫ M4A"]:
            await message.reply("✘ Invalid choice.")
            return
        fmt = "mp3" if "MP3" in text else "m4a"
        await download_playlist(message, user_id, state, audio_fmt=fmt)
        return

    # ── Default ──
    await message.reply("👇 Press the button below to start.", reply_markup=main_keyboard())

async def health(request):
    return web.Response(text="OK")

async def start_web():
    app_web = web.Application()
    app_web.router.add_get("/", health)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("Web server running on port 8080")

async def main():
    await start_web()
    await app.start()
    print("Bot is running...")
    await asyncio.get_event_loop().run_forever()

asyncio.run(main())
