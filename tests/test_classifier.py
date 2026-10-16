import pytest

from clipvault.classifier.rules import classify, detect_language
from clipvault.core.model import Representation, Snapshot
from clipvault.engine import reclassify

from conftest import INLINE_MAX, png_rep, query, snap, text_rep


def _cls(text: str):
    return classify(snap(text_rep(text)))


def _cat(c):
    return next(t[4:] for t in c.tags if t.startswith("cat:"))


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/a?b=1#c",
        "http://localhost:8080/x",
        "www.example.org/path",
        "  https://example.com  ",
        "ftp://files.example.com/pub",
    ],
)
def test_url(text):
    c = _cls(text)
    assert "url" in c.tags and _cat(c) == "link"


@pytest.mark.parametrize(
    "text,tag",
    [
        ("someone@example.com", "email"),
        ("#ff8800", "color"),
        ("#F80", "color"),
        ("rgb(255, 136, 0)", "color"),
        ("hsl(30, 100%, 50%)", "color"),
        (r"C:\Users\legion\file.txt", "path"),
        (r"\\server\share\doc.docx", "path"),
        ("/usr/local/bin/python", "path"),
        ("~/projects/app", "path"),
    ],
)
def test_other_signals_land_in_other_category(text, tag):
    c = _cls(text)
    assert tag in c.tags and _cat(c) == "other"


@pytest.mark.parametrize(
    "text",
    [
        "Hôm nay trời đẹp, mình đi uống cà phê nhé.",
        "Meeting at 3pm. Bring the report and the slides.",
        "see https://example.com and https://example.org",  # nhiều URL → không phải link đơn
        "/help",
        "hello@",
        "#12",
        "Select the best option from the list below.",
        "I let x = 5 happen",
    ],
)
def test_plain_text_is_not_misclassified(text):
    c = _cls(text)
    assert _cat(c) == "text" and c.tags == {"cat:text"}


@pytest.mark.parametrize(
    "lang,code",
    [
        ("python", "def add(a, b):\n    return a + b\n"),
        ("python", "import os\nfrom pathlib import Path\n\nclass A:\n    def f(self):\n        return self.x\n"),
        ("javascript", "const x = 5;\nfunction f(a) { return a => a * 2; }\nconsole.log(x);"),
        ("typescript", "interface User {\n  name: string;\n}\nconst u: User = { name: 'a' };"),
        ("json", '{"name": "clipvault", "items": [1, 2, 3]}'),
        ("html", "<div class=\"a\"><p>Hello</p></div>"),
        ("xml", '<?xml version="1.0"?><root><a>1</a></root>'),
        ("sql", "SELECT id, name FROM users WHERE id = 1 ORDER BY name;"),
        ("java", "public class Main {\n  public static void main(String[] a) { System.out.println(1); }\n}"),
        ("csharp", "using System;\nnamespace App { class P { static void Main() { Console.WriteLine(1); } } }"),
        ("c", '#include <stdio.h>\nint main(void) { printf("hi"); return 0; }'),
        ("cpp", "#include <iostream>\nint main() { std::cout << 1; }"),
        ("go", 'package main\n\nfunc main() {\n\tfmt.Println("x")\n}'),
        ("rust", 'fn main() {\n    let mut x = 5;\n    println!("{}", x);\n}'),
        ("css", ".a { color: red; margin: 0; }"),
        ("powershell", "Get-ChildItem | Where-Object { $_.Length -gt 1 }"),
        ("bash", "#!/bin/bash\necho hi\n"),
        ("php", "<?php echo $x; ?>"),
    ],
)
def test_code_language(lang, code):
    assert detect_language(code) == lang
    c = _cls(code)
    assert {"code", f"lang:{lang}", "cat:code"} <= c.tags


def test_invalid_json_is_not_json():
    assert detect_language('{"a": 1,}') != "json"


def test_image_kind_and_category():
    c = classify(snap(png_rep(100)))
    assert c.kind == "image" and "cat:image" in c.tags


def test_image_with_text_stays_image():
    c = classify(snap(text_rep("https://example.com"), png_rep(100)))
    assert c.kind == "image" and "cat:image" in c.tags


def test_rich_and_unknown_kinds():
    html = Representation("HTML Format", "text/html", b"<b>x</b>")
    assert classify(snap(text_rep("x"), html)).kind == "rich"
    assert classify(snap(html)).kind == "rich"
    assert classify(snap(Representation("X", "application/x-unknown", b"1"))).kind == "other"
    assert "cat:other" in classify(snap(Representation("X", "application/x-unknown", b"1"))).tags


def test_classification_does_not_alter_snapshot_or_payload():
    s = snap(text_rep("def f():\n    pass\n"), png_rep(50))
    before = [(r.native_format, r.mime, bytes(r.data)) for r in s.representations]
    classify(s)
    assert [(r.native_format, r.mime, bytes(r.data)) for r in s.representations] == before


def test_large_text_is_classified_quickly():
    huge = "lorem ipsum dolor sit amet " * 100_000
    assert detect_language(huge) is None


def test_save_stores_kind_and_tags(service, db):
    r = service.process(snap(text_rep("https://example.com")))
    item = db.get_item(r.item_id)
    assert item.kind == "text" and item.category == "link" and "url" in item.tags


def test_code_item_exposes_language(service, db):
    r = service.process(snap(text_rep("def f(x):\n    return x\n")))
    item = db.get_item(r.item_id)
    assert item.category == "code" and item.language == "python"


# --- phân loại lại mục cũ (lưu từ Phase 1, chưa có tag) -----------------------------------------


def _insert_legacy(db, snapshot, clock):
    """Mô phỏng Phase 1: mục chỉ có kind, không có tag."""
    from clipvault.engine.dedupe import blob_hash, item_hash

    reps = snapshot.representations
    hashes = [blob_hash(r.data) for r in reps]
    return db.save(snapshot, item_hash(reps, hashes), hashes, "text", None, None, clock(), INLINE_MAX).item_id


def test_ensure_current_classifies_legacy_items_once(db, clock):
    link = _insert_legacy(db, snap(text_rep("https://example.com")), clock)
    code = _insert_legacy(db, snap(text_rep("def f():\n    pass\n")), clock)
    img = _insert_legacy(db, snap(png_rep(INLINE_MAX + 10)), clock)
    assert db.get_item(link).tags == frozenset()

    assert reclassify.ensure_current(db) == 3
    assert db.get_item(link).category == "link"
    assert db.get_item(code).language == "python"
    assert db.get_item(img).kind == "image" and db.get_item(img).category == "image"
    assert reclassify.ensure_current(db) == 0  # đã đúng phiên bản


def test_reclassify_keeps_manual_category(db, clock):
    item = _insert_legacy(db, snap(text_rep("https://example.com")), clock)
    db.change_category(item, "code")
    reclassify.reclassify_item(db, item)
    got = db.get_item(item)
    assert got.category == "code" and "manual" in got.tags and "url" in got.tags


def test_reclassify_does_not_touch_payload(db, clock):
    rep = text_rep("https://example.com")
    item = _insert_legacy(db, snap(rep), clock)
    reclassify.reclassify_item(db, item)
    assert db.representations(item) == [rep]
    assert query(db, "SELECT COUNT(*) FROM items") == [(1,)]
