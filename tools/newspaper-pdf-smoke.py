"""Inspect downloaded actual PDF output without publishing or changing the station."""
import json
from pathlib import Path
import sys

import pymupdf

folder = Path(sys.argv[1])
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
report = []
for style in ('broadsheet', 'tabloid'):
    doc = pymupdf.open(folder / (style + '.pdf'))
    escaped = []
    fonts = set()
    for i, page in enumerate(doc):
        fonts.update(font[3] for font in page.get_fonts())
        for block in page.get_text('blocks'):
            if block[0] < -1 or block[1] < -1 or block[2] > page.rect.width + 1 or block[3] > page.rect.height + 1:
                escaped.append(i + 1)
    report.append({'style': style, 'pages': len(doc),
                   'size_mm': [round(doc[0].rect.width * 25.4 / 72, 2), round(doc[0].rect.height * 25.4 / 72, 2)],
                   'out_of_page_text': escaped, 'embedded_blackletter': any('Unifraktur' in name for name in fonts)})
    assert not escaped, report[-1]
    if style == 'broadsheet':
        assert report[-1]['embedded_blackletter']
    for index, name in [(0, 'front'), (1, 'inside')]:
        doc[index].get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(output / (style + '-' + name + '.png'))
(output / 'pdf-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
