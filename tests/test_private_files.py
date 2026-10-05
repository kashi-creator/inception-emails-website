import os

os.environ.setdefault("GHL_LOCATION_API_KEY", "test-pit-not-real")

from app import app  # noqa: E402


def test_source_and_private_files_are_not_served():
    client = app.test_client()
    for path in ["/app.py", "/ghl_client.py", "/brief.py", "/Procfile", "/requirements.txt",
                 "/.gitignore", "/.git/config", "/briefs/x.md", "/tests/test_apply.py"]:
        assert client.get(path).status_code == 404, path


def test_public_files_still_served():
    client = app.test_client()
    for path in ["/", "/robots.txt", "/llms.txt", "/sitemap.xml", "/learn-more", "/pricing", "/about", "/contact"]:
        assert client.get(path).status_code == 200, path
