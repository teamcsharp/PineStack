# Commit log

All 608 commits in order, oldest first, grouped by day. This is the project history as
it was developed, before it was published here; the initial commit and the merge that
attached it are not listed. The narrative that runs through it is in
[HISTORY.md](../HISTORY.md).

## 2026-08-08

- `12ee512` Pine Box agent: current state
- `0cd868c` Pine Box troubleshooter: live diagnosis, printable guide, USB helper
- `6981f43` USB serial bridge and console for Pine Box recovery
- `e03c5ee` USB console UI and a readable port list
- `9e05b3e` Serial port list: only real USB devices
- `679bfa0` DJ say-menu, replay, prev/next by the player, movable panels
- `8c36fd0` Cover flow fills the panel, albums drift behind it, click one for its tracks
- `d45fa46` USB console watches for the box arriving and says why it has not

## 2026-08-09

- `229810c` Close button on the booth popup; announce serialised; silent-speech reasons surfaced
- `7bdff79` Spoken song requests: box hears "play X", station starts, DJ introduces it, track plays
- `3346332` Request memory, banter topic bank, call-ins with web+manual research, square transport buttons
- `052b53a` Remove 19 committed app.py backups; ignore them in future
- `51e27d9` Song requests no longer hijack ordinary questions; word-boundary matching
- `3ae5f7a` Fix 500 on station replies; rebuild the Wyoming connection when announce fails
- `e2a70fb` Rebuild the satellite connection the moment it is found unavailable
- `f859363` #165 click a booth line to have it said again in the right voice
- `f411736` #163 voice call-in from the browser, #166 everything played reaches the DJs, #167 display follows what you play
- `c88d671` Detect that the satellite cannot be told to listen; remove the button that could never work

## 2026-08-14

- `d77274a` Play means play, one clock for every device, and links that stop failing
- `9e60009` #634 an ENGINEER station between the voice and the air
- `0f9e649` The rest of the inbox: other heads, the full mix, and a room that talks back
- `2f135a0` #649 open a picture and make it again, #650 give a guest their own voice
- `355ca69` #651 the cookie button explains itself and takes the file
- `448a6bb` The booth now follows the audio, not the transcript
- `60d4598` #656 the booth keeps the whole night, #657 nothing collapses on its own
- `4a71d16` #659 the setup measures itself and speaks PowerShell, #660 click anything to copy over a plexus
- `5a867c6` #661 cookies are checked for real, #664 long lines scroll, #665 pending shows, #669 studio console, #670 jump to the live line, #673 the switchboard is big
- `dad38e8` #672 the services say what they do, not what port answered
- `fc6317f` #662 the guest button is a toggle, #663/#666 a voice for everyone in the room, #674 lock the pair onto one document
- `7c14e80` #678 a dot that jumps to the live line, #680 what the callers are calling about
- `3e6b3c3` #676 the dice, #677 the booth names who actually spoke, #684 the cohost gets a word in
- `ac66490` #679 the booth's arrow saves the broadcast, not just the voices
- `3a11364` #686 the theme call gets pushed and mined, #687 copying works on a plain-http origin
- `9d863e1` #685 the plexus labels stop colliding
- `d188600` #687 share links point somewhere reachable again
- `bb84e6f` #687 a public listener door on its own port
- `d37bc6a` #687 the public link, carried by Funnel
- `00fa6a8` #689 an ON AIR light in the header, with the switch and the way out
- `8729369` #690 the box was never down; two bugs made it look dead forever

## 2026-08-15

- `26244c6` #689 a finished record no longer masks the silence
- `db412d0` #688 the ad book
- `ab26b28` #681 the sample path becomes a Windows path you can paste
- `9a11fe0` #689 the needle goes down first, #683 an ad bedded on the moment you liked
- `90086f8` Two levels at the top of the listener page
- `7a1fa12` #690 a switched-off box is not a broken box, #691 calls end for a reason you can edit
- `c8b0aa5` #692 the live bar stops printing itself on top of itself
- `d4a9ccd` #693 the SERVER TASK card keeps its contents inside itself
- `5fcbf15` #694 the document lock lists what the show is living in, and lets you read it
- `5a8cd0d` #695 the player keeps its volume, #696 a booth name tells you what made the line
- `3529422` #697 the box switch is yours to keep, #698 the Mind stays in side view
- `4da1d65` Fix the NameError #691 left in the generated-call path
- `dc8ca7b` #689 third cut: the talk runs BESIDE the record, not in front of it
- `3db65db` Torrent mode owns its own talk (#689/#618)
- `c9611de` #700 talk radio that never stops, over records that never stop either
- `da0aa44` #700 the ad bed is levelled against the read instead of blasting over it
- `9b88943` #700 the tape outro and station ID stop running into silence
- `bcd4768` #701 the broadcast mix is levelled too, #702 the torrent stops repeating itself
- `d10c2fa` #704 a bed slider in the Ad Studio, beside the bed you are choosing
- `3f6ab99` #702 pictures on the lines about them, #703/#704 every sample listed and capped
- `226d534` #712 the box could not join the network, #722 turns stopped being cut at 600 chars
- `76a04f6` #705 the booth glass is readable, #708 find a document, #711 the sleeves load, #718 see the guest out
- `e099077` #707 gallery art hangs to the right of the entry, not under it
- `393d914` #712 the stutter was our own repair loop, and #724 the library is cleaned up
- `7a9a335` #728 an up arrow for lines worth keeping
- `7c0c49e` #725 a speech-rate dial, #729 a countdown to the next round, #730 it rolls
- `6d2c129` #726 F5-TTS is a second, swappable cloning engine
- `6df9e50` #733 sign the ad download, #732 play+download on the tile, #737 stop the canvas shrinking
- `9245456` #735 a blocked browser now says so, #738 a sting that cannot reach the box goes to the page
- `8ce433e` #743 an ads desk, #742 the line being spoken is in the list, #741 switching to the box moves the audio, #740 the spectrogram is a fixed fitting
- `9850e16` #752 a unique-dialogue engine at the choke point, #749 the manager upstairs, #745 the panel stops rebuilding the night every 4s, #747 the glass cannot be squeezed
- `2cbf3db` #755 the booth came back blank after being closed — a regression, fixed; #756 speed and pitch per voice; #754 winners are thrilled or crushed
- `028f8ed` ﻿#755 the booth had no dialogue because the log had no HEIGHT — my regression, fixed
- `3c25006` ﻿close three loose ends from the batch: F5 falls back like every other engine, F5 is named in prose, and #707s margin thumbnails are finally attached
- `e3fba4d` ﻿#757 setting the output to the Pine Box did nothing, and nothing said why
- `121d264` ﻿#757 initialize the Pine Box, and a diagnosis that cannot say "nothing is wrong" while a check is failing
- `1fb2727` ﻿#760 five minutes of dead air before the DJs said a word, and #758 audio that went nowhere at all
- `7908dac` ﻿#759 #761 #762 ask the Pine Box about the station and have it fix itself, #757 download anything the booth has audio for
- `f6d6b22` ﻿#764 the stutter was mine, and #763 the gaps get their real fix
- `26ddd0c` ﻿#765 show the picture beside the words selling it, and #763b the pickers tell the truth at once
- `425a074` #770 #772 the booth is the broadcast, in order and 1:1

## 2026-08-16

- `c62c21f` #775 the subject you set owns the air, #776 the stream keeps talking
- `ad57a90` #777 the filters may choose which lines air, not whether the radio does
- `c65fd5e` pine-no-repeats: an hour where a phrase may not come round again, and #778 the booth tells the truth about what is sounding
- `7d5993b` #784 every written line gets on the air, whatever is broken underneath
- `79094eb` #784 a busy satellite is not a dead one - real playout outranks a refused probe
- `7a67350` #782 every line tells you its whole life, and #783 every entry can be taken away

## 2026-08-17

- `1057b20` responsive: every element survives a compressed window, in both layers
- `d3832ac` the deck: the media player is always a media player
- `f539537` #786 nabu is the core, the pair talk more, and the page answers the hand
- `d40b029` #786 mission control, the level columns, and the window that remembers
- `30abdaa` #786 the box cell has a heartbeat
- `f971aea` #786 the drawer fits itself, and the models know their place
- `28dba51` #786 the Voice Director: an engine bench, characters, and a service
- `8ab8ec2` #786 Kokoro live on the host, the gate fixed, and the layout unbroken
- `63449f6` #786 sectionized voice picker, engine:voice routing, DJ controls breathe
- `4c39b64` #787-#792 wake words, the Voice Director service, and the app hears itself
- `927a413` #793 the dead-link ladder — the DJs climb what the operator climbed
- `80813a6` #795 what the triple scan found: the shelf, the calls, the plan race, the range
- `9306d96` #796 the whole machine was wearing ComfyUI's name
- `5c85bca` #797/#798 the observatory, the deck, and XTTS learns to leave the room
- `ea0d059` #799 the status bar — the machine's own ticker tape
- `df05a03` #800/#801 the sample extractor and the terminal grown up
- `77c4f90` #802/#803 the terminal reads like the station's black box
- `d137e7f` #804 size the terminal to the number of entries you want to read
- `90ebb9c` #805/#806 what the resilience scan demanded: calls that complete, a valve, a lifeboat

## 2026-08-18

- `1c45ee3` #808 the sample icon fits its corner and lives in the sidebar too
- `402cbe6` #809 F5 reloads the page
- `9d84bb4` #810 collapsed sections keep their nested headers
- `f7a857b` #811 collapsed gallery and console fold to one-line strips
- `de7253d` #812 the word cloud opens in its own centered window
- `50932db` #813 closing the cloud mid-load no longer throws
- `614c2c8` #814 replies stop playing out of the retired satellite
- `30e2885` #815/#816 crystals, and the vector store stops strangling the show
- `3bd36a4` #817 saved files open in File Explorer
- `89b23f6` #819/#820 the carefree caller, and cast changes take the air NOW
- `0f74e61` #821-#823 audible proof, the sting cache, live model list
- `5f0c70b` #824/#825 the 24-hour no-repeat guarantee, the wandering scour, instant models
- `ff51974` #826 the terminal freezes solid while you read
- `4b7cec3` #827-#829 the machine in front, hosts that react, the crystal lit
- `d0e9ba0` #831 the crystal switch in the corner
- `5c5b407` #832/#833 tags-first lyrics, album minds, and the stings finally fire
- `2f52c9e` #834 crystals tint the SOURCE, not just the instructions
- `43bf30c` #835/#836 the SFX guy finds his voice, and the crystal cabinet opens
- `0941924` #788-#799 the inbox clears: ten requests landed
- `0d140e7` #800-#804 the inbox empties again
- `e36b07d` #806-#808 pine_box.exe, the repeat machine dismantled, saves remember home
- `04bf6fd` #809 the freshness engine: a repeat is never dead air
- `3365b5c` #810 the on-air contract: FM on is audible, FM off is offloaded
- `574ad36` #811 the drowning tails: F5 renders are sentence-bounded now
- `0256c72` #805-#809 the inbox empties a third time
- `97040af` #813-#815 data windows, the mind table, and the DJs' triage tree
- `be135c3` #816 the house that F5 kept selling
- `9fe9e4c` #817 the sting library rotates whole
- `4816b16` #818 the operator's routing is THE default, and switches land NOW
- `cd08318` #819 the clip-length ceiling gets its slider
- `3753efb` #820-#823 the observatory, the tinted cast, cards that own their data, and the end of the gaps
- `05c9ae3` #810-#813 the vanishing cabinet, corner downloads, hawked art, live siphons
- `553847f` #814 the cabinet's minds are a drill-down tree
- `f28a3e4` #824 the render chain joins the triage tree, and F5 is deployable
- `d554f84` #825 every handle the DJs need for XTTS and the director
- `c3f83eb` #826 the sting scan was strangling the event loop
- `c29abbd` #827 the rebuild button becomes unbreakable
- `239ad1c` #828 launch-method-proof: self-sync on boot, agent root that finds home
- `3323700` #830 the booth tells the time the audio keeps
- `1155aaa` #830b the client half lands: slide-in arrivals, standing latest marker
- `56b0890` #819 the ads desk download moves to the corner
- `3d129e7` #831/#832 the audit lands, and the host stops gargling
- `1366143` #833 the tail fade, and skipping a dead engine wakes it
- `c629683` #820-#825 English-only air, the honeycomb tower, every ad hearable, the artist-scoped cabinet, and the monitor
- `0c8b658` #826/#827/#835 the music-player rung, the rescue words, and the idle clock spares a fresh engine

## 2026-08-19

- `5769f43` #836 the ONE BUTTON: Radio Triage popup off the Agent cell, deep repair with the deaf-device rung
- `efcd2aa` #836/#837 the director learns about direct renders, the call-segment download, and the reboot rungs
- `97970a3` #838/#839 the sample forge: video scrubbing, the hexagon loader, self-naming cuts, the batch editor — and the rescue that raises the dead
- `3d89511` #839 the routing rung: the deep repair restores the operator's stamped routing
- `d470257` #840 every booth entry plays and downloads
- `e04ca79` #841 'what happened to the djs' — the DJ rung, and the full reply always plays
- `d3eff79` #842 THE GUARANTEED VOICE — a line always has audio, and no ceiling on what the cast may say
- `03b9c1f` #843/#844/#845/#846 the UMA guard, the GPU load advisor, the booth download, and the host's engine as law
- `f648ea4` #847 the booth download survives a restart
- `8bfce1a` #848/#849 the guard owns the director rung; the cast pickers show the GPU cost
- `47ed432` #850 the two fatal findings from the 41-agent audit
- `c916b44` #851/#852/#853 break the oscillator, wake the watchdogs, watch the floor
- `5139f86` #854 THE DEADLOCK THAT SILENCED THE STATION
- `fc6f50b` #855 the operator's routing becomes sticky — and the rebuild button stops silencing the radio
- `cbd9251` #856/#857 the DJs stop killing the record, and the station repairs itself unasked
- `b798af8` #858-#863 the booth reopens, the desktop calls in, the shares stay mounted, and the stings rotate again
- `02d6b6b` #864 a deaf box cures itself
- `9159882` #865-#868 stop the skipping, one engine resident, whole-moment downloads, and the echo returns
- `3972da0` #869 THE STATION IS LIVE — stale dialogue leaves the shelf
- `4421e99` #870/#871 English, at the last door
- `390c777` #872 booth downloads are instant
- `2493935` #873-#877 the larder finally holds rounds, and the writer stops being the bottleneck
- `7d62408` #878/#879 the looking prompt becomes yours, and the phones become conversations
- `d6877e6` #880/#881 the triage learns
- `87964a9` #882-#885 the SFX guy stops repeating, music streams, and the operator steers
- `2e4f688` #886-#893 audio stacked ahead, one model, and the round finishes
- `23e1af4` #894 (#832/#828/#829/#840) the recording session, the tape cadence, and no mid-track cuts
- `0a2d27d` #895 (#839/#841/#830/#831/#833/#837) quotas that get hit, and pictures that load
- `8269b90` #896 (#835/#834/#838) new samples found, words explained, and the operator's own words survive
- `9c2c430` #897 (#836/#896) the store room, and The Works
- `c0da03d` #898 (#844/#845) the grounding slider becomes a guarantee
- `da91c46` #899/#900 (#842/#843) the DJ Scheduler, the recording room, and prepared ads
- `83a1682` #901 (#846/#847) the records play whole, and the wall only shows what is there
- `6a6836d` #902 (#853) the writing room is briefed on what it is writing
- `73024ba` #903/#904 (#848/#850/#852) the booth stops lying, and everything opens
- `8bcd53c` #905 (#851/#856/#857) two live bugs, a badge the glass never knew, and the buffer's real limiter
- `50835ca` #906 (#858) one person at a time in the recording room
- `6e12f3b` #907 (#854) the case book — calls with a reason, and a temperature
- `631fbbc` #908 (#855) the schedule sends people into the recording room
- `7ace31d` #909/#910 (#859/#863) the boss is never cut off, and the queue folds away
- `52da723` #911 (#861) the writing desk, with the paperwork
- `9e0529f` #912 (#860/#862) the picture gets re-read, and the tint stops fighting the speakbox
- `8c2ee38` #913 (#867/#864) nothing stops the speakbox, and the writing desk opens
- `f203cc0` #914/#915/#916 (#870/#866/#872/#869/#868) the restart stops costing the buffer, and the phones come back
- `905012c` #917/#918/#919 (#878-#882/#871/#865) the recording room gets a door, a slot, and permission to work
- `0ebb822` #920 (#873/#874/#875/#876/#877) the news stops repeating, and the popups behave
- `48d9bd3` #921/#922/#923 the hour beside The Works, drawers that hold still, and a quota that can catch up
- `3d16382` drop a stray scratch file that rode along with #923
- `e321ba1` #924 the segment is called what you called it, and the desk stops lying about being finished
- `1f043e2` #925 the painting and the bulletin get a road

## 2026-08-20

- `9218053` #926 (#890) the hour reads as a row of columns, and the icons sit five pixels clear
- `35e02eb` #927 the itinerary becomes the desk
- `9e4f26e` #928 (#892/#891/#886) every ad is listed, the record can be chosen, and the temperature is the GPU
- `af7d7da` #929-#931 (#883-#896) the horizon rolls, the pantry opens, the box digs deeper
- `3e699ca` #932 a prepared round writes down which clips it is holding
- `f3b8b56` #933 "the works are unreachable" was a lie, and the reason was one word
- `147f593` #934/#935 the hour gets stocked entry by entry, and every tape opens
- `d85d475` #936 the English door stops refusing English
- `f31c08d` #937/#938 the running order is the law, and you can watch it being kept
- `8b8032b` #939/#940 every section plays and keeps; the tile on air lights up
- `11779f5` #941/#942 the coordinator, and callers that get stranger as the queue deepens
- `c6a8bd8` #943 (#941) the four figures at the top of every call, and the dial
- `c0a9ef1` #944 (#911/#912) the coordinator looks ahead, and nothing prepared is wasted
- `d485c70` #945 the director studio, and the prompt book (#917/#914/#910/#909/#897/#906)
- `9448d0d` #946-#949 the deadlock broken, the caller put on the phone, the clip cut true
- `c4543bf` #950 (#904/#900) the marquee, the jump, and what is actually being sold
- `50b2256` #951/#952 the clocks obey the sheet, and the hour stops restarting at entry one
- `38dadba` #953 relief stops the renders, not the writing room
- `0f0cbd6` #954/#955/#956 the news fills its slot, the hour archives, nothing rots
- `1050846` #924-#941 the coordinator schedules, the caller is on the phone, the marquee tells the truth
- `765c353` #971 Pine Box is an application, with a name, a mark, and a pin that works
- `78d1bbe` #972 the pin kept painting the Electron atom, and the icon cache was why
- `1bda9e5` #973 the box moved, and the station stood down for hours because of it
- `0687394` #973b the wire report, and a probe that answers the question it was asked
- `fe212eb` #974 the mark is the badge the app already wears
- `b688b7c` #975 the purge screen becomes a table you can actually work from
- `44a4999` #976 the pine on a box everywhere, and the PB badges go
- `53f32e6` #977 the calls: one line, one caller — and the hour finally counts them
- `20eb7a0` #978 the rooms were backed up, and six measured reasons why
- `453bbb7` #979 Application means all of it, out of the application
- `21b98de` #980 where the audio was, and three dials to move it on the fly
- `61e496e` #981 a volume for each of the three streams
- `c6605a5` #982 the master is the master: the stream sliders stop eating app volume
- `1119a2b` #983 the agent's prompt and the station's are two different prompts
- `a32ee2b` #984 the writing desk says something when it is shut
- `48b9395` #985 ComfyUI was launched with the wrong interpreter, and nothing watched it
- `ba73048` #986 the desk stops writing what cannot be voiced
- `f951e4a` #987/#988 one bad advert jammed eleven, and changing tabs muted the station
- `ecd92ce` #989-#993 the long reads stop being thrown away, and every road gets a turn
- `0020b06` #997 set it to the device and it goes to the device
- `7e08779` #994-#1000 the car link: fewer bytes, and the bytes arrive before they are due
- `610fdf9` #971/#967 the record has a level on the box, and the pickers name the device that is on

## 2026-08-21

- `6f2a547` #974/#973/#964 the recast, the tint, and a reserve you can read
- `fdfbaf7` #963/#962/#969/#970 the grey was arithmetic, the record was silent, the caller was cut off
- `cbd4317` #965/#966 each tile answers for itself, and a ready one says so
- `baf9eca` #972/#959 who is waiting to record, and what just came out of the room
- `38d255d` #977/#976/#960/#979 a tank that is kept, and a horizon that follows the dial
- `18ccbca` #1004/#1003/#1002 the station was deleting the radio it had just made
- `a755adf` #1005 the caller gets recorded too, and the long silences go
- `139170e` #993 the dial on the device stays where you put it
- `f29e88c` #990/#986 the copy button copies, and the hour sheet can find its way home
- `364f358` #1006 a wedged box no longer takes the show down with it
- `a13954a` #991/#985 the picture on the line is the picture being sold
- `ae8bd41` #998 a folder for each topic, and every file about it inside
- `4e6deca` #1007 a repeat joins the request it repeats
- `ebecb79` #1001/#978 the floating panels stopped moving twice
- `69ac7ed` #1000 a call that finishes instead of one that stops
- `b833ccc` #995 the lyrics leave the studio shelf
- `ca35e2f` #987/#992 every banked round can say where it came from, and be rewritten
- `514cce1` #1002 every line in the booth says what it is doing
- `b6c30f8` #999 the conductor says what is wrong and what he is doing about it
- `4a268c7` #999 the conductor's line, where the operator can read it
- `b2f7edf` #994 sixteen dozen knives, one at a time
- `a7b9882` #1007/#1004/#961 the dial has one owner, and the phone rings more than once
- `a543d19` #957/#958/#988 the segment you can see, watch arrive, and hear explained
- `c2a2490` #968/#984 the segment is checked against its own brief, and a corner of the shelf
- `f4a7516` #1005/#946/#947 the painting where you can see it, and a sheet with names on it
- `30ae152` #1005 the picture is bound to the round that is about it
- `46dfe2e` #975 five documents that explain the station to whoever works on it next
- `ad9a933` #1008/#1009 the overlap was a default, and the documents were never gone
- `ac1c074` #1010 one actor, every script
- `afa077d` #1014/#1011/#1012/#1015 the sliders reach the box, tooltips wait, the desk arrives folded
- `0677bbf` #1006/#1016 the tint is a second pass now, and both versions are kept
- `4d2c59a` #980 Glyphy conducts
- `4d93451` #1017 the vault, and nothing leaves the shelf on its own again
- `12aeefd` #1018 the crystal's own words go with every tint, and the popups come back
- `de910c2` #1019 the writing desk shows which calls were tinted, and what the tint did
- `06ac47a` #1020/#1021/#1022 tinting is the form, one turn at a time, and a call says what it was for
- `a89b3a6` #1023 dead air was measured at a device the broadcast was not going to
- `c601b52` #1024/#1025/#1026/#1027 the tint was rewriting a quotation, and reaching almost nobody

## 2026-08-22

- `8a737f1` #1028/#1029 two instruments the box was missing
- `3ee53d2` #1018 the tint never finished a round, and the second prompt is yours now
- `e8810c2` #1030 every listing says who is in it
- `6b56267` #1031-#1036 the tint raps now, and the model was the ceiling all along
- `1506cfd` #1037 verse keeps its lines — the cause underneath every other cause
- `4fe6037` #1038/#1039/#1040/#1041 the crystal reaches every road, and the first pass gets material again
- `e2f40eb` #1042/#1043 the chunk ledger — a cooldown on both shelves, and a window on it
- `44aa1c4` #1044 "source: huggingartists/mf-doom" is not one of the lyrics
- `bcb2ba6` #1045/#1046/#1047 one context size, an honest depth, and a tint that stands down
- `b78229c` #1048/#1049/#1050/#1051 the half-hour desk
- `8cddf04` #1052/#1053/#1054 the repeats cupboard — pre-rolled airtime, kept and reused
- `7b830e5` #1055-#1061 the orchestrator asks, the cupboard keeps, and a read belongs to its record
- `01b01cd` #1062 the callback — "here's a song made by that ad"
- `93d4708` #1063 the tint gets a SHARE, not a threshold — and the brake was on backwards
- `3c05634` #1064/#1065/#1066 the console opens its paperwork, and the whole-round tint was a paraphraser
- `d582e36` #1067 the planner stops picking work the gate will refuse
- `11c05eb` #1068/#1069/#1070 the commitment board — every coming segment decided in advance
- `613d09f` #1071 the question arrives where it cannot be missed
- `d182314` #1072/#1073/#1074 the trail, the arrears, and text that keeps its measure
- `8f00e49` #1075/#1076 nothing is thrown away unheard, a reserve of last resort, and cover_now gets called
- `bbd709d` #1077/#1078 a tinted round was airing de-tinted, and the seed the model never saw
- `9e60f57` #1079 the context pin undone by one line, and the queue the desk could not see
- `771f473` #1080-#1083 the stop-gap, the self-answering question, breathing room, and the surplus
- `2534605` #1084/#1085/#1086 the topics come out, forty-five minutes of warning, and a function I wrote that lied
- `0ef2cc6` #1087 a piper take beats no take, and the ledger learns what one costs
- `cbd111c` #1088 something finally watches the TALK
- `108fd74` #1089 the board counted supply the shelf would refuse, and the cheapest road could not be scheduled
- `1fbe280` #1090 the running order can ask for the cheapest road, and one banter entry becomes a record
- `6bc84c1` #1091 four gates wired to nothing: rows against seconds, a veto counting deleted audio, a decision on a browser poll, and a guarantee inside an except
- `f08300b` #1092 "a fresh one is queued so this does not come round again" was not queuing anything
- `6287c20` #1093 the hour can give airtime back to the records - the only answer to an hour that cannot be made
- `46451f3` #1094/#1095 "protect banter hardest" meant "phone calls never stand down", a desk that could be refused for ever, and a ceiling counting rows with no audio
- `036da2b` #1096 three dials the operator could turn that were not connected
- `9258a31` #1097 the debts left behind by the browser poll, and a ledger that could not pay itself off
- `4ebd608` #1098 the other loop that writes banter never yielded either
- `d79c80f` #1099 the pair stopping work should be visible while it is happening
- `a516cc8` #1100 the yield floor was the stocking target, so the reserve sat just under it and banter never yielded
- `0fbe008` #1101 a gauge pinned at its own ceiling reads exactly like no progress

## 2026-08-23

- `e944b28` #1102/#1103/#1104/#1105 the booth reads like a post, surplus measures the hour, the tint reaches every road and stops running out of money at twenty-five past
- `fba5e2a` docs: the crystal and the orchestrator, and why neither survives the other being starved
- `df354e7` #1106 the room made the audio and the station could not air it
- `97646bb` #1107/#1108 every line the conductor says opens its paperwork, and the station can go off air without stopping the rooms
- `0b6b099` #1109 the piper lane could never be measured, so it was never used - and #1106 had quietly made the hosts eligible for it
- `dc1b61b` desktop: the off-air button in the rail, beside the mark it is not
- `00d716d` #1110/#1111/#1112 the crystal reaches every road, the station's name survives its own tint, and nobody broadcasts into a dead speaker again
- `a67cc2e` fix: I anchored a patch on "function djPower(" and took the async off it, killing the whole panel
- `a1322bd` #1113 OFF meant off for one model out of four
- `81d581e` #1114 the radio stops; the Pine Box keeps answering you
- `9879561` #1115/#1116 paused shut the door on speech and left the records playing
- `89efcd0` #1117 there were three broadcasts, and pause had only stopped one
- `2fca576` #1118 "both" meant two broadcasts, not one show heard in two rooms
- `0e7a9db` #1119 the tint burned sixteen minutes a round, threw it away, paid nothing, and stalled the coordinator doing it
- `5322626` #1120 my own pause gate was destroying the material the pause exists to bank
- `9e353c8` #1121 off air, nothing yields - because there is nothing to yield to
- `6fa6ee5` #1122/#1123 the crystal wiped the round the preparer was building, and one wiped round hid seven good ones
- `56ee1bb` #1124 a station that is not airing is not behind
- `d4842c1` #1125 three hours off air and not one segment written - #1108 opened the door and left the clock reading zero
- `6b9d3c1` #1126/#1127 a bulletin lives three hours, and paused is a silenced booth rather than a silenced station
- `2daec13` #1128/#1129 the news clamp was on the wrong number, and a road with nothing should outrank the ledger

## 2026-08-24

- `62fb445` #1130 off air, the orchestrator drives the numbers the operator watches - and asks before it must be told
- `f755eea` #1131/#1132 the room was idle 54% of the pause, a watchdog pressed the restart button, and two inventories had learned to disagree
- `88763b6` #1133 "pause the radio" and "unpause the radio", spoken to the box

## 2026-08-25

- `301d143` #1134 the panel cried famine over a stocked cupboard, the door refused what the board chose, and the ladder fought the scorecard
- `8be7c9f` #1135 the hour can name the chair - a Studio guest entry interviews whoever is in it
- `9079ee8` #1136 the produced cupboard gets heard, the ads desk walks back sooner, and three deck faults from the full audit
- `35db2d9` #1137 "I want the radio paused" - the polite form moves the switch too
- `7436853` #1138 a paused radio is a silent radio - playback stops the moment the switch flips
- `a7bb110` #1139 "turn off the radio" means OFF - the service ends until it is asked back
- `c74f229` #1140 "start the radio" starts everything that is not started - and repairs nothing that is
- `e7c2c3d` #1141 the cupboard is allowed to be full - and the phone stops writing calls that were dead at the draw

## 2026-08-26

- `a7c447a` #1142 the bookkeeping was strangling the switchboard - four memos give the event loop back to the show
- `7f7c986` #1143 a buffering record is not a drifting record - the panel and shell followers get the #998 guard
- `fa16a29` #1144 pause means silence on the click - the booth obeys the button, and the bridge beats the poll
- `b933e4f` #1145 the state road learns what the clock knew - a pause is not playing, on any poll
- `f734ffd` #1146 the floor, the memo book, and the lesson - conversations air one at a time, the manager's memos are kept for good, and a failed tint no longer kills the call
- `78f4834` #1147 the garble had five mouths - every way two clips could sound at once, closed

## 2026-08-27

- `0ea053e` #1148 the box gets a window - packing the kit is watched, not endured
- `f62cd75` #1149 the road to the car - the public broadcast made smooth, and an inert station made openable
- `4dee819` #1149 addendum - nvidia-smi leaves the loop
- `a0df9d2` #1149 second pass on the ledger - a draw asks, one flusher writes
- `6d5ac11` #1150 the pause stops eating its own larder, and the orchestrator gets a memory and a face

## 2026-08-28

- `5a15a20` #1151 the resume reel - unpause drops finished radio, and the shelf stops burning the unheard
- `0c6d45e` #1152 the comfy doctor - ask what's wrong and watch it get fixed
- `513df27` #1153 the services steward - ask after the stack, and it answers, repairs, and proves it
- `445c905` #1153b the routing selectors, spoken - broadcast to the Nabu, broadcast locally to the app

## 2026-08-30

- `b5b7691` #1154 a command is a sentence, not a cameo - the mystery pauses were the mic hearing the show

## 2026-09-01

- `1b8ef54` #1155 the pause finishes what it wrote, and talk radio keeps the records turning

## 2026-09-02

- `659c741` #1156 the pulse names the blocker, records ride the local shelf, and a box with no firmware gets routed around

## 2026-09-04

- `3110f64` #1019 the Gazette - a newspaper printed on the hour off the station's own log, and the 📰 beside the cloud

## 2026-09-05

- `99b7f11` #1020-#1043 the Gazette becomes a paper, the station learns to listen, and the dead air gets measured
- `21481e9` #1044-#1050 the paper gets real pages, a PDF writer, a screenplay and a slideshow
- `e0c15e6` #1051-#1053 the paper announces itself, the store room reads by age, and the crystal dial does something

## 2026-09-06

- `5ab10cc` #1045-#1061, #1063 the paper reads its pictures, the LCD joins the desk, and the tint yields to the air
- `460f7ee` #1062, #1063 new samples get half the draws, and a recorded line airs
- `78d0d39` #1064 the universe rhymes - every line a bar while a crystal is on
- `3ba3fb7` #1064 the hold is the rule: meaning grade, every road, one ask per round
- `2cf25b9` #1064 the meta filter learns the retry prompts, and a call retry asks for a bar
- `e340073` #1064 the cut before the studio - a line that will not rap is cut, the bars are the round
- `6c2992d` #1065, #1066 the masthead follows the name, and a caller's pivots enter the story
- `3023fe2` #1064 every line rhymes - the rap-aware rhyme reading is mandatory
- `29b11f7` #1064 saved progress that fails the grade in force is asked for whole again
- `3b213c0` #1064 progress graded under an older evaluator is not resumed - the round is asked whole
- `9bc0581` #1064 no plain stopgap under a crystal, fresh rounds before legacy repair, and the LCD cupboard view
- `4cea863` #1064 audit: the world rides the whole-round prompt, the paper tints under the hold, the pair keeps the deep model, unrhymed tagged responses never serve
- `cc62fc8` #1064 audit: the round tint deadline is sized per model and per ask
- `9d437ec` #1064 audit: the closing section
- `4b49598` #1064 reading the LCD: the rap reading is the only rhyme evidence, every road deep under the hold, a dropped g keeps a name, the cupboard shows bars as they land (evaluator v4)
- `a21b96a` #1064 reading the LCD: a hard bar keeps a fifth of the content words, a speaker label is not a bar, no tint budget under the hold; three quarters of sting draws go to fresh samples
- `b974458` Gold bars fire again with a sting, spoken destinations know the device and the computer, spelled-out numbers keep the numbers
- `db2b181` #1064 the refused bars are re-asked together, old rounds are aligned not refused, a plain re-air is held, a sting rides the record
- `4a518e9` docs: #1064 section 16 - when the hold starves the air
- `fb1f584` #1064 a stale speaker-order verdict is re-audited by the aligner at boot; "pause the radio playback" is a command
- `c945a14` #1064 four quiet minutes open the live writer at 100% talk; the batched re-ask names the words to keep and reads a run-on answer

## 2026-09-07

- `391f583` #1064 rounds first on the tint lane: a single-line ask yields to a waiting round, the legacy repair waits while the lane is deep, resumed progress is re-asked together
- `1789570` #1062 the sting over the record waits out a voice and says why it skipped; one starved live round at a time
- `5e0575b` #1064 the floor is lent out while a line waits on the tint lane - rounds and stings no longer queue behind an advert's rewrite
- `b22edf7` tests: the record sting test pins the last-spoke clock
- `5158877` #1156 the hold drain stands down while the box firmware is down; the state names who holds the air floor
- `02ab87c` #1156 every road routes around a firmware-down box and the page carries the line; the floor hold names its stage
- `c94b57e` #1156 a firmware-down box declines at once at the one door every clip takes; a page delivery counts as air for the starvation clock
- `c427a5f` #1064 the single-line write runs with the floor lent out - the floor is for the render and the play
- `613fc51` docs: 16.1 the floor, the dead box, rounds first

## 2026-09-08

- `2d2cc97` #1068 #1069 #1070 System2 drives the station; the rhyme lookup leaves the loop; no line twice inside an hou
- `80f7849` #1069 #1070 System2 refresh does less: one decode of the drafts per hour, a minute between plans, no copy for the status poll
- `ab330ec` docs: #1070 the numbers after the fourth restart
- `0e5b5fd` #1071 the Gazette asks the fast model's own tint lane and says why a paragraph stayed plain
- `d7f016a` #1071 the Gazette tints two stories at a time in a twenty-minute window
- `3dea666` #1077 #1075 no Gazette edition goes out untinted
- `92806b5` #1072 #1073 #1074 every 3JS scene in its own window, a Scheduler tile, and System2's four mechanical faults
- `4fdc2e6` #1075 #1076 #1077 #1078 clock times and 'PM' no longer refuse a bar, no phantom refusals, a print register for the Gazette, the learner can explore
- `32ed076` #1079 #1080 #1081 #1082 the request book, two lanes and the schedule's permit, one cacheable prefix, the strike cap and the fault memo
- `fa18a01` #1083 #1084 #1085 #1086 #1087 two System2 sittings, the stanzas held for the prefix, the recreation guide
- `96ae057` #1088 rejection notices: machine-handled refusals are notes, only a cut is pending
- `f3fc286` #1076 #1082 the evaluator reconciliation: the audited false refusals fixed rule by rule, every pinned fidelity rule kept
- `7bee4c4` docs: the hour and the cupboard fill rate; the tint gate is a queue, not a refusal loop
- `49359cf` docs: the cupboard fill rate - the first reading after the gate became a queue
- `1be0aa5` the rejections census, the 96-hour repertoire, the gap filler and the LCD that shows what is said
- `79dbcc6` the retirement desk - nothing rhymed leaves the cupboard without the operator's answer
- `2d12e5a` rapping 24/7 - the operator's own hand approves, the orchestrator reflects, gold bars fill the air
- `682253b` the rejections read in full - five more cuts at their cause
- `2db8e4f` RapAssembly - the assembly line written down, and drawn live
- `424ea21` The evening's rejections: what the queue was, and what the orchestrator now folds
- `5da539a` The deep scan: the readers stop refusing rhymes, the queue drains itself, the lane stops being wasted
- `c4b9d9d` The dials the scan asked for, and the rapped calls that were held by a stale verdict
- `e616ed8` The crystal's own rhymes, the deep bank spent first, and calls that finish

## 2026-09-09

- `48eb978` #1157 a rhymed line is not deleted, and the bank fills the air
- `18cb8f2` The rejection queue read row by row: four false refusals closed, one panel lie
- `5f152b2` A line held in the review queue tells the truth about why

## 2026-09-10

- `45b6af0` The hour on paper, the room that reads it, and the passage the pair answer
- `0298ef4` The script desk: an edit is a training pair, and kept material is not writable
- `fe1a79b` The writers room: a shape, a fork, a lesson, and an hour that fits the engine
- `3cda4c4` The script comes to you: a pulsing queue, a line you can tint by hand, and a way past the tint
- `6bdecb1` The rhyme lane: one ask for a whole script, and a smoke alarm where the grader was
- `145cf98` The talk yields to the record: an unbounded await stopped the music for 21 minutes
- `72e9d3f` Retention for three stores that had none, and a hot read off a contended lock
- `5ee0ea8` The banned list is not checked sixty times a second
- `89598f3` A schedule change must not be able to throw the cupboard away
- `5825862` A dead lease is not an active performance: thirteen corpses had stopped the orchestrator planning
- `74b7e6a` A record may play fully; it may not own the hour
- `7984f31` The script reads like a script, and a note sends it back to the writing room
- `4fd5d45` Why is this line playing: the whole chain, from the clip back to the prompt
- `5cebd2a` Dead air opens the cupboard, not the sting tin
- `efc12c8` The conductor gets a stage, and the cupboard stops lying about how full it is
- `e4fe439` The Gazette's Copy button was fixed twice, both times in the wrong window
- `dbb817c` The mark says whether it needs pressing, and the rebuild clears the cache it was skipping
- `1efe077` The Gazette set to publishing rules, and the paper collected as one plate
- `16ccf8b` A storyline that comes round again, and one that cannot empty the cupboard
- `0113dac` A topic may go any of twelve ways
- `daea24f` The entry on air gets first refusal, and the intercom cuts in
- `66047e8` The cupboard is tried before the emergency host
- `6fa6c6f` Where the work lives, and which doors open
- `918356b` An entry runs until its minutes are used, and a segment may run past the fold
- `6614711` The Gazette window shows the show as well as the paper
- `c9549c1` The rescue could never open the door it was given the key to
- `fc3f564` The orchestrator was banking against a pile it could not see
- `686c8e2` A road whose rounds are one line still has rounds
- `ab50e44` Eighty-eight recorded phone calls, and one word refusing all of them
- `9903d90` A road that cooks into a bin
- `2e2c335` The crystal is not evidence that the segment failed
- `8992dae` The memo is about them, the painting gets sold, and the round reads more than one document
- `e1a949f` Twenty-eight lines carrying a fifth of the air
- `886cc1e` A draw of one is not a draw
- `32fec7d` The rest of the randomness audit
- `d7d5859` A standing answer you cannot take back
- `2e0d5e9` "The hour on air" was whichever hour came first in the list

## 2026-09-11

- `12f3303` A round nobody has heard does not expire
- `830769d` An answer the station cannot carry out is not an answer
- `5bd976f` The orchestrator only asks what it can act on
- `1b2a6bd` The air follows the device, and an entry answers for its own road
- `67adf1d` The play switch decides who may hold the air, and an open entry reaches the cupboard
- `fab2c11` The orchestrator gets a lever on the air, and the manager is heard
- `f5508af` A document already mined goes down the list
- `62d9f5b` Cupboard View, and a phrase the station keeps saying
- `15986ba` Worn rounds go up for debate, not in the bin
- `e3f840d` The standing order reaches the writer, and airings are read off the row
- `30360d5` A sting has to be long enough and loud enough to hear
- `ef513bc` A rung for the page, and a line that knows where it sits in its script
- `9525593` The wedge detector read the wrong clock, and nobody rang it
- `0fc8f98` The station says when it is stuck, and offers to unstick itself
- `d7bad17` The SFX desk: hear it, then bin it
- `37cd3a8` The broadcast that could not let go, and the windows it cut by guesswork

## 2026-09-12

- `f1efaaf` The pause that never lifted, and the surface that lied about it
- `5007a06` The restart rail, and an orchestrator that works the silence instead of watching it
- `34c4ef2` A voice clip crosses the stalling loop once, and the ladder learns to measure
- `f8afa3d` One check re-read a file per line, and the loop froze 16% of the show
- `9d13df2` The one rung that can actually help a congested loop
- `ce53512` The line that was read 385 lines before it was written
- `c4c9e53` A 625 MB JSON parse on the event loop, once per restart
- `b2d353f` The debt paid to the road that earned it, and the binding shown
- `65c1ebe` The chronicle: ten eras, 489 commits, and the notes underneath them
- `3f383d6` The clock was deep-copying a whole slot, many times a second
- `aa73ba9` The topic bank was exhausted, so the station cooks its own
- `91b42e7` An hour's unheard work was locked out of the next hour
- `7db4b27` A purity test that was a coin flip, and the census that found it
- `721ef50` The SFX Guy gets a dial, a voice in the silence, and the topics board
- `8afd565` A record playing is not the SFX Guy's problem
- `cbc58bd` Taking a reservation copied the whole ledger to change one row
- `79340d1` Who actually took the entry's window, and a grace period that ends
- `623b6ae` And the stock count must still be what would go out
- `8157013` The three modules app.py imports and the repository did not have
- `9a5368d` The desktop app: 49 files the tracked index.html already asked for
- `ae4ed79` Tests, tools, stylesheets and notes that were never tracked
- `459d365` The Library's PDF reader, the craft prompts, and the eight phrases
- `4af5e69` The transcriber, and HEAD finally matches the file that is running
- `80165ad` The station's working repository and its published one, made one
- `b222931` The repair button triangulates: the tablet was gagged, not broken
- `c4e30e2` The tablet's timers were frozen, and the air stayed with its ghost
- `5740d16` The draw walked 7,180 clips twice every three seconds
- `1060d8a` The topic said out loud, and the manager bringing one downstairs
- `db44a9a` The SFX Guy gets his own watch, the joins, and a gate that let him work
- `b38014c` A watchdog that awaits the thing it watches is not a watchdog
- `c4d3c7d` The popups answer in a quarter second, and the slideshow reaches the tablet
- `b7cf20d` The speakbox walked the share on the event loop, once per document
- `b0730cf` The sampler keeps the last two minutes of air, and a pad can be cleared, tuned or carried away in a kit
- `f1812dc` Every clip is allowed, and the draw goes round all of them
- `4c52926` The clip-length dial had no door, so lifting the ceiling changed nothing
- `7518fae` A playhead across the sampler, a kit an MPC can open, and a take you can widen after the fact
- `e141a0c` The slideshow stops sending 3.7 MB pictures, the desk answers under the thumb, and Listen grows a grab pad
- `51564f2` The music ducks for anything that talks, a pad silences the radio outright, and three taps keep the last two lines
- `7356dcd` A skipped book was never settled, so the shelf read it for ever
- `ce8bafc` The sampler opens the way you left it, the records join the feed, and a carried row is a tile
- `6374888` The MPC's card opens on the tablet, and a kit on it loads back onto the pads
- `4353b84` Two voices were doing 65% of the callers
- `753925f` A pad grab takes the voices, not the room - and nothing was ever recorded twice
- `28fa594` One record in the feed, and the line on air goes back above it
- `7465e36` The stream was in order; the document describing it was not
- `392d73f` The script's own sequence decides, not a timestamp
- `ec52a41` Double-tap the script and read it properly
- `dd4c895` A pause is when to build hardest, and a script you can actually read
- `898f15e` The sampler gets a face: a gallery backdrop, waveforms on the pads, three knobs and an edit sheet
- `5acac67` The recap entry had never once been filled
- `d4e1e35` The sampler tab opens again, and the pad grid cannot be squeezed out by the next child
- `de41a05` Only one line is being said, so only one may be marked
- `f90a55d` The reel airs a conversation that has no name, so the script cannot place it
- `e2e09a3` An interjection is not a change of scene
- `a689a69` Hold a line on any script screen, and it offers to play it as well
- `072a422` The desktop follows the share while it runs, and the staleness mark stops lying
- `8b2e528` The highlight kept its own clock, and its own clock was always behind
- `3b587dc` The reading does not end because the hour did
- `fdaedd7` The sampler feed keeps its rows, so you can scroll back and grab what just played
- `7e0d280` A mark that did not happen is not remembered
- `91eb43c` And the page goes and gets the line it cannot find
- `0b7c33b` +5 steps the feed back five entries at a time, because scrolling to them was not realistic
- `06083c6` A single tap does nothing, and that is the point
- `cee4d92` Three buttons that reach the tablet's glass, and a window to draw on what they bring back
- `13acca9` The script is kept, not rebuilt
- `2237803` The clip gets sound, an export dialog to cut and mix it, and Asked-for folds away
- `6ae5561` A conversation is anchored on the one stamp that is never rewritten
- `c618367` The feed stops being cut off, and the picture follows the trim handles
- `cb83d02` One line, one clip, one measured window
- `69b9bbb` Notices can be switched off per screen, and Later means the orchestrator takes it
- `6f16e24` The three chunkers are one chunker, or the bank misses
- `f49db75` The capture buttons follow whichever device is mapped, and x264 stops refusing odd windows
- `6ec5986` The line menu closes when you press it, and each choice wears a mark
- `0abc1fe` Carbon icons, not emoji
- `78a732a` The terminal finds the station from outside the house
- `5586bd7` The hour that is over is fetched once, not on every poll
- `16b4bcd` The player knows where it is. Ask it, not a clock.
- `38b5dbd` The feed marks the line that is sounding, and its rows stop lying
- `4448e48` DGX Terminal: a shell on the Spark, and the three bugs between here and typing
- `48327f3` One timeline, computed once, served to every surface
- `2a3f9c5` Restore app.py: the previous commit captured a half-written file
- `d358101` One timeline computed once, and a line named before it is spoken
- `1f4ca5c` The cupboard is heard, the memo gets through, and the sheet is measured
- `625f1f5` Segments that fold, names that do not move, and a feed with a memory
- `48a3486` The blank moment was the sample library being walked on the air path
- `a5faa2d` Restore the parallel session's #1277 and re-apply the sample index on top
- `7310512` Stop asking expensive questions at a rate nothing needs
- `80f3f65` Match the file that is sounding, and stop the feed's treadmill
- `0935c00` A line that has been heard sounded when it sounded
- `168caf4` Commit the working tree so HEAD matches the container
- `ee6e8f8` The command is performed where you chose it, and two bugs it uncovered
- `2ad822e` The feed's memory must not cost the loop anything
- `ac17970` Recap can air, recap knows what was discussed, and the mark stops dragging the page
- `3029e45` Reading the settings must not wait behind writing them
- `ea9ec84` The script reads one to one, and the readers stop blocking the air
- `a058b61` The clip lands where it happened, and the hand-off is shown
- `432b8eb` #1300b the heading answered the question before its members asked it
- `83c2d08` Silence outranks the interval, and the clips library answers dead air
- `c7a5b3c` The door says why, the meters share the graph, and a video on the thumb
- `0ac6a23` The screenshot knows what is in it, and the marks are sized for the picture
- `01e78b5` A webcam icon on the desk, and the annotation defaults stop lying about size
- `6eea0d9` The lineage gets a chart, and the whole round is one parameter away
- `2b1b6d8` The video actually plays: a cue road, a set that is seen, a clip that loads
- `5a80b2c` The camera gets a window of its own, streamed from the tablet
- `66ff56a` A line nobody heard stops standing in front of the ones they did
- `f01137d` A pad that holds a video pops the video
- `e3039a2` Clean then fill then enlarge, a door ComfyUI can find, and a countdown
- `e5cbda2` Stopping gives a shorter clip, and the export says what colour it is
- `d7265a6` The picture waits for the seek, and "not running" stops being a guess
- `98dd232` The video button was working, refusing, and saying so where nobody could see

## 2026-09-13

- `f322f7d` Every chunk opens up, says whether it reached the prompt, and can be cut
- `c986558` A swath is cut by its lines, and the X now reaches every draw road
- `43058ea` The picture could not be fetched because the pictures before it never let go
- `5d36e39` Right-click any line anywhere, and inspect it in conversational context
- `97c2918` Change the line from the window you inspected it in
- `78547d0` Silence loses: the rescue stops asking the floor for permission
- `06a6bc6` Long-press any line on the tablet, and inspect it there
- `ee2984f` There was already an inspect:play, and two of them stop the app booting
- `51f62b8` The terminal's deaf-watch, mirrored into the renderer
- `0f63631` A leading slash meant the disk, and a timeout now says what to do about it
- `2aecf6e` The script is written down before it is heard, and the chrome can finally hear the panel
- `7f09076` One tap now reaches every cure the station owns, and RELEASE finally runs
- `737dc59` The out-loud switch is a cure too, and the ladder now counts to twelve
- `8b065ab` Two different gags wore the same word, and RELEASE stopped asking permission
- `4158184` A script is read downwards, and an owner that takes nothing loses the air
- `f91a38d` Sixty seconds, because at thirty the gagged light came on with the station audible
- `c1c0129` The ladder could not reach its own rung nine, and ON AIR never touched the switch
- `9ad5442` Pick who sees the camera, and say which microphone you are using
- `9ce0129` A still, a clip, and the camera taking the gallery's place
- `302c0dd` The ARP table was full, so the radio could never finish a handshake
- `6864b50` The clip doctor, a heal button for the camera, and the orb's two broken roads
- `8132291` The panel did not parse, so nobody heard the DJs; the loop taken off its knees
- `1bdafb2` Twenty inbox items closed: the buttons the agent's roads lacked, and three things nobody had built
- `93e6a63` Profiled, not guessed: a failed import per request, a lock under the loop, and the set rung ahead
- `b8b68f6` The station stuttered: the store's save starved the disk, and the tablet was animating under a view nobody could see
- `e3ba6c6` The tablet's frame pipeline, the tailnet gallery's hand-back, and an SFX slider
- `624ab0b` In endless mode the tube belongs to the cycle: the SFX guy's clip plays after, never over
- `9e5e3ee` The audio graph that grew a node per clip, a mixer dot on the player card, and the heap frozen every quarter hour
