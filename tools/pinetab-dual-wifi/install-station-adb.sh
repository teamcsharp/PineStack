#!/bin/sh
# Isolated arm64 Ubuntu ADB tools; does not touch dpkg's database or locks.
set -eu
runtime="$HOME/.local/share/pinecam-adb"
mkdir -p "$runtime/packages" "$runtime/root"
cd "$runtime/packages"
apt-get download adb android-libbase android-libboringssl android-libcutils android-liblog android-libziparchive
for package in ./*.deb; do dpkg-deb -x "$package" "$runtime/root"; done
LD_LIBRARY_PATH="$runtime/root/usr/lib/aarch64-linux-gnu/android:${LD_LIBRARY_PATH:-}" \
    "$runtime/root/usr/bin/adb" version
