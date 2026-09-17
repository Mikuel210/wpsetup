#!/usr/bin/env python3
"""wpsetup mirror patches for a v1 prod bot on escape-pod firmware (2.0.1.6086ep).

Fixes the forever-spinner after entering the PIN:

1. doOta(): the "non-EP firmware" guard read `firmware.indexOf("ep")` where
   `firmware` is the parsed FIRMWARE VERSION string, not the OTA URL
   (`firmwareURL`). On a 6086ep bot that string never contains "ep", so a
   bogus "you are not in recovery mode" alert fired on every run and the
   flow never continued.

2. #btnConnectCloud (Activate): it POSTed to wpsetup.keriganc.com/sessions,
   which returns no Access-Control-Allow-Origin header. A cross-origin read
   from a local mirror is blocked by the browser, so the promise rejected and
   the bot never got the doAnkiAuth() it needs. The prod session token is a
   fixed public value (the same one wire-pod's ble.go sends), so we skip the
   dead network hop and authenticate against the bot directly, with retries.

Note: node on this VM core-dumps on every invocation (that is why the earlier
attempt died, leaving core.* files). This script is pure python3 stdlib.
"""
import os, shutil, sys

P = "/home/soup/wpsetup/js/rts.js"
BAK = P + ".bak"

src = open(P, encoding="utf-8").read()

if not os.path.exists(BAK):
    shutil.copy2(P, BAK)
    print("backup written:", BAK)

PATCHED_MARK = "// [patched]"


def rep(old, new, name):
    global src
    n = src.count(old)
    assert n == 1, f"PATCH {name}: anchor found {n}x, expected 1x"
    src = src.replace(old, new)
    print("patched:", name, flush=True)


# ---------------------------------------------------------------- 1. doOta
rep(
    '  if(_version != 2 && firmware.indexOf("ep") == -1){',
    '  // [patched] check firmwareURL (the OTA url), not `firmware` (the parsed\n'
    '  // firmware-version string); skip when the bot already reports ep firmware.\n'
    '  if(_version != 2 && firmwareURL.indexOf("ep") == -1 && firmware.indexOf("ep") == -1){',
    "doOta-firmwareURL-fix",
)

# ---------------------------------------------------------------- 2. Activate
# Locate the whole click handler by its start and end (it ends at the
# "$(\"#btnFinishSetup\")" handler), so whitespace can't break the anchor.
start = src.index('$("#btnConnectCloud").click(function() {')
end = src.index('$("#btnFinishSetup").click(function() {')
assert end > start, "btnFinishSetup must come after btnConnectCloud"

old_block = src[start:end]
assert 'doCloudLogin' in old_block, "expected the cross-origin login in this block"
assert old_block.count("doAnkiAuth") >= 2, "expected the auth-retry nesting"

new_block = '''$("#btnConnectCloud").click(function() {
  // [patched] prod escape-pod bots authenticate with a fixed public session
  // token (the same one wire-pod's ble.go sends). Upstream first POSTed to
  // wpsetup.keriganc.com/sessions, but that endpoint sends no
  // Access-Control-Allow-Origin, so the browser blocked the cross-origin read
  // and Activate could never proceed from a local mirror. Skip the dead hop
  // and authenticate against the bot directly, with retries.
  setPhase("containerLoading");

  cloudSession.sesionToken = "2vMhFgktH3Jrbemm2WHkfGN";

  var _authTries = 0;
  var _authFail = function(reason) {
    var msg = "Error logging in. The bot is likely unable to communicate with your wire-pod instance. Make sure you followed all of the steps and try again.";
    if(reason) { msg = msg + " (" + reason + ")"; }
    $("#accountErrorLabel").html(msg);
    $("#accountErrorLabel").removeClass("vec-hidden");
    setPhase("containerAccount");
  };

  var _tryAuth = function() {
    rtsHandler.doAnkiAuth(cloudSession.sesionToken).then(function(msg) {
      console.log("anki-auth:", msg);
      if(msg && msg.value && msg.value.success) {
        cloudSession.clientToken = msg.value.clientTokenGuid;

        // adjust default timezone
        let tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        let jqtz = $("#selectTimeZone option[value=\\'" + tz + "\\']");
        jqtz.prop("selected", "selected");

        toggleIcon("iconAccount", true);
        setPhase("containerSettings");
        enableLogPanel();
      } else {
        _authTries++;
        if(_authTries < 3) {
          console.log("anki-auth not successful, retry " + _authTries);
          setTimeout(_tryAuth, 1500);
          return;
        }
        _authFail("bot rejected auth");
      }
    }, function(err) {
      _authTries++;
      if(_authTries < 3) {
        console.log("anki-auth failed, retry " + _authTries, err);
        setTimeout(_tryAuth, 1500);
        return;
      }
      _authFail("no response from bot");
    });
  };
  _tryAuth();
});

'''

src = src[:start] + new_block + src[end:]
print("patched: btnConnectCloud-direct-auth", flush=True)

open(P, "w", encoding="utf-8").write(src)
print(f"OK: wrote {P} ({len(src)} bytes)", flush=True)
print("idempotency check:", "already patched" if PATCHED_MARK in open(BAK).read() else "first run")
