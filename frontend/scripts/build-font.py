"""Builds frontend/src/design/fonts/gjurme-serif.woff2, the headline face (ADR-032): Source Serif 4
(OFL, Adobe; the "source-serif" npm package, VAR/SourceSerif4Variable-Roman.ttf), weights 400-700 at
its default optical size, Latin-1 plus the regional letters and the punctuation headlines use.
Renamed "Gjurme Serif", as the OFL asks of a modified version of a font with a reserved name.

    python scripts/build-font.py <SourceSerif4Variable-Roman.ttf> src/design/fonts/gjurme-serif.woff2 400 700

Needs fonttools and brotli."""
import sys
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.subset import Subsetter, Options

src, out, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
font = TTFont(src)
axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in font["fvar"].axes}
print("axes", axes)
limits = {"opsz": axes["opsz"][1], "wght": (lo, hi) if lo != hi else lo}
font = instantiateVariableFont(font, limits)
text = "".join(chr(c) for c in range(0x20, 0x7F)) + "".join(chr(c) for c in range(0xA0, 0x100))
text += "ČčĆćŠšŽžĐđ" + "–—‘’‚“”„«»‹›…·•€−×"
opts = Options()
opts.layout_features = ["kern", "liga", "locl", "ccmp", "mark", "mkmk", "tnum", "lnum"]
opts.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
opts.notdef_outline = True
opts.hinting = False
opts.desubroutinize = True
sub = Subsetter(opts)
sub.populate(text=text)
sub.subset(font)
for rec in font["name"].names:
    if rec.nameID in (1, 4, 16):
        rec.string = "Gjurme Serif"
    elif rec.nameID == 6:
        rec.string = "GjurmeSerif"
    elif rec.nameID == 3:
        rec.string = "GjurmeSerif;subset of Source Serif 4"
font.flavor = "woff2"
font.save(out)
import os
print(out, os.path.getsize(out), "bytes", len(font.getGlyphOrder()), "glyphs")
