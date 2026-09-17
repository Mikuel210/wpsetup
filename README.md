# wpsetup patched for escapepod firmware

> [!NOTE]
> Vibepatched by Hermes, I haven't reviewed the code but works on my machine

Self-hosted mirror of [wpsetup.keriganc.com](https://wpsetup.keriganc.com) —
the web-based Vector setup tool for [wire-pod](https://github.com/kercre123/wire-pod).
Needed because Web Bluetooth requires a secure context, and because the hosted
site has two bugs that stall a v1 production bot already running escape-pod
firmware (`2.0.1.6086ep`).

The site tree (`html/`, `js/`, `css/`, `images/`) is the deployed site as
served by keriganc, with the patches below applied to `js/rts.js`.

## Running

```bash
python3 server.py
# → https://<this-host>:8444/html/main.html  (LAN or tailscale address of the machine)
#    http://<this-host>:8081  → 301 to https
```

Managed by pm2 as `wpsetup`:

```bash
pm2 logs wpsetup     # watch
pm2 restart wpsetup  # after editing files
```

The TLS material is not committed — generate it for your own host:

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout cert/wpsetup.key -out cert/wpsetup.crt -days 822 \
  -subj "/CN=wpsetup" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Add your own addresses to `subjectAltName` if you connect from elsewhere.
Chrome warns about the self-signed cert once — click through.

## Patches (`patch_wpsetup.py`)

Both hang the UI on the forever-spinner after entering the PIN.

**1. `doOta()` checked the wrong variable.** The "non-EP firmware" guard ran
`firmware.indexOf("ep")`, but `firmware` is the parsed *firmware version*
string while the OTA URL lives in `firmwareURL`. On a 6086ep bot the version
string never contains `"ep"`, so a bogus "you are not in recovery mode" alert
fired on every run and the flow never continued. Now checks `firmwareURL` and
accepts a bot that already reports ep firmware.

**2. Activate was impossible from any mirror.** The button POSTed to
`wpsetup.keriganc.com/sessions`, which returns **no `Access-Control-Allow-Origin`**,
so the browser blocked the cross-origin read, the promise rejected, and the bot
never received the `doAnkiAuth()` it needs to pair with wire-pod. The prod
session token is a fixed public value (`2vMhFgktH3Jrbemm2WHkfGN` — the same one
wire-pod's own `chipper/pkg/wirepod/setup/ble.go` sends), so the patch skips the
dead network hop and authenticates against the bot directly, with 3 retries.

The OTA download itself still points at `wpsetup.keriganc.com:81` (keriganc's
server), which is what it does in the original flow.

## Layout

```
server.py           static https mirror (stdlib, no deps)
patch_wpsetup.py    applies the patches below to js/rts.js
html/main.html      the setup page
js/rts.js           patched setup app (browserify bundle)
js/rts.js.bak       pristine upstream, kept as the diff baseline
js/env/endpoints.js OTA/account endpoints for the bot
cert/               self-signed TLS material (generated locally, gitignored)
```

## Upstream

- Site: https://wpsetup.keriganc.com (mirror of `vector.techshop82.com`/`ddl.io`)
- App source: https://github.com/kercre123/vector-web-setup (MIT, Digital Dream Labs)
- Server software: https://github.com/kercre123/wire-pod
