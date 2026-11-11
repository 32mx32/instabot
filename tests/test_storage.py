import pytest

from storage import Storage


@pytest.fixture
def db():
    storage = Storage(":memory:")
    yield storage
    storage.close()


def test_save_media_upsert_keeps_id_and_caption(db):
    first = db.save_media("https://www.instagram.com/reel/A/", "instagram", "reel", "Подпись", "author1")
    second = db.save_media("https://www.instagram.com/reel/A/", "instagram", "reel", None, None)
    assert first == second
    row = db.get_media(first)
    assert row["caption"] == "Подпись" and row["author"] == "author1"


def test_file_id_lifecycle(db):
    media_id = db.save_media("u1", "tiktok", "video")
    assert db.get_media_by_url("u1")["file_id"] is None
    db.set_file_id(media_id, "FILE", "video")
    assert db.get_media_by_url("u1")["file_id"] == "FILE"
    db.forget_file_id(media_id)
    assert db.get_media_by_url("u1")["file_id"] is None


def test_counters_and_users(db):
    db.incr("total")
    db.incr("total", 2)
    db.touch_user(1)
    db.touch_user(1)
    db.touch_user(2)
    assert db.counters()["total"] == 3
    assert db.user_count() == 2


def test_favorites_toggle_and_order(db):
    a = db.save_media("a", "instagram", "reel", "Первый")
    b = db.save_media("b", "tiktok", "video", "Второй")
    assert db.toggle_favorite(1, a) is True
    assert db.toggle_favorite(1, b) is True
    rows, total = db.list_favorites(1)
    assert total == 2 and [r["url"] for r in rows] == ["b", "a"]  # новые сверху
    assert db.toggle_favorite(1, a) is False  # повторное нажатие убирает
    assert db.list_favorites(1)[1] == 1
    assert db.list_favorites(2)[1] == 0  # у другого пользователя своя коллекция


def test_favorites_search_cyrillic_case_insensitive(db):
    a = db.save_media("a", "instagram", "reel", "Лучший РЕЦЕПТ борща", "chef")
    b = db.save_media("b", "tiktok", "video", "Котики", "cats")
    db.toggle_favorite(1, a)
    db.toggle_favorite(1, b)
    assert [r["url"] for r in db.list_favorites(1, "рецепт")[0]] == ["a"]
    assert [r["url"] for r in db.list_favorites(1, "CATS")[0]] == ["b"]
    assert [r["url"] for r in db.list_favorites(1, "tiktok")[0]] == ["b"]
    assert db.list_favorites(1, "нет такого")[1] == 0


def test_favorites_pagination(db):
    for i in range(12):
        db.toggle_favorite(1, db.save_media(f"u{i}", "instagram", "reel"))
    page1, total = db.list_favorites(1, limit=10)
    page2, _ = db.list_favorites(1, limit=10, offset=10)
    assert total == 12 and len(page1) == 10 and len(page2) == 2
