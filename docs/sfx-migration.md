# Moving the SFX collection from the NAS to a drive on the Spark

*The runbook for the operator. Written 2026-10-06 against the live station; every path and
command below was read off the host that day. Nothing in it has been run yet - the drive has
not arrived.*

> "the hard drive will be arriving and I will be hooking it up to the NAS and transferring the
> SFX collection to the new drive. When I plug it up to the spark, I want the database work to
> continue and for it to plug back up seamlessly into the system and be the new home for clipping
> and SFX clip retrieval. ... In the intermission, I want it playing H3 / Supercuts if it finds it
> has issues getting to the clips or accessing the SFX collection."

## 0. The one fact that makes the switch seamless

A clip's id (`sid`) is `sha1("/samples/samples_grabbed/<folder>/<clip>")[:16]` - the sha1 of the
**absolute path inside the container**. Every store the station keeps about a clip is keyed by
that sid or that path: the clip book (`data/sfx_clips.db`, 433,401 rows today), the vector
section (`data/sfx_vectors`, 3.0 GB of embeddings, tags and transcripts), the plays, the deck,
the 24 h no-repeat book, the bans and weights, the quarantine, the gains, the lengths and levels
ledgers (keyed `path:mtime_ns`), the posters and spectrograms, the levelled copies, the supercut
plans and their cues.

**Keep the container path identical and nothing changes.** The container sees the collection at
`/samples` because `compose.yaml` binds the host directory `/home/ehm_eckx/samples` there
(`- /home/ehm_eckx/samples:/samples:ro`, line 256). Whatever drive ends up mounted at
`/home/ehm_eckx/samples` on the host, with the same `samples_grabbed/<folder>/...` tree inside, is
the same collection to the station: every sid, receipt, cooldown, transcript and supercut plan
stays valid, and the clip book carries straight on. The `--dry-run` of `tools/sfx_rehome.py`
shows what the other road costs; do not take it.

Today's mount (fstab line 5):

```
//exbox.local/quickswap /home/ehm_eckx/samples cifs ro,credentials=/etc/exbox.cred,uid=1000,gid=1000,iocharset=utf8,_netdev,nofail,vers=3.1.1 0 0
```

The NAS is `exbox.local` = 10.89.1.125, share `quickswap`, 1.8 TB, 94 % full. The listener
uploads are a second, read-write CIFS mount of the same share's `samples_grabbed/user` at
`/home/ehm_eckx/quickswap-user` (fstab line 7). The SFX guy's own cuts never go to the NAS: they
are written locally (`data/radio_cache/cuts`, `data/sfx/glued`, `data/sfx/edited`,
`data/samples`) and the H3 renders live in `~/ComfyUI/output/sfx_ads`.

## 1. What happens to the station while the collection is away

Nothing you have to do. With wave E applied (`tools/sfx_reach_patch.py`), the station asks
"is the collection there?" with one stat on its own thread (3 s, one in flight, every 20 s)
and, the moment the answer is no:

- the pipeline log says once: *the SFX collection is unreachable since HH:MM - the intermission
  plays H3 renders and supercuts*; `GET /api/sfx/reach`, `/api/sfx/video/mode`, `/api/sfx/db` and
  the SFX doctor all carry it; the desk's endless-set line leads with **INTERMISSION**;
- the endless set rings the station's own pictures instead of the book - H3 renders and
  everything else ComfyUI rendered on this box, the saved supercuts, the gallery's supercut
  videos - through the same ring, the same cooldown and no-repeat, System 3's die
  `sfx.intermission_pick`; the SFX guy's queued requests wait their turn;
- the stings draw from his own clips (the H3 renders in `sfx_ads`, the glued and edited clips)
  or stand down quietly; `/sfx/<id>` answers 503 at once for a clip of the collection instead of
  hanging on the dead mount;
- the clip book is **kept as it is**: nothing is forgotten, quarantined, reconciled or re-walked
  while the share is away; the walk, the vision pass, the study and the reconcile sweep wait;
- when the share answers again, the set returns to the book on its own and the keepers resume;
  the log says *the SFX collection is back after N min*.

So the switch below can be made with the station on air. The only hard stop is the container
restart in step 5, and `tools/deploy-at-radio-gap.py` waits for a gap to make it.

## 2. Copy the collection to the new drive

### 2a. Format: ext4, labelled

Linux permissions, nanosecond mtimes and no uid/gid games - ext4. Format it **on the Spark**
(or let the NAS format it ext4/Btrfs if that is what it offers; **not** exFAT or NTFS - their
coarse timestamps invalidate the `path:mtime_ns` ledgers and they need uid/gid mount options).
Plug the drive into the Spark, find it, format it, label it `sfx`:

```sh
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL,UUID -e 7      # the new disk has no mountpoint; say /dev/sda
sudo wipefs -a /dev/sda                                    # ONLY the new disk - check the size against lsblk
sudo parted -s /dev/sda mklabel gpt mkpart sfx ext4 1MiB 100%
sudo mkfs.ext4 -L sfx -m 0.5 /dev/sda1                     # -m 0.5: a 2-4 TB drive does not need 5 % reserved
sudo blkid /dev/sda1                                       # write the UUID down
```

### 2b. The copy

Two roads. Either one ends with the same tree on the drive.

**Road A - the Spark copies from the NAS mount it already has (no NAS shell needed).**
Mount the new drive somewhere temporary and rsync from the read-only CIFS mount:

```sh
sudo mkdir -p /mnt/sfx-new
sudo mount /dev/sda1 /mnt/sfx-new
sudo chown 1000:1000 /mnt/sfx-new
# the whole quickswap share, as the container sees it: samples_grabbed (the clips, the renamer's
# _retroname.jsonl, the listener uploads in samples_grabbed/user) and whatever else is used
# off the share (Sample Packs, Music/iTunes is a separate mount)
rsync -a --info=progress2 --no-inc-recursive --chown=1000:1000 \
      /home/ehm_eckx/samples/ /mnt/sfx-new/
```

`-a` keeps modification times (nanosecond precision across CIFS -> ext4 with rsync 3.x), which
keeps the lengths/levels/gains ledgers warm. Expect many hours for 1.7 TB over the LAN; it is
safe to run inside `screen` or `tmux` and to re-run - rsync resumes. The station is reading
the same share at the same time; that is fine, it reads clips one at a time.

Repeat the `rsync` once more at the end for anything that changed (the renamer service keeps
renaming clips; the uploads keep landing).

**Road B - the drive is hooked to the NAS first (as the operator said).** Use the NAS's own
copy (its file manager, or `rsync -a` in its shell) to put `quickswap/` onto the drive **with
the same top-level tree**: `samples_grabbed/` must sit at the root of the drive. Then move the
drive to the Spark. Permissions come out as whatever the NAS wrote; step 3 fixes ownership once
(`chown -R 1000:1000`), which is minutes, not hours.

### 2c. Verify the copy before anything is switched

```sh
cd ~/pinevoice-stack/spark-agent
python3 tools/sfx_rehome.py --verify /mnt/sfx-new
```

It reads the clip book (read-only) and checks the new tree against it: the folders the book
knows that are missing on the drive, the extra folders on the drive, a sample of 200 clips
across the folders (present, same bytes, same mtime), the mount facts (own filesystem? ext4?
read-only?). `PASS` or `WARN` (extra folders are only new material for the next walk) means the
tree is the collection; `FAIL` names what is missing - copy again. `--json` for the whole report.

**Take the baseline first.** Run the same verify against the NAS mount *before* the copy, so you
know what the book already disagrees with. Measured on 2026-10-06 against the NAS (a sample of
60): 59 of 60 clips present with matching bytes and exact mtimes, **1 folder the book knows is
not on the NAS any more** (`samples_grabbed/patrice`, 53,482 rows - renamed or removed on the
NAS side), 1 sampled clip gone (`Rest/E85FE748-...MP4`), and **63 folders on the NAS the book has
never walked** (175 on the share, 112 in the book). So the NAS itself reads `FAIL` today; the
drive should read the same or better - the point of the comparison is that the drive is not
*worse* than the NAS. The 63 unwalked folders are a question for the drop-folder cap, not for
the move.

## 3. Mount the drive where the NAS was

Keep `nofail` (a missing drive must never stop the box booting). `ro` keeps today's contract
(the container bind is read-only anyway); make it `rw` if you want the uploads bind (step 3b) to
write straight into it.

```sh
sudo umount /home/ehm_eckx/samples              # the CIFS mount; the station goes into the intermission here
sudo sed -i.bak-sfx 's#^//exbox.local/quickswap /home/ehm_eckx/samples .*#\# &#' /etc/fstab   # comment the NAS line, keep it
echo 'UUID=<the UUID from blkid> /home/ehm_eckx/samples ext4 defaults,noatime,nofail,x-systemd.device-timeout=10 0 2' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount /home/ehm_eckx/samples
sudo chown -R 1000:1000 /home/ehm_eckx/samples   # Road B only (Road A's rsync already did it)
ls /home/ehm_eckx/samples/samples_grabbed | head
findmnt /home/ehm_eckx/samples                    # must show the drive, fstype ext4
```

Then verify the mounted tree itself: `python3 tools/sfx_rehome.py --verify` (the default ROOT
is `/home/ehm_eckx/samples`).

### 3a. If the drive must live at a different path

Bind-mount it onto the old path, so the container path never changes:

```sh
# the drive at its own home
UUID=<uuid> /mnt/sfx ext4 defaults,noatime,nofail,x-systemd.device-timeout=10 0 2
# and the station's view of it
/mnt/sfx /home/ehm_eckx/samples none bind,nofail,x-systemd.requires-mounts-for=/mnt/sfx 0 0
```

`sudo mount -a`, then `findmnt /home/ehm_eckx/samples` shows the bind. The container still sees
`/samples/samples_grabbed/...`; no sid changes.

### 3b. The read-write question

- **Listener uploads** land in `samples_grabbed/user`, today through the separate rw CIFS mount
  `/home/ehm_eckx/quickswap-user` (fstab line 7). Point that at the new drive with a bind so the
  uploads and the clips stay one tree:
  `/home/ehm_eckx/samples/samples_grabbed/user /home/ehm_eckx/quickswap-user none bind,nofail 0 0`
  (the drive must then be mounted `rw`, and the NAS line for quickswap-user commented out like
  the other). Until you do, uploads keep landing on the NAS and will not be in the drive's tree.
- **The SFX guy's cuts and renders** are local already (`data/...`, `~/ComfyUI/output/sfx_ads`):
  nothing to move. The renamer service that writes `_retroname.jsonl` and renames clips in place
  needs the drive `rw` and must be pointed at the new mount (it is a separate service on the
  NAS side today - check where it runs before unplugging the NAS).
- **The recordings** (`/home/ehm_eckx/pinebox-recordings`, fstab line 8) and the iTunes music
  (line 4) are other shares of the same NAS and are not part of this move.

## 4. The container does not see a mount made under its bind

A Docker bind is resolved when the container is **created** and is `rprivate`: a filesystem
mounted on the host under `/home/ehm_eckx/samples` after `spark-agent` started is **not** visible
inside it - the container keeps the empty directory underneath. That is exactly the state the
station reads as "unreachable" (an empty `samples_grabbed`), so the intermission keeps playing
until the container is restarted. `docker restart` is not enough for a bind that has come adrift
(memory: *docker bind under a later mount*): recreate it.

## 5. The quiet hand-off restart

This is a station restart. Lower the PineTab volume first (restarts blast the tablet), tell
any peer session, then:

```sh
cd ~/pinevoice-stack/spark-agent
python3 tools/deploy-at-radio-gap.py --restart --recreate --seconds 900   # waits up to 15 min for a quiet hand-off, then
                                                                            # docker compose up -d --force-recreate spark-agent
# or, by hand at a gap you can hear:
cd ~/pinevoice-stack && docker compose up -d --force-recreate spark-agent
```

Then, inside a minute:

```sh
KEY=$(docker exec spark-agent printenv SPARK_AGENT_API_KEY)
curl -s -H "Authorization: Bearer $KEY" 'http://127.0.0.1:8096/api/sfx/reach?fresh=1' | python3 -m json.tool | head -30
docker exec spark-agent stat -c '%d %n' /samples /app/data     # two DIFFERENT device numbers = the drive is inside
docker exec spark-agent ls /samples/samples_grabbed | wc -l   # 175 folders today
```

`reachable: true` and the log line *the SFX collection is back after N min* mean the set is
back on the book.

## 6. After the switch: let the book walk the new home

```sh
curl -s -X POST -H "Authorization: Bearer $KEY" http://127.0.0.1:8096/api/sfx/db/rebuild     # a walk, commits per folder, minutes
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8096/api/sfx/db | python3 -m json.tool | head -20
curl -s -X POST -H "Authorization: Bearer $KEY" http://127.0.0.1:8096/api/sfx/doctor/rebuild  # clears the walked-pool caches
curl -s -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d '{"apply": false}' \
     http://127.0.0.1:8096/api/sfx/reconcile    # a LOOK, not a write: what the book thinks is gone/moved/new
curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8096/api/sfx/reconcile | python3 -m json.tool | head -30
```

The walk only adds and updates rows (it never deletes), so a folder that did not copy shows up
as "gone" in the reconcile LOOK - fix the copy before you ever POST `{"apply": true}`. The
vector keeper, the vision keeper and the study carry on exactly where they were, because every
sid is the same.

## 7. The fallback: nothing worked, go back to the NAS

```sh
sudo umount /home/ehm_eckx/samples
sudo sed -i 's#^\# \(//exbox.local/quickswap /home/ehm_eckx/samples .*\)#\1#' /etc/fstab   # uncomment the NAS line
sudo sed -i '/UUID=<uuid> \/home\/ehm_eckx\/samples/d' /etc/fstab                          # drop the drive line
sudo systemctl daemon-reload && sudo mount /home/ehm_eckx/samples
cd ~/pinevoice-stack && docker compose up -d --force-recreate spark-agent                    # at a gap
```

The book was never changed, so the NAS is the collection again the moment the container sees it.

## 8. The road not to take: a different container path

If the drive had to appear at, say, `/mnt/sfx` **inside the container** (a new bind), every sid
of the collection would change. `python3 tools/sfx_rehome.py --dry-run --prefix-from /samples
--prefix-to /mnt/sfx` prints what that costs: the 432,994 book rows that would move and the
sid-keyed stores that would be orphaned (the vector section's 360,533 clips, the plays, the
deck, the no-repeat book, the bans, the quarantine, the gains, the posters and spectrograms, the
levelled copies, the supercut cues). The tool can rewrite the **clip book only**
(`--apply --i-understand-sids-change`, with a backup first, container stopped) - and leaves
everything else behind by design, because rewriting a 3 GB vector section and a dozen ledgers
from a host script is how a station loses a month of the SFX guy's work. Mount at the same path.

## 9. The operator's choices (2026-10-06)

- **Read-write.** The drive is mounted rw: listener uploads (`samples_grabbed/user`), the renamer and future
  cuts live on it. Keep `uid=1000,gid=1000` ownership (`chown -R 1000:1000`) so the container's user writes.
- **Only `samples_grabbed` moves.** The drive carries `samples_grabbed/` at `/home/ehm_eckx/samples/samples_grabbed`
  so every clip path and id stays the same. The station ALSO reads two things off the share outside it, which
  must stay reachable or be copied beside it:
  - `Sample Packs/` (`pixabay scratches`, `lounge - sfx`, `DJ_SAPPO_ROLLING_JUNGLE_&_DnB`) - the DJs' stinger packs
    (app.py SFX_PACKS, ~1038) and the lounge bed (`SFX_ROOT / "Sample Packs" / "lounge - sfx"`).
  - the MX mixtape folder (`mixtape_folder()`, the `{mxtape}` slot) when it is under the share.
  Copy those two folders onto the drive as well (same relative paths), or keep the NAS mounted at another path
  and bind-mount just those folders into `/home/ehm_eckx/samples/` - never leave them dangling.
- **pineEX** does not depend on the share: its supercut versions go to `data/samples/pineEX` (SFX_LOCAL_ROOT).
