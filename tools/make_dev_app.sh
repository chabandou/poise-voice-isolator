#!/usr/bin/env bash
#
# Poise Voice Isolator - macOS dev app bundle
#
# Wraps the Core Audio tap spike in the smallest .app that macOS will treat as a
# TCC client. The spike must not be exercised as a bare CLI: the System Audio
# Recording grant (kTCCServiceAudioCapture) is attributed to the *bundle*, and
# the shipping app is a bundle, so a spike that runs from a terminal is
# measuring Terminal's grant, not Poise's (or being refused outright, because a
# bare executable has no Info.plist to declare the usage string).
#
#   tools/make_dev_app.sh            -> build/PoiseDev.app
#   tools/make_dev_app.sh --deny     -> build/PoiseDeny.app (same binary, no
#                                       usage string, for the denial probe)
#
# Then (LaunchServices launch, so the grant attaches to PoiseDev, not to the
# terminal):
#   open -n -W build/PoiseDev.app --stdout /tmp/out.log --stderr /tmp/err.log \
#        --args --seconds 5 --out /tmp/tone.wav
#
# Bundle ID and code signature: signed ad hoc with a fixed identifier, because
# TCC keys the grant on the code identity. Nothing here needs a Developer ID;
# T12 owns the real signing.
#
# Info.plist key for the grant: NSAudioCaptureUsageDescription. That is the key
# this macOS maps to kTCCServiceAudioCapture (tccd's own service table lists the
# pair; verified on macOS 27.0.1, see measurements/mac-tap-spike.md). It is not
# NSMicrophoneUsageDescription: no microphone is opened on this path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${POISE_BUILD_DIR:-${REPO_DIR}/build}"

app_name="PoiseDev"
bundle_id="dev.poise.spike"
usage_string="Poise records your system audio so it can remove everything that is not speech, then plays the result to your output device."

if [[ "${1:-}" == "--deny" ]]; then
	# The denial probe: an identical app that declares no usage string. If macOS
	# refuses the tap for this one and prompts for the other, the key is load
	# bearing (probe (b)).
	app_name="PoiseDeny"
	bundle_id="dev.poise.spike.deny"
	usage_string=""
fi

app="${BUILD_DIR}/${app_name}.app"
macos_dir="${app}/Contents/MacOS"
plist="${app}/Contents/Info.plist"
binary="${macos_dir}/poise_coreaudio"

echo "==> building the spike"
make -C "${REPO_DIR}/native/poise_coreaudio" >/dev/null

echo "==> ${app}"
rm -rf "${app}"
mkdir -p "${macos_dir}"
cp "${REPO_DIR}/native/poise_coreaudio/poise_coreaudio" "${binary}"

{
	cat <<-EOF
	<?xml version="1.0" encoding="UTF-8"?>
	<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
	<plist version="1.0">
	<dict>
	    <key>CFBundleIdentifier</key>
	    <string>${bundle_id}</string>
	    <key>CFBundleExecutable</key>
	    <string>poise_coreaudio</string>
	    <key>CFBundleName</key>
	    <string>${app_name}</string>
	    <key>CFBundleDisplayName</key>
	    <string>${app_name}</string>
	    <key>CFBundlePackageType</key>
	    <string>APPL</string>
	    <key>CFBundleShortVersionString</key>
	    <string>0.0.0</string>
	    <key>CFBundleVersion</key>
	    <string>0</string>
	    <key>LSMinimumSystemVersion</key>
	    <string>14.2</string>
	    <key>NSHighResolutionCapable</key>
	    <true/>
	    <key>LSUIElement</key>
	    <true/>
	EOF
	if [[ -n "${usage_string}" ]]; then
		cat <<-EOF
		    <key>NSAudioCaptureUsageDescription</key>
		    <string>${usage_string}</string>
		EOF
	fi
	cat <<-EOF
	</dict>
	</plist>
	EOF
} > "${plist}"

plutil -lint "${plist}" >/dev/null

# Ad hoc signature: gives the bundle a stable code identity for TCC without a
# Developer ID. Re-run after any change to the binary or the plist, otherwise
# the signature is stale and TCC may treat the bundle as new.
codesign --force --sign - --identifier "${bundle_id}" "${app}" 2>&1 | sed 's/^/    /'

echo "==> done: ${app}"
echo "    run from the bundle, not the CLI:"
echo "    open -n -W ${app} --stdout /tmp/poise.out --stderr /tmp/poise.err \\"
echo "         --args --seconds 5 --out /tmp/poise.wav --verbose"
