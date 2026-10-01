# [pinetab-stamp] THE KIOSK'S BUILD STAMP - sourced by deploy.sh, mirrored by
# desktop/pinetab-stamp.cjs (tests/test_pinetab_stamp.cjs holds the two equal).
#
# What the APK is built from: every file under app/src (the synced shared views
# included) and app/build.gradle.kts. One line per file, sorted bytewise:
#   "<sha1 of its bytes>  <path relative to the repo>"
# and the stamp is the first 12 hex of the sha1 of those lines. It rides the APK
# as versionName 1.0.0+<stamp>, the kiosk says it in its user agent, and the
# desk compares it with what the source would build now.
pine_stamp() {
  ( cd "${1:-.}" && { find app/src -type f -print0; printf '%s\0' app/build.gradle.kts; } \
      | LC_ALL=C sort -z | xargs -0 sha1sum ) | sha1sum | cut -c1-12
}
