# macOS setup for CV Adapter

## What you download

The GitHub Actions build produces a ZIP archive with:

- `CVAdapter.app`
- `.env.example`
- `system_prompt.txt`
- `README.md`

## Before the first launch

1. Start `CVAdapter.app` once. The app will create `~/Library/Application Support/CVAdapter/` automatically.
2. If available, the app will also copy `.env` or `.env.example` and `system_prompt.txt` there automatically.
3. If the copied `.env` still contains placeholders, edit it and fill in the required keys.
4. Put your own `client_secret.json` into `~/Library/Application Support/CVAdapter/` if the app did not copy it itself.
5. On the first Google authorization, `token.json` will be created in the same folder automatically

Recommended layout:

```text
~/Library/Application Support/CVAdapter/
	.env
	client_secret.json
	token.json
	system_prompt.txt   # optional
```

Why this is needed:

- unsigned apps launched from Finder may run through App Translocation
- in that mode, files placed next to `CVAdapter.app` can resolve to a temporary read-only path
- `~/Library/Application Support/CVAdapter/` is stable and avoids this issue completely

## If macOS blocks the app

Because the first CI version is **not code-signed / notarized**, macOS may warn that the app is from an unidentified developer.

Use one of these options:

1. In Finder, right-click `CVAdapter.app` → **Open**
2. Confirm the security dialog
3. If needed, open **System Settings → Privacy & Security** and allow the app manually
4. If Finder still starts the app from a translocated path, remove quarantine in Terminal:

```bash
xattr -dr com.apple.quarantine CVAdapter.app
```

## Notes

- Build is created on `macos-latest` in GitHub Actions
- This is enough for internal use and testing
- For public distribution, add Apple `codesign` and `notarization` later
