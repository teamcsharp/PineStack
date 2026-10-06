"""Persist the authorized DGX read-only NAS mount; never read credentials."""
from pathlib import Path
path=Path('/etc/fstab')
source='//10.89.1.125/Downloads'
target='/home/ehm_eckx/pinevoice-stack/spark-agent/data/book_sources'
text=path.read_text()
if not any(line.split()[:2]==[source,target] for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')):
    text+='\n# Pine Box Book Mode: read-only EPUB/PDF library\n'+source+' '+target+' cifs ro,credentials=/etc/exbox.cred,uid=1000,gid=1000,vers=3.0,_netdev,nofail,x-systemd.automount 0 0\n'
    path.write_text(text)
print('Book-share mount persistence is configured')
