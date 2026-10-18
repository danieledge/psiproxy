# CLAUDE.md: PsiProxy

Read this before changing anything. The user-facing documentation is
`README.md`. PsiProxy is one program of the Psion Series 5mx suite
(PsiTerm, PsiMail, PsiWeb, PsiCast, PsiLinux, PsiConnect, psion-core);
until October 2026 it was `proxy/` in the PsiTerm repository.

## What this is

The public, **optional** HTTP proxy the apps can use from a computer on the
user's network: the apps are off it as standard and have **no proxy
address built in**. Plain Python 3.10+, no build step.

- `psiproxyd.py`: the daemon (TCP server, client allowlist, control socket,
  log). `psiproxy_core.py`: the engine (fetching with TLS on the computer,
  page slimming for a 640x240 16-grey browser, pictures to 16-grey GIFs,
  one connection per Psion, `Range` downloads, plug-ins, checks).
  `psiproxytui.py` and `psiproxy`: the Textual dashboard.
- Routes the apps use: ordinary proxied `GET`/`POST`, `/_putlog` (the apps'
  **Send log to server** button, written to `PSIPROXY_LOG_DIR`), and the
  plug-ins' own routes.
- **Plug-ins** load only if present: modules in `plugins.local/` (or beside
  `psiproxyd.py`, or on `PSIPROXY_PLUGIN_PATH`) listed in
  `plugins.local.json`, both git-ignored. A missing or failing plug-in is
  logged and skipped. The public repository must not name private
  plug-ins; PsiLinux's `psiapk` is public and may be mentioned.
- Settings come from the environment (`PSIPROXY_*`), with
  `~/.config/psiproxy/psiproxy.env` as a file to copy from
  `psiproxy.env.example`; the systemd unit uses `EnvironmentFile=`. Secrets
  (for plug-ins) come from the environment too, never from files in this
  repository.

The LIVE proxy Dan runs is a separate checkout elsewhere, not this one:
changing this repository changes nothing running.

## Testing

There is no test suite. Smoke checks: `python3 -m py_compile *.py`,
`bash -n psiproxy`, and a run on 127.0.0.1 with `curl -x 127.0.0.1:8081
http://example.com/`. The link between the Psion and PsiProxy is plain
HTTP: keep it on a trusted network (`PSIPROXY_ALLOW`).

## Rules

- Never commit: `psiproxy.env`, `*.env`, `plugins.local/`, `*.local.json`,
  logs, tokens, LAN addresses or home paths.
- Treat every page and every request from a Psion as untrusted input.
- British English, plain short sentences, no em dashes. Commit messages in
  plain British English.
