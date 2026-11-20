"""The first page must work before the collector has supplied a snapshot."""

from html.parser import HTMLParser
from importlib.resources import files


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_first_document_shows_loading_without_sample_data_or_preview_services():
    assets = files("joi_observer.web").joinpath("static")
    source = assets.joinpath("index.html").read_text(encoding="utf-8")
    doc = Document(source)
    by_id = {attrs["id"]: attrs for _, attrs in doc.elements if "id" in attrs}
    assert "hidden" not in by_id["loading"] and by_id["loading"]["role"] == "status"
    assert "hidden" in by_id["dashboard"] and "hidden" in by_id["error"]
    assert "hidden" in by_id["asset-error"] and by_id["asset-error"]["role"] == "alert"
    assert by_id["error"]["role"] == "alert"
    assert {"gpu", "host", "storage", "docker", "models", "detail"} <= by_id.keys()
    assert any(tag == "button" and "disabled" in attrs for tag, attrs in doc.elements)
    assert "refresh" in " ".join(doc.text).lower()
    assert all(sample not in source for sample in (
        "window.openai", "Amber Relay", "Vector Matrix", "H3C R5300", "PAN HISTORY", "15:42:08 CST",
    ))
    resources = [attrs[key] for _, attrs in doc.elements for key in ("src", "href") if key in attrs]
    assert sorted(resources) == ["/static/__JOI_RELEASE__/dashboard.css", "/static/__JOI_RELEASE__/dashboard.js"]
    for path in resources:
        assert assets.joinpath(path.rsplit("/", 1)[1]).is_file()
