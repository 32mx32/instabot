import pytest

from links import extract_link, is_instagram_stories, link_from_resolved_url


@pytest.mark.parametrize("text, expected_url, kind", [
    ("https://www.instagram.com/reel/ABC123/", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("https://www.instagram.com/reel/ABC123/?igsh=xyz", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("https://www.instagram.com/reels/ABC123/", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("https://m.instagram.com/reel/ABC123/", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("https://www.instagram.com/some.user/reel/ABC123/", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("instagram.com/p/Xy_-9/?img_index=1", "https://www.instagram.com/p/Xy_-9/", "post"),
    ("https://instagram.com/tv/TV1/", "https://www.instagram.com/tv/TV1/", "tv"),
    ("смотри https://www.instagram.com/reel/ABC123/ огонь", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("@https://www.instagram.com/reel/ABC123/,", "https://www.instagram.com/reel/ABC123/", "reel"),
    ("https://www.instagram.com/share/reel/BAxyz/", "https://www.instagram.com/share/reel/BAxyz/", "share"),
    ("https://www.tiktok.com/@user/video/7300000000000000000?lang=ru", "https://www.tiktok.com/@user/video/7300000000000000000?lang=ru", "video"),
    ("глянь vm.tiktok.com/ZMabc123/.", "https://vm.tiktok.com/ZMabc123/", "video"),
    ("https://youtube.com/shorts/dQw4w9WgXcQ?si=abc", "https://www.youtube.com/shorts/dQw4w9WgXcQ", "video"),
])
def test_extract_link(text, expected_url, kind):
    link = extract_link(text)
    assert link is not None
    assert link.url == expected_url
    assert link.kind == kind


@pytest.mark.parametrize("text", [
    "", "привет", "https://www.instagram.com/someuser/", "https://www.youtube.com/watch?v=abc",
    "https://www.instagram.com/stories/user/123/",
])
def test_extract_link_none(text):
    assert extract_link(text) is None


def test_platforms_and_labels():
    assert extract_link("https://www.instagram.com/p/A/").label == "Пост"
    assert extract_link("https://www.instagram.com/reel/A/").label == "Reels"
    assert extract_link("https://www.tiktok.com/@u/video/1").platform == "tiktok"
    assert extract_link("https://youtube.com/shorts/abcdef").label == "YouTube Shorts"


def test_share_link_needs_resolve():
    assert extract_link("https://www.instagram.com/share/BAxyz/").needs_resolve
    assert not extract_link("https://www.instagram.com/reel/A/").needs_resolve


@pytest.mark.parametrize("final_url, expected", [
    ("https://www.instagram.com/reel/ABC/?igsh=1", "https://www.instagram.com/reel/ABC/"),
    ("https://www.instagram.com/accounts/login/?next=%2Freel%2FABC%2F", "https://www.instagram.com/reel/ABC/"),
    ("https://www.instagram.com/accounts/login/?next=/p/XYZ/", "https://www.instagram.com/p/XYZ/"),
])
def test_link_from_resolved_url(final_url, expected):
    assert link_from_resolved_url(final_url).url == expected


def test_link_from_resolved_url_unknown():
    assert link_from_resolved_url("https://www.instagram.com/accounts/login/") is None


def test_stories():
    assert is_instagram_stories("https://www.instagram.com/stories/user/1/")
    assert not is_instagram_stories("https://www.instagram.com/reel/A/")
