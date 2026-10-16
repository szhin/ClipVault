"""Phân loại Snapshot -> (kind, tags). Thuần, chỉ đọc: không sửa, không lưu, không log nội dung.

Quy ước tag (lưu trong bảng `tags`, không đổi schema):
  url | email | color | path | code   tín hiệu nội dung
  lang:<tên>                           ngôn ngữ của code (python, javascript, json, ...)
  cat:<danh mục>                       image | link | code | text | other (danh mục hiển thị)
  manual                               người dùng đã Change Type; `cat:*` không bị phân loại lại đè
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from clipvault.core.model import Representation, Snapshot

CATEGORIES = ("image", "text", "link", "code", "other")
TAG_CAT = "cat:"
TAG_LANG = "lang:"
TAG_MANUAL = "manual"
CLASSIFIER_VERSION = "1"

_MAX_SCAN = 20_000  # chỉ quét đầu văn bản để heuristic rẻ với văn bản lớn
_MAX_JSON = 1_000_000


@dataclass(frozen=True)
class Classification:
    kind: str  # text | rich | image | files | other
    tags: frozenset[str]


# --- trích văn bản (chỉ để phân loại; không ghi ngược) -----------------------------------------


def text_of(reps: tuple[Representation, ...]) -> str | None:
    for rep in reps:
        if rep.mime == "text/plain":
            codec = "utf-16-le" if rep.native_format == "CF_UNICODETEXT" else "utf-8"
            return rep.data.decode(codec, errors="replace").split("\x00", 1)[0]
    return None


# --- tín hiệu đơn giản --------------------------------------------------------------------------

_URL = re.compile(r"^(?:https?|ftp)://[^\s<>\"]+$", re.I)
_WWW = re.compile(r"^www\.[^\s<>\"]+\.[a-z]{2,}(?:[/?#][^\s<>\"]*)?$", re.I)
_EMAIL = re.compile(r"^[^@\s<>\"]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
_COLOR = re.compile(
    r"^(?:#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})|(?:rgb|hsl)a?\([^()\n]{5,40}\))$", re.I
)
_PATH_WIN = re.compile(r'^(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/])[^\r\n<>"|?*]*$')
_PATH_POSIX = re.compile(r"^(?:/|~/)[\w.@+\-]+(?:/[\w.@+\-]+)+/?$")


def _single_line_tags(s: str) -> set[str]:
    tags: set[str] = set()
    if _URL.match(s) or _WWW.match(s):
        tags.add("url")
    elif _EMAIL.match(s):
        tags.add("email")
    elif _COLOR.match(s):
        tags.add("color")
    elif _PATH_WIN.match(s) or _PATH_POSIX.match(s):
        tags.add("path")
    return tags


# --- nhận diện ngôn ngữ code --------------------------------------------------------------------
# (trọng số, regex). Điểm = tổng trọng số của các mẫu khớp; cần >= _THRESHOLD.
# 3 = tín hiệu mạnh, 2 = vừa, 1 = yếu.

_THRESHOLD = 3
_M = re.MULTILINE
_MI = re.MULTILINE | re.IGNORECASE


def _p(weight: int, pattern: str, flags: int = _M) -> tuple[int, re.Pattern[str]]:
    return weight, re.compile(pattern, flags)


_LANGS: dict[str, list[tuple[int, re.Pattern[str]]]] = {
    "python": [
        _p(3, r"^\s*def \w+\(.*\)\s*(->\s*[^:]+)?:\s*$"),
        _p(3, r"^\s*class \w+(\(.*\))?:\s*$"),
        _p(2, r"^\s*(?:from [\w.]+ import \S+|import [\w.]+(?: as \w+)?)\s*$"),
        _p(2, r"^\s*(?:if|elif|else|for|while|try|except|finally|with)\b.*:\s*$"),
        _p(2, r"\bself\.\w+"),
        _p(1, r"^\s*print\("),
        _p(1, r"\b(?:None|True|False)\b"),
        _p(2, r"^\s*@\w+(?:\.\w+)*(?:\(.*\))?\s*$"),
        _p(2, r"\bif __name__ == ['\"]__main__['\"]"),
    ],
    "javascript": [
        _p(2, r"\b(?:const|let|var)\s+\w+\s*="),
        _p(2, r"=>"),
        _p(2, r"\bfunction\s*\w*\s*\("),
        _p(2, r"\bconsole\.\w+\("),
        _p(2, r"\brequire\(['\"]|\bimport\s+.*\bfrom\s+['\"]"),
        _p(1, r"\b(?:document|window)\.\w+"),
        _p(1, r"[!=]==\s"),
        _p(2, r"\bexport\s+(?:default|const|function|class)\b"),
    ],
    "typescript": [
        _p(2, r":\s*(?:string|number|boolean|any|void|unknown)\b"),
        _p(3, r"^\s*(?:export\s+)?interface\s+\w+(?:\s+extends\s+\w+)?\s*\{"),
        _p(2, r"^\s*(?:export\s+)?type\s+\w+(?:<.*>)?\s*="),
        _p(1, r"\b(?:readonly|enum)\s+\w+"),
    ],
    "java": [
        _p(3, r"\bpublic\s+(?:final\s+)?class\s+\w+"),
        _p(3, r"\bSystem\.out\.print"),
        _p(3, r"^\s*import\s+java\.[\w.*]+;"),
        _p(2, r"\b(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\]]+\s+\w+\s*\("),
        _p(1, r"@Override"),
    ],
    "csharp": [
        _p(3, r"^\s*using\s+System[\w.]*;"),
        _p(2, r"\bnamespace\s+[\w.]+"),
        _p(2, r"\b(?:public|private|internal)\s+(?:static\s+)?(?:async\s+)?(?:void|string|int|bool|Task)\b"),
        _p(3, r"\bConsole\.Write(?:Line)?\("),
        _p(2, r"\{\s*get;\s*(?:set;)?\s*\}"),
    ],
    "cpp": [
        _p(3, r"\bstd::\w+"),
        _p(3, r"\bcout\s*<<|\bcin\s*>>"),
        _p(3, r"^\s*using\s+namespace\s+\w+;"),
        _p(2, r"\btemplate\s*<"),
    ],
    "c": [
        _p(3, r"^\s*#include\s*[<\"][\w./]+[>\"]"),
        _p(3, r"\bint\s+main\s*\("),
        _p(2, r"\bprintf\s*\("),
        _p(1, r"^\s*#define\s+\w+"),
    ],
    "go": [
        _p(3, r"^\s*package\s+\w+\s*$"),
        _p(3, r"\bfunc\s+(?:\(\w+\s+\*?\w+\)\s*)?\w+\s*\("),
        _p(2, r"\w+\s*:=\s*"),
        _p(2, r"\bfmt\.\w+\("),
        _p(2, r"^\s*import\s+\("),
    ],
    "rust": [
        _p(3, r"\bfn\s+\w+\s*(?:<[^>]*>)?\s*\("),
        _p(2, r"\blet\s+(?:mut\s+)?\w+\s*[:=]"),
        _p(2, r"\bimpl\b.*\{"),
        _p(3, r"\b(?:println|vec|format)!\("),
        _p(2, r"^\s*use\s+\w+(?:::\w+)+"),
        _p(1, r"&mut\b"),
    ],
    "sql": [
        _p(3, r"^\s*select\s+(?:distinct\s+)?\*\s+from\s+\S+", _MI),
        _p(3, r"^\s*select\b.+\bfrom\b.+\b(?:where|join|order\s+by|group\s+by|limit)\b", _MI),
        _p(2, r"^\s*select\s+(?:distinct\s+)?[\w.\"`\[\]()*]+(?:\s*,\s*[\w.\"`\[\]()*]+)*\s+from\s+[\w.\"`\[\]]+", _MI),
        _p(1, r";\s*$"),
        _p(3, r"^\s*(?:insert\s+into|update\s+\w+\s+set|delete\s+from|create\s+(?:table|index|view)|alter\s+table|drop\s+table)\b", _MI),
        _p(1, r"\bwhere\b", _MI),
        _p(1, r"\bjoin\b.+\bon\b", _MI),
        _p(1, r"\b(?:group|order)\s+by\b", _MI),
    ],
    "css": [
        _p(3, r"[\w\-\]\)]\s*\{\s*[\w-]+\s*:\s*[^;{}]+;"),
        _p(2, r"^\s*@(?:media|import|font-face|keyframes)\b"),
    ],
    "powershell": [
        _p(3, r"\b(?:Get|Set|New|Remove|Write|Invoke|Start|Import)-[A-Z]\w+", 0),
        _p(2, r"^\s*\$\w+\s*=", _M),
        _p(2, r"\|\s*(?:ForEach|Where|Select|Sort)-Object"),
        _p(2, r"^\s*param\s*\(", _MI),
    ],
    "bash": [
        _p(2, r"^\s*(?:sudo|apt(?:-get)?|pip|npm|git|docker|chmod|export|mkdir)\s+\S+"),
        _p(3, r"^\s*(?:if|elif)\s+\[.*\]\s*;\s*then"),
        _p(2, r"^\s*(?:fi|done|esac)\s*$"),
        _p(2, r"\$\([^)]*\)"),
        _p(1, r"^\s*echo\s+"),
    ],
    "php": [
        _p(3, r"<\?php"),
        _p(2, r"\$\w+\s*->\s*\w+"),
        _p(2, r"\becho\s+[\"'$]"),
    ],
}

# Khi hòa điểm: ngôn ngữ đặc thù thắng ngôn ngữ chung.
_PRIORITY = ("typescript", "cpp", "csharp", "java", "rust", "go", "php", "powershell", "sql",
             "python", "css", "javascript", "c", "bash")

_SHEBANG = re.compile(r"^#!\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)?)?(\w+)")
_SHEBANG_LANG = {"bash": "bash", "sh": "bash", "zsh": "bash", "python": "python", "python3": "python",
                 "node": "javascript", "pwsh": "powershell", "powershell": "powershell", "php": "php"}
_HTML_TAG = re.compile(
    r"</?(?:html|head|body|div|span|p|a|script|style|ul|ol|li|table|tr|td|h[1-6]|img|br|input|form|button|section|nav)\b[^>]*>",
    re.I,
)
_XML_TAG = re.compile(r"</?[\w:.-]+(?:\s[^<>]*)?/?>")


def _detect_json(s: str) -> bool:
    if len(s) < 7 or len(s) > _MAX_JSON or s[0] not in "{[" or s[-1] not in "}]":
        return False
    try:
        value = json.loads(s)
    except ValueError:
        return False
    return isinstance(value, (dict, list)) and bool(value)


def detect_language(text: str) -> str | None:
    s = text.strip()
    if not s:
        return None
    if _detect_json(s):
        return "json"
    head = s[:_MAX_SCAN]
    m = _SHEBANG.match(head)
    if m and m.group(1).lower() in _SHEBANG_LANG:
        return _SHEBANG_LANG[m.group(1).lower()]
    if head.startswith("<?xml"):
        return "xml"
    if head.lstrip().lower().startswith("<!doctype html") or (
        head.startswith("<") and len(_HTML_TAG.findall(head)) >= 2
    ):
        return "html"
    if (
        head.startswith("<") and head.endswith(">") and len(_XML_TAG.findall(head)) >= 3
    ):
        return "xml"
    scores = {
        lang: sum(w for w, rx in patterns if rx.search(head)) for lang, patterns in _LANGS.items()
    }
    if scores["typescript"]:  # TS là tập cha của JS: tín hiệu JS cũng tính cho TS
        scores["typescript"] += scores["javascript"]
    best = max(scores.values())
    if best < _THRESHOLD:
        return None
    return next(lang for lang in _PRIORITY if scores[lang] == best)


# --- API chính -----------------------------------------------------------------------------------


def kind_of(reps: tuple[Representation, ...]) -> str:
    mimes = {r.mime for r in reps}
    if any(m.startswith("image/") for m in mimes):
        return "image"
    if "text/uri-list" in mimes:
        return "files"
    if mimes & {"text/html", "text/rtf"}:
        return "rich"
    if "text/plain" in mimes:
        return "text"
    return "other"


def category_for(kind: str, tags: frozenset[str] | set[str]) -> str:
    if kind == "image":
        return "image"
    if "url" in tags:
        return "link"
    if "code" in tags:
        return "code"
    if kind in ("text", "rich") and not (set(tags) & {"email", "color", "path"}):
        return "text"
    return "other"


def classify(snapshot: Snapshot) -> Classification:
    reps = snapshot.representations
    kind = kind_of(reps)
    tags: set[str] = set()
    text = text_of(reps)
    if text is not None:
        s = text.strip()
        if s and "\n" not in s and "\r" not in s:
            tags |= _single_line_tags(s)
        if not tags:
            lang = detect_language(text)
            if lang:
                tags |= {"code", TAG_LANG + lang}
    tags.add(TAG_CAT + category_for(kind, tags))
    return Classification(kind, frozenset(tags))
