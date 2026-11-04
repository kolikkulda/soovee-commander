#!/bin/bash
# Soovee Commander on the iPhone: a free Apple ID signs an app for 7 days only. This renews it from the Mac:
#   - when the signature has MIN_DAYS or fewer left (or with --now), it takes the last approved commit
#     (tag commander-ios-production) into its own folder (~/soovee_build/commander-ios), so work in progress never
#     reaches the phone,
#   - sets the app's old profiles aside so Xcode fetches a fresh 7-day one,
#   - builds the app and installs it on the iPhone over Wi-Fi; its files, folders and pairings are kept.
#
# Runs twice a day from launchd (scripts/cz.soovee.commander.renew.plist) and from an iPhone shortcut over SSH.
# Prints one line for the shortcut; details go to ~/Library/Logs/soovee-commander-renew.log.
#
#   scripts/obnov.sh            renew if needed
#   scripts/obnov.sh --now      renew now
#   scripts/obnov.sh --status   how many days are left
#   scripts/obnov.sh --approve  mark the current commit as the approved version for the iPhone
#
# --approve copies the approved source, this script and a small Python environment to ~/soovee_build.
# The scheduled run uses only that copy: macOS does not let background jobs read ~/Documents.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG=en_US.UTF-8

APP_ID="cz.soovee.commander.ios"
DEVICE="${SOOVEE_IPHONE:-}"   # empty: the first paired iPhone that devicectl reports
REPO="$(cd -- "$(dirname -- "$0")/.." && pwd)"
WORK="${SOOVEE_BUILD_ROOT:-$HOME/soovee_build}"
SOURCE="$WORK/commander-ios"         # approved commit, copied by --approve
RUNTIME="${SOOVEE_APPLE_RUNTIME:-$WORK/apple-runtime}"
MIN_DAYS="${MIN_DAYS:-2}"
RELEASE_REF="${SOOVEE_COMMANDER_REF:-commander-ios-production}"
LOG="$HOME/Library/Logs/soovee-commander-renew.log"
PROFILES="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
PYTHON="${SOOVEE_PYTHON:-$WORK/venv/bin/python}"

log() { echo "$(date '+%F %T') $*" >>"$LOG"; }
say() {   # the one line for the shortcut, a Mac notification, and the log
    echo "$1"
    log "$1"
    osascript -e "display notification \"$1\" with title \"Soovee Commander na iPhonu\"" >/dev/null 2>&1 || true
}
profile_name() { security cms -D -i "$1" 2>/dev/null | plutil -extract Name raw -o - - 2>/dev/null; }

# Days left on the newest profile Xcode has for the app (-1 when there is none).
days_left() {
    local best=0 f exp t
    shopt -s nullglob
    for f in "$PROFILES"/*.mobileprovision; do
        [ "$(profile_name "$f")" = "iOS Team Provisioning Profile: $APP_ID" ] || continue
        exp=$(security cms -D -i "$f" 2>/dev/null | plutil -extract ExpirationDate raw -o - - 2>/dev/null)
        t=$(date -j -u -f "%Y-%m-%dT%H:%M:%SZ" "$exp" +%s 2>/dev/null) || continue
        [ "$t" -gt "$best" ] && best=$t
    done
    if [ "$best" -eq 0 ]; then echo -1; else echo $(( (best - $(date +%s)) / 86400 )); fi
}
newest_profile() {
    local best="" f
    shopt -s nullglob
    for f in "$PROFILES"/*.mobileprovision; do
        [ "$(profile_name "$f")" = "iOS Team Provisioning Profile: $APP_ID" ] || continue
        if [ -z "$best" ] || [ "$f" -nt "$best" ]; then best="$f"; fi
    done
    echo "$best"
}

left=$(days_left)
case "${1:-}" in
    --status) echo "Podpis Soovee Commanderu platí ještě $left dní."; exit 0 ;;
    --approve)
        commit=$(git -C "$REPO" rev-parse --verify HEAD) || exit 1
        git -C "$REPO" tag -f "$RELEASE_REF" "$commit" >/dev/null
        mkdir -p "$WORK"
        rm -rf "$SOURCE.new" && mkdir -p "$SOURCE.new" && git -C "$REPO" archive "$commit" | tar -x -C "$SOURCE.new" || { echo "Schválení selhalo: kopie zdrojů nejde vytvořit."; exit 1; }
        echo "$commit" >"$SOURCE.new/.approved-commit"
        rm -rf "$SOURCE" && mv "$SOURCE.new" "$SOURCE"
        cp "$SOURCE/scripts/obnov.sh" "$WORK/obnov.sh" && chmod +x "$WORK/obnov.sh"
        if [ ! -x "$WORK/venv/bin/python" ]; then
            /opt/homebrew/bin/python3 -m venv "$WORK/venv" && "$WORK/venv/bin/python" -m pip install -q qrcode pillow || { echo "Schválení selhalo: Python prostředí nejde připravit."; exit 1; }
        fi
        echo "Pro iPhone je schválená verze $(git -C "$REPO" rev-parse --short "$commit")."
        exit 0 ;;
    --now) ;;
    *) if [ "$left" -gt "$MIN_DAYS" ]; then
           echo "Podpis platí ještě $left dní, obnova zatím není potřeba."
           log "platí ještě $left dní, nic se nedělá"
           exit 0
       fi ;;
esac

# Only one renewal at a time (the night run and the shortcut can meet); a lock left by a killed run expires.
mkdir -p "$WORK"
LOCK="$WORK/commander-renew.lock"
find "$LOCK" -maxdepth 0 -mmin +120 -exec rmdir {} \; 2>/dev/null
if ! mkdir "$LOCK" 2>/dev/null; then echo "Obnova už běží."; exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if [ -z "$DEVICE" ]; then
    DEVICE=$(xcrun devicectl list devices 2>/dev/null | awk '/iPhone/ && /physical/ && /available|connected/ {for(i=1;i<=NF;i++) if($i ~ /^[0-9A-F]+-[0-9A-F]+$/){print $i; exit}}')
fi
if [ -z "$DEVICE" ] || ! xcrun devicectl list devices 2>/dev/null | grep "$DEVICE" | grep -qE "available|connected"; then
    say "iPhone není na dosah (musí být doma na Wi-Fi). Podpis platí ještě $left dní."
    exit 1
fi
if [ ! -d "$RUNTIME/iOS" ]; then
    say "Obnova selhala: chybí běhové prostředí Pythonu pro iOS v $RUNTIME."
    exit 1
fi
if [ ! -f "$SOURCE/.approved-commit" ] || [ ! -x "$PYTHON" ]; then
    say "Obnova pozastavena: chybí schválená verze (scripts/obnov.sh --approve). Rozpracovanou verzi nenahraji."
    exit 1
fi
log "obnova: zbývá $left dní, commit $(cat "$SOURCE/.approved-commit")"

# Xcode keeps using a profile that has not run out yet, which would install the same end date again: set the
# app's profiles aside so Xcode asks Apple for a fresh 7-day one, and put them back if that fails.
ASIDE="$WORK/commander-profiles"
mkdir -p "$ASIDE"
shopt -s nullglob
for f in "$PROFILES"/*.mobileprovision; do
    [ "$(profile_name "$f")" = "iOS Team Provisioning Profile: $APP_ID" ] && mv "$f" "$ASIDE/"
done
team=$(security find-identity -v -p codesigning | sed -n 's/.*"Apple Development: .*(\(.*\))"/\1/p' | head -1)
identity=$(security find-identity -v -p codesigning | awk '/Apple Development/ {print $2; exit}')
team_id=$(for f in "$ASIDE"/*.mobileprovision; do security cms -D -i "$f" 2>/dev/null | plutil -extract TeamIdentifier.0 raw -o - - 2>/dev/null; break; done)
team_id="${SOOVEE_TEAM:-${team_id:-$team}}"
if ! "$PYTHON" "$SOURCE/scripts/prepare_apple_signing.py" --team "$team_id" --device "$DEVICE" --output "$WORK/commander-signing" >>"$LOG" 2>&1; then
    mv "$ASIDE"/*.mobileprovision "$PROFILES/" 2>/dev/null
    say "Obnova selhala: Xcode nevydal nový profil (podrobnosti v $LOG). Podpis platí ještě $left dní."
    exit 1
fi
profile=$(newest_profile)
if [ -z "$profile" ]; then
    mv "$ASIDE"/*.mobileprovision "$PROFILES/" 2>/dev/null
    say "Obnova selhala: nový profil se nenašel. Podpis platí ještě $left dní."
    exit 1
fi
rm -f "$ASIDE"/*.mobileprovision

APP_OUT="$WORK/commander-app"
if ! nice -n 10 "$PYTHON" "$SOURCE/scripts/build_apple_clients.py" --platform ios-device --runtime-directory "$RUNTIME" \
        --output "$APP_OUT" --provisioning-profile "$profile" --signing-identity "$identity" >>"$LOG" 2>&1; then
    say "Obnova selhala při sestavení (podrobnosti v $LOG). Podpis platí ještě $left dní."
    exit 1
fi
if ! xcrun devicectl device install app --device "$DEVICE" "$APP_OUT/iOS-device/SooveeCommander.app" >>"$LOG" 2>&1; then
    say "Sestaveno, ale do iPhonu se nenahrálo (je odemčený a na Wi-Fi?). Podpis platí ještě $left dní."
    exit 1
fi
say "Soovee Commander obnoven, podpis platí ještě $(days_left) dní."
