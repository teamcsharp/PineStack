"""Install the exact read-only book mount in the DGX deployment."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
assert str(root)=='/home/ehm_eckx/pinevoice-stack/spark-agent',str(root)
p=root.parent/'compose.yaml';s=p.read_text()
if 'PINE_BOOK_FOLDERS:' not in s:
    s=s.replace('      SEARXNG_URL: http://127.0.0.1:8081','      SEARXNG_URL: http://127.0.0.1:8081\n      PINE_BOOK_FOLDERS: /books/Epub:/books/PDF',1)
if './spark-agent/data/book_sources:/books:ro' not in s:
    s=s.replace('      - ./spark-agent:/app','      - ./spark-agent:/app\n      - ./spark-agent/data/book_sources:/books:ro',1)
shutil.copy2(p,p.with_name('compose.yaml.before-book-mode'))
p.write_text(s)
print('DGX compose has a read-only /books volume and explicit EPUB/PDF roots')
