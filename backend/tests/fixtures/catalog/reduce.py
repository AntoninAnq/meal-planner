"""Turn a fetched page into a committable test fixture.

I9 forbids republishing an author's prose. A test fixture is not an exception —
"it's for the tests" is not a licence. So a page is reduced to what the parser
actually reads, and nothing else survives:

  * every <script> goes, except application/ld+json (whose instruction and
    description fields are blanked);
  * markup structure and the attributes selectors use are kept;
  * the text of `recipeInstructions` is replaced by a marker, the elements
    carrying it are kept so step counting stays testable;
  * any text node longer than MAX_PROSE that is not inside an itemprop is
    replaced too — that is where introductions, comments and anecdotes live.

Short template labels survive, which is deliberate: `Durée totale : 55 min` is a
field, and one of the things the extractor must find.
"""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

KEEP_ATTRS = {
    "itemscope", "itemprop", "itemtype", "class", "id", "href", "datetime",
    "content", "type", "lang", "rel", "property",
}
DROP_TAGS = {"script", "style", "svg", "noscript", "iframe", "picture", "source", "img", "link"}
VOID = {"br", "hr", "meta", "input", "img", "link", "source", "col", "area", "base"}
MAX_PROSE = 110
ELIDED = "[élidé — I9]"

JSON_FIELDS = ("recipeInstructions", "description", "articleBody", "text", "reviewBody")

#: Hosts that are part of the DATA, not of the source's identity. Rewriting
#: them would make the fixture test nothing: `schema.org` is what names the
#: vocabulary, and a licence URL is a fact the extractor reads and stores.
KEPT_HOSTS = ("schema.org", "creativecommons.org", "spdx.org", "opendatacommons.org")
PLACEHOLDER_HOST = "exemple.test"
_ABSOLUTE_URL = re.compile(r"(https?://)([a-z0-9.-]+)", re.I)


def _anonymise(text: str, names: tuple[str, ...]) -> str:
    """Remove the source's identity from the fixture.

    Renaming the file alone would be theatre — a single reduced page carried
    195 absolute URLs pointing at its origin. What the fixture is FOR is the
    shape of its markup; who emitted it is deployment configuration and does not
    belong in a public repository.
    """

    def swap(match: re.Match[str]) -> str:
        host = match.group(2)
        if any(host == keep or host.endswith(f".{keep}") for keep in KEPT_HOSTS):
            return match.group(0)
        return f"{match.group(1)}{PLACEHOLDER_HOST}"

    out = _ABSOLUTE_URL.sub(swap, text)
    for name in names:
        out = re.sub(re.escape(name), "exemple", out, flags=re.I)
    return out


def _blank(value: object) -> object:
    """Replace prose, keep shape.

    `recipeInstructions` is usually a LIST, and its length is the step count —
    a fact the extractor reads and I9 does not protect. Collapsing the list to a
    string would remove the author's words and the number at the same time, and
    the fixture would then be unable to test something the pipeline does.
    """
    if isinstance(value, list):
        return [_blank(item) for item in value]
    if isinstance(value, dict):
        return {k: (_blank(v) if k in ("text", "name", "description") else v)
                for k, v in value.items()}
    return ELIDED


def _walk(node: object) -> object:
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if isinstance(node, dict):
        return {k: (_blank(v) if k in JSON_FIELDS else _walk(v)) for k, v in node.items()}
    return node


def _sanitise_jsonld(payload: str) -> str:
    # STRICT parse only. A document that needs repairing is left as text and
    # blanked by regex below: re-serialising it would silently fix the very
    # defect the fixture exists to reproduce (one source's trailing comma).
    try:
        parsed = json.loads(payload.strip())
    except ValueError:
        pass
    else:
        return json.dumps(_walk(parsed), ensure_ascii=False)

    out = payload
    for field in JSON_FIELDS:
        # Blank the value wherever it appears, string or nested array/object,
        # without pretending to parse a document we already know may be invalid.
        out = re.sub(
            rf'("{field}"\s*:\s*)(".*?(?<!\\)"|\[.*?\]|\{{.*?\}})',
            rf'\1"{ELIDED}"',
            out,
            flags=re.S,
        )
    return out


class Reducer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.skip_depth = 0
        self.skipping: str | None = None
        self.jsonld = False
        self.itemprop_depth = 0
        self.elide_depth = 0
        self.stack: list[tuple[str, bool, bool]] = []  # tag, was_itemprop, was_elide

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = {k: (v or "") for k, v in attrs}

        if tag == "script" and "json" in mapping.get("type", ""):
            self.jsonld = True
            self.out.append('<script type="application/ld+json">')
            return
        if tag in DROP_TAGS:
            if tag not in VOID:
                self.skipping = tag
                self.skip_depth = 1
            return
        if self.skipping:
            if tag == self.skipping:
                self.skip_depth += 1
            return

        is_itemprop = "itemprop" in mapping
        is_elide = mapping.get("itemprop") in {"recipeInstructions", "description"}
        if tag not in VOID:
            self.stack.append((tag, is_itemprop, is_elide))
        self.itemprop_depth += is_itemprop
        self.elide_depth += is_elide

        kept = "".join(
            f' {k}="{v}"' if v else f" {k}" for k, v in mapping.items() if k in KEEP_ATTRS
        )
        self.out.append(f"<{tag}{kept}>")

    def handle_endtag(self, tag: str) -> None:
        if self.jsonld and tag == "script":
            self.jsonld = False
            self.out.append("</script>")
            return
        if self.skipping:
            if tag == self.skipping:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skipping = None
            return
        if tag in VOID:
            return
        # Real pages leave <p> and <li> unclosed. Unwinding to find a tag that
        # is not on the stack would close <body> and <html> early, and the
        # fixture would then be truncated exactly where the interesting markup
        # begins. An end tag with no opener is simply dropped.
        if all(name != tag for name, _, _ in self.stack):
            return
        while self.stack:
            name, was_itemprop, was_elide = self.stack.pop()
            self.itemprop_depth -= was_itemprop
            self.elide_depth -= was_elide
            self.out.append(f"</{name}>")
            if name == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.skipping:
            return
        if self.jsonld:
            self.out.append(_sanitise_jsonld(data))
            return
        text = re.sub(r"\s+", " ", data)
        if not text.strip():
            return
        if self.elide_depth or (len(text) > MAX_PROSE and not self.itemprop_depth):
            self.out.append(f" {ELIDED} ")
            return
        self.out.append(text)

    def handle_entityref(self, name: str) -> None:
        if not self.skipping and not self.elide_depth:
            self.out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skipping and not self.elide_depth:
            self.out.append(f"&#{name};")


def reduce_html(html: str) -> str:
    parser = Reducer()
    parser.feed(html)
    parser.close()
    body = "".join(parser.out)
    body = re.sub(r"(\s*\[élidé — I9\]\s*)+", " [élidé — I9] ", body)
    return re.sub(r"[ \t]{2,}", " ", body).strip() + "\n"


if __name__ == "__main__":
    # usage: reduce.py <page.html> <fixture.html> [nom-du-site ...]
    #
    # The trailing names are the strings to scrub — the domain without its TLD,
    # and any variant the page spells out.
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    names = tuple(sys.argv[3:])
    reduced = _anonymise(reduce_html(src.read_text(encoding="utf-8", errors="replace")), names)
    dst.write_text(reduced, encoding="utf-8")
    print(f"{src.name:26} {src.stat().st_size:>8} -> {len(reduced.encode()):>7} octets  {dst}")
