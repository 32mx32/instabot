import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import MessageHandler

import main
from links import extract_link


class FakeApiError(Exception):
    def __init__(self, msg, status_code=None):
        super().__init__(msg)
        self.status_code = status_code


@pytest.mark.parametrize("error, expected", [
    (FakeApiError("whatever", status_code=402), True),
    (FakeApiError("whatever", status_code=429), True),
    (Exception("By launching this job you will exceed the memory limit... monthly usage hard limit exceeded"), True),
    (Exception("User was not found or authentication token is not valid"), True),
    (Exception("Request took 4013ms"), False),
    (Exception("invalid token in input"), False),
    (FakeApiError("Actor not found", status_code=404), False),
])
def test_rotation_error(error, expected):
    assert main.is_apify_rotation_error(error) is expected


def test_key_manager_rotation():
    manager = main.ApifyKeyManager(["k1", "k2", "k3"])
    manager.mark_limited("k1", Exception("limit"))
    assert manager.get_available_keys() == ["k2", "k3"]
    manager.mark_success("k3")
    assert manager.get_available_keys() == ["k3", "k2"]


def test_edited_messages_are_ignored():
    app = main.build_application()
    handler = next(h for h in app.handlers[0] if isinstance(h, MessageHandler))
    msg = Message(1, None, Chat(1, "private"), from_user=User(1, "a", False), text="https://www.instagram.com/reel/A/")
    assert handler.check_update(Update(1, message=msg))
    assert not handler.check_update(Update(2, edited_message=msg))


def test_fetch_media_sync_prefers_ytdlp(monkeypatch, tmp_path):
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(main, "download_with_ytdlp", lambda *a: (str(f), "video", "cap"))
    apify = MagicMock()
    monkeypatch.setattr(main, "download_instagram_reel", apify)
    result = main.fetch_media_sync(extract_link("https://www.instagram.com/reel/A/"))
    assert result.source == "ytdlp" and result.caption == "cap"
    apify.assert_not_called()


def test_fetch_media_sync_falls_back_to_apify(monkeypatch):
    def fail(*a):
        raise main.YtDlpErrorForTest("login required")
    main.YtDlpErrorForTest = type("E", (Exception,), {})
    monkeypatch.setattr(main, "download_with_ytdlp", fail)
    monkeypatch.setattr(main, "download_instagram_reel", lambda url: ("/tmp/x.mp4", "video", None))
    assert main.fetch_media_sync(extract_link("https://www.instagram.com/reel/A/")).source == "apify"


def test_fetch_media_sync_no_apify_for_tiktok(monkeypatch):
    def fail(*a):
        raise Exception("boom")
    monkeypatch.setattr(main, "download_with_ytdlp", fail)
    apify = MagicMock()
    monkeypatch.setattr(main, "download_instagram_reel", apify)
    result = main.fetch_media_sync(extract_link("https://www.tiktok.com/@u/video/1"))
    assert result.file_path is None
    apify.assert_not_called()


def test_too_large_stops_fallback(monkeypatch):
    def too_large(*a):
        raise main.FileTooLargeError("big")
    monkeypatch.setattr(main, "download_with_ytdlp", too_large)
    apify = MagicMock()
    monkeypatch.setattr(main, "download_instagram_reel", apify)
    assert main.fetch_media_sync(extract_link("https://www.instagram.com/reel/A/")).error == "too_large"
    apify.assert_not_called()


def test_download_does_not_block_event_loop(monkeypatch):
    """Пока идёт медленное скачивание, event loop продолжает работать."""
    monkeypatch.setattr(main, "_download_semaphore", None)
    monkeypatch.setattr(main, "fetch_media_sync",
                        lambda link: (time.sleep(1), main.DownloadResult("/tmp/x.mp4", "video"))[1])
    ticks = []

    async def ticker(t0):
        while time.time() - t0 < 1.0:
            await asyncio.sleep(0.05)
            ticks.append(time.time() - t0)

    async def run():
        t0 = time.time()
        await asyncio.gather(ticker(t0), main.fetch_media(extract_link("https://www.instagram.com/reel/A/"), None))

    asyncio.run(run())
    assert len([t for t in ticks if t < 0.9]) >= 10


def _context():
    bot = SimpleNamespace(send_video=AsyncMock(), send_photo=AsyncMock(), send_message=AsyncMock())
    return SimpleNamespace(bot=bot)


def test_process_link_success_deletes_file(monkeypatch, tmp_path):
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(main, "fetch_media", AsyncMock(return_value=main.DownloadResult(str(f), "video", "подпись", source="ytdlp")))
    monkeypatch.setattr(main, "DELETE_AFTER_SEND", True)
    ctx, status = _context(), MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
    link = extract_link("https://www.instagram.com/reel/A_b/")
    assert asyncio.run(main.process_link(ctx, link, 42, None, status))
    kwargs = ctx.bot.send_video.call_args.kwargs
    assert kwargs["caption"] == '<a href="https://www.instagram.com/reel/A_b/">Reels</a>'
    assert "message_thread_id" not in kwargs
    assert kwargs["reply_markup"] is not None
    assert not f.exists()
    status.delete.assert_awaited()


def test_process_link_failure_shows_retry(monkeypatch):
    monkeypatch.setattr(main, "fetch_media", AsyncMock(return_value=main.DownloadResult()))
    ctx, status = _context(), MagicMock(edit_text=AsyncMock(), delete=AsyncMock())
    link = extract_link("https://www.tiktok.com/@u/video/1")
    assert not asyncio.run(main.process_link(ctx, link, 42, 7, status))
    markup = status.edit_text.call_args.kwargs["reply_markup"]
    retry_id = markup.inline_keyboard[0][0].callback_data[len(main.RETRY_DOWNLOAD_PREFIX):]
    assert main.RETRY_LINK_CACHE[retry_id] == link


def test_show_comment_missing_still_answers():
    query = MagicMock(data=f"{main.SHOW_COMMENT_PREFIX}nope", answer=AsyncMock())
    asyncio.run(main.button_callback(SimpleNamespace(callback_query=query), None))
    query.answer.assert_awaited()
