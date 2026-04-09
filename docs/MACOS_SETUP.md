# macOS setup for CV Adapter

## What you download

The GitHub Actions build produces a ZIP archive with:

- `CVAdapter.app`
- `.env.example`
- `system_prompt.txt`
- `README.md`

## Before the first launch

1. Copy `.env.example` to `.env`
2. Fill in the required keys in `.env`
3. Put your own `client_secret.json` рядом с приложением или в удобной рабочей папке
4. On the first Google authorization, your `token.json` will be created automatically

## If macOS blocks the app

Because the first CI version is **not code-signed / notarized**, macOS may warn that the app is from an unidentified developer.

Use one of these options:

1. In Finder, right-click `CVAdapter.app` → **Open**
2. Confirm the security dialog
3. If needed, open **System Settings → Privacy & Security** and allow the app manually

## Notes

- Build is created on `macos-latest` in GitHub Actions
- This is enough for internal use and testing
- For public distribution, add Apple `codesign` and `notarization` later
