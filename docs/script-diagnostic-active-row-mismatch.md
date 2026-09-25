# Script capture: active row versus player file

The open #1287 capture (`data/script_reports/script_2026-09-24_145656_951042401366567914.json`)
reported seven observations as "no captured row names" the observed player
file. In all seven, a different captured row did name that exact file. The
active row instead named another file. The old diagnostic conflated a missing
file row with a script-to-player mapping disagreement.

`script_diagnostics.py` now reports `observed_active_row_mismatch` when the
file belongs to another captured row, with the active and matching row IDs in
bounded evidence. `observed_file_mismatch` remains for an observed file that
no captured row names. This changes diagnosis only; it does not move the live
script mark or claim that a listener heard a line. The #1287 report is still
awaiting its post capture and needs a fresh capture after the script-view work
is deployed to establish whether the display itself is fixed.

At 2026-09-24 22:05 CDT, five consecutive 2-second CDP samples on the
deployed Lenovo tablet each had exactly one highlighted line. Its id matched
the resolver's on-air line, and the resolver's media filename matched that
line's feed row. This checks the current steady-state mapping, not a full
transition or the incident recorder's one-minute window; #1287 remains open
for that capture.
