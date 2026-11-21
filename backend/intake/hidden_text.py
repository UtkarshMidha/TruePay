"""L1: hidden-text scan. A char is hidden if its fill is white or its size is below 3 pt (PRD §11)."""
from collections import defaultdict

import pdfplumber

WHITE = {(1,), (1, 1, 1), (0, 0, 0, 0)}


def _is_hidden(ch) -> bool:
    col = ch.get("non_stroking_color")
    col = tuple(float(x) for x in col) if isinstance(col, (list, tuple)) else ((float(col),) if col is not None else None)
    return col in WHITE or ch.get("size", 12) < 3


def scan(pdf_path) -> dict:
    """-> {text (all chars, untrusted), spans [{text,page,x0,top,x1,bottom}], page_size {w,h}}"""
    spans, texts = [], []
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_size = {"w": float(pdf.pages[0].width), "h": float(pdf.pages[0].height)}
        for pno, page in enumerate(pdf.pages, start=1):
            texts.append(page.extract_text() or "")
            lines = defaultdict(list)
            for ch in page.chars:
                if _is_hidden(ch):
                    lines[round(ch["top"])].append(ch)
            for top in sorted(lines):
                chs = sorted(lines[top], key=lambda c: c["x0"])
                spans.append({"text": "".join(c["text"] for c in chs), "page": pno,
                              "x0": min(c["x0"] for c in chs), "top": min(c["top"] for c in chs),
                              "x1": max(c["x1"] for c in chs), "bottom": max(c["bottom"] for c in chs)})
    # merge consecutive lines of the same block into one span (UI shows one red panel per block)
    merged = []
    for s in spans:
        if merged and s["page"] == merged[-1]["page"] and s["top"] - merged[-1]["bottom"] < 3:
            m = merged[-1]
            m.update(text=m["text"] + " " + s["text"], x0=min(m["x0"], s["x0"]), x1=max(m["x1"], s["x1"]), bottom=s["bottom"])
        else:
            merged.append(dict(s))
    return {"text": "\n".join(texts), "spans": merged, "page_size": page_size}
