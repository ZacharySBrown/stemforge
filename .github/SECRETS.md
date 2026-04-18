# GitHub Actions Secrets — StemForge

Secrets required by `.github/workflows/release.yml` and the composite actions
under `.github/actions/`. Names only — **never commit values**. Rotate per the
cadence below.

Set these via: `Settings -> Secrets and variables -> Actions -> New repository secret`.

## Required secrets

| Name | Used by | Purpose |
|---|---|---|
| `CODESIGN_ID` | `notarize` composite (binary kind) | Common Name of the **Developer ID Application** identity, e.g. `Developer ID Application: Example Inc. (TEAM12345)`. Passed to `codesign --sign`. |
| `CODESIGN_CERT_P12_B64` | `notarize` composite | Base64-encoded `.p12` bundle exported from Keychain Access containing the Developer ID Application cert **and** its private key. Generate: `base64 -i DeveloperID.p12 \| pbcopy`. |
| `CODESIGN_CERT_PW` | `notarize` composite | Password set when exporting the `.p12`. Used to decrypt on import into the CI keychain. Also reused by the installer codesign step. |
| `INSTALLER_ID` | `notarize` composite (installer kind) | Common Name of the **Developer ID Installer** identity, e.g. `Developer ID Installer: Example Inc. (TEAM12345)`. Passed to `productsign --sign`. |
| `INSTALLER_CERT_P12_B64` | `notarize` composite (installer kind) | Base64-encoded `.p12` bundle containing the Developer ID Installer cert + private key. |
| `APPLE_ID` | `notarize` composite | Apple ID email used to submit to `xcrun notarytool`. |
| `APPLE_TEAM_ID` | `notarize` composite | 10-char team identifier (e.g. `ABCDE12345`) found on https://developer.apple.com/account. |
| `APPLE_APP_PW` | `notarize` composite | App-specific password generated at https://appleid.apple.com -> Sign-In and Security -> App-Specific Passwords. Not the Apple ID login password. |

## Generating `_CERT_P12_B64` values

1. In Keychain Access on a trusted Mac with the cert installed, select the
   certificate **and** its private key, right-click -> Export 2 items -> save
   as `.p12` with a strong password.
2. Encode: `base64 -i DeveloperID.p12 | pbcopy`.
3. Paste into the GitHub secret. Delete the intermediate `.p12` after upload.
4. Store the plaintext password in a password manager; add as `CODESIGN_CERT_PW`.

## Rotation cadence

- **Developer ID certs**: valid 5 years. Rotate at most 90 days before expiry.
  Check `security find-certificate -c "Developer ID Application" -p | openssl x509 -noout -dates`.
- **App-specific password**: rotate every 12 months, or immediately if the
  Apple ID was accessed from an untrusted device.
- **Any leak**: revoke the affected cert on https://developer.apple.com,
  regenerate, re-encode, replace the secret. Force-push nothing — just update
  the secret; next release re-signs with the new cert.

## Never commit

- Real `.p12` files.
- Base64 strings of real certs.
- Apple IDs or team IDs in workflow files (use `${{ secrets.* }}`).
- Plaintext notarization passwords in any file, log, or comment.

`actionlint` does not validate secret references — reviewers must. Any
workflow referencing an undocumented secret name is a review-blocking issue.

## Local testing

For local dry-runs of signing, use `act` with a `.secrets` file **gitignored
at repo root**. Never commit `.secrets`. The repo's root `.gitignore` should
include it (enforce in review).
