import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User
from telegram.error import BadRequest, Conflict
from telegram.ext import MessageHandler

import main
from links import extract_link
from storage import Storage


@pytest.fixture(autouse=True)
def fresh_storage(monkeypatch):
    storage = Storage(":memory:")
    monkeypatch.setattr(main, "storage", storage)
    yield storage
    storage.close()


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
    monkeypatch.setattr(main, "download_with_ytdlp", lambda *a: (str(f), "video", "cap", "author"))
    apify = MagicMock()
    monkeypatch.setattr(main, "download_instagram_reel", apify)
    result = main.fetch_media_sync(extract_link("https://www.instagram.com/reel/A/"))
    assert result.source == "ytdlp" and result.caption == "cap" and result.author == "author"
    apify.assert_not_called()


def test_fetch_media_sync_falls_back_to_apify(monkeypatch):
    def fail(*a):
        raise main.YtDlpErrorForTest("login required")
    main.YtDlpErrorForTest = type("E", (Exception,), {})
    monkeypatch.setattr(main, "download_with_ytdlp", fail)
    monkeypatch.setattr(main, "download_instagram_reel", lambda url: ("/tmp/x.mp4", "video", None, None))
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


def _sent(message_id=99, file_id="FILE1"):
    return SimpleNamespace(
        message_id=message_id, video=SimpleNamespace(file_id=file_id), animation=None, photo=None, document=None
    )


def _context():
    bot = SimpleNamespace(
        send_video=AsyncMock(return_value=_sent()), send_photo=AsyncMock(), send_animation=AsyncMock(),
        send_document=AsyncMock(), send_message=AsyncMock(),
    )
    return SimpleNamespace(bot=bot, user_data={})


def _status():
    return MagicMock(edit_text=AsyncMock(), delete=AsyncMock())


def test_process_link_success_deletes_file_and_caches_file_id(monkeypatch, tmp_path, fresh_storage):
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    link = extract_link("https://www.instagram.com/reel/A_b/")
    fetch = AsyncMock(return_value=main.DownloadResult(str(f), "video", "подпись", source="ytdlp", author="chef"))
    monkeypatch.setattr(main, "fetch_media", fetch)
    monkeypatch.setattr(main, "DELETE_AFTER_SEND", True)
    ctx, status = _context(), _status()

    assert asyncio.run(main.process_link(ctx, link, 42, None, status, user_id=7, chat_type="private"))
    kwargs = ctx.bot.send_video.call_args.kwargs
    assert kwargs["caption"] == '<a href="https://www.instagram.com/reel/A_b/">Reels</a> · @chef'
    assert "message_thread_id" not in kwargs
    buttons = [b.callback_data for b in kwargs["reply_markup"].inline_keyboard[0]]
    assert buttons[0].startswith(main.SHOW_COMMENT_PREFIX) and buttons[1].startswith(main.FAVORITE_PREFIX)
    assert not f.exists()
    status.delete.assert_awaited()
    assert fresh_storage.get_media_by_url(link.url)["file_id"] == "FILE1"

    # Второй раз — мгновенно по file_id, без скачивания
    ctx2 = _context()
    assert asyncio.run(main.process_link(ctx2, link, 43, None, _status(), user_id=8))
    assert fetch.await_count == 1
    assert ctx2.bot.send_video.call_args.kwargs["video"] == "FILE1"
    counters = fresh_storage.counters()
    assert counters["source_ytdlp"] == 1 and counters["source_cache"] == 1 and counters["success"] == 2


def test_broken_file_id_falls_back_to_download(monkeypatch, tmp_path, fresh_storage):
    link = extract_link("https://www.tiktok.com/@u/video/1")
    media_id = fresh_storage.save_media(link.url, "tiktok", "video")
    fresh_storage.set_file_id(media_id, "BROKEN", "video")
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(main, "fetch_media", AsyncMock(return_value=main.DownloadResult(str(f), "video", source="ytdlp")))
    ctx = _context()
    ctx.bot.send_video = AsyncMock(side_effect=[BadRequest("wrong file identifier"), _sent(file_id="NEW")])
    assert asyncio.run(main.process_link(ctx, link, 42, None, _status()))
    assert fresh_storage.get_media(media_id)["file_id"] == "NEW"


def test_process_link_failure_shows_retry(monkeypatch):
    monkeypatch.setattr(main, "fetch_media", AsyncMock(return_value=main.DownloadResult()))
    ctx, status = _context(), _status()
    link = extract_link("https://www.tiktok.com/@u/video/1")
    assert not asyncio.run(main.process_link(ctx, link, 42, 7, status))
    markup = status.edit_text.call_args.kwargs["reply_markup"]
    retry_id = markup.inline_keyboard[0][0].callback_data[len(main.RETRY_DOWNLOAD_PREFIX):]
    assert main.RETRY_LINK_CACHE[retry_id] == link


def _callback(data, user_id=1):
    query = MagicMock(data=data, answer=AsyncMock(), from_user=SimpleNamespace(id=user_id), message=None)
    return SimpleNamespace(callback_query=query), query


def test_show_comment_missing_still_answers():
    update, query = _callback(f"{main.SHOW_COMMENT_PREFIX}nope")
    asyncio.run(main.button_callback(update, _context()))
    query.answer.assert_awaited()


def test_show_comment_from_storage(fresh_storage):
    media_id = fresh_storage.save_media("u", "instagram", "reel", "Текст подписи")
    update, query = _callback(f"{main.SHOW_COMMENT_PREFIX}{media_id}")
    asyncio.run(main.button_callback(update, _context()))
    assert "Текст подписи" in query.answer.call_args.args[0]


def test_favorite_button_and_saved_list(fresh_storage):
    media_id = fresh_storage.save_media("https://www.tiktok.com/@u/video/1", "tiktok", "video", "Смешные котики", "catlover")
    fresh_storage.set_file_id(media_id, "F", "video")
    update, query = _callback(f"{main.FAVORITE_PREFIX}{media_id}", user_id=5)
    asyncio.run(main.button_callback(update, _context()))
    assert "Добавлено" in query.answer.call_args.args[0]

    text, keyboard = main.render_saved(5, None)
    assert "TikTok · @catlover" in text and "Смешные котики" in text
    assert keyboard.inline_keyboard[0][0].callback_data == f"{main.SEND_SAVED_PREFIX}{media_id}"
    assert "ничего нет" in main.render_saved(5, "собаки")[0]
    assert "пусто" in main.render_saved(6, None)[0]

    # Нажатие на номер в /saved присылает видео по file_id
    ctx = _context()
    update, query = _callback(f"{main.SEND_SAVED_PREFIX}{media_id}", user_id=5)
    asyncio.run(main.button_callback(update, ctx))
    assert ctx.bot.send_video.call_args.kwargs["video"] == "F"
    assert ctx.bot.send_video.call_args.kwargs["chat_id"] == 5


def test_saved_pagination_buttons(fresh_storage):
    for i in range(12):
        fresh_storage.toggle_favorite(1, fresh_storage.save_media(f"https://www.instagram.com/reel/R{i}/", "instagram", "reel"))
    _, keyboard = main.render_saved(1, None)
    assert keyboard.inline_keyboard[-1][0].callback_data == f"{main.SAVED_PAGE_PREFIX}10"
    text, keyboard = main.render_saved(1, None, offset=10)
    assert "<b>11.</b>" in text and keyboard.inline_keyboard[-1][0].callback_data == f"{main.SAVED_PAGE_PREFIX}0"


def test_callback_data_fits_telegram_limit():
    assert len(f"{main.SHOW_COMMENT_PREFIX}{10**12}".encode()) <= 64
    assert len(f"{main.RETRY_DOWNLOAD_PREFIX}{'x' * 12}".encode()) <= 64


def test_conflict_logged_without_traceback(caplog):
    ctx = SimpleNamespace(error=Conflict("terminated by other getUpdates request"))
    with caplog.at_level("WARNING"):
        asyncio.run(main.error_handler(None, ctx))
    record = caplog.records[-1]
    assert record.levelname == "WARNING" and record.exc_info is None
