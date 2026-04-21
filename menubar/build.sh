#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

APP="VoiceDictate.app"
BIN="VoiceDictate"
BUNDLE_ID="com.voicedictate.menubar"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -o "$APP/Contents/MacOS/$BIN" VoiceDictateMenu.swift

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>        <string>$BIN</string>
    <key>CFBundleIdentifier</key>        <string>$BUNDLE_ID</string>
    <key>CFBundleName</key>              <string>VoiceDictate</string>
    <key>CFBundleDisplayName</key>       <string>VoiceDictate</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key>           <string>1</string>
    <key>LSUIElement</key>               <true/>
    <key>LSMinimumSystemVersion</key>    <string>12.0</string>
    <key>NSHighResolutionCapable</key>   <true/>
</dict>
</plist>
EOF

echo "Built: $(pwd)/$APP"
echo "Open:  open $(pwd)/$APP"
