# Smart Service Dysk

A custom integration for Home Assistant that lets the built-in **Google Drive**
integration sign in through your **Smart Service** account. Backups are made by
Home Assistant's own Google Drive integration, as usual. This integration only
handles signing in and refreshing access.

[Polski opis — README_PL.md](README_PL.md)

## How it works

- Home Assistant's `google_drive` integration stores the backups on your Google Drive.
- Smart Service Dysk provides the sign-in method **“Smart Service”** for it, so you
  do not have to create your own Google Cloud project or OAuth client.
- The Google client's secret stays on the Smart Service panel. The access tokens are kept
  only in your Home Assistant.
- Access is limited to the files that Home Assistant creates on your Drive (`drive.file`).
- The integration has no screens of its own. **Smart Service HA** sets it up with the
  Drive key from your Smart Service panel, so you never need to add it by hand.

## Requirements

- Home Assistant **2026.7.0** or newer;
- Smart Service HA connected to a Smart Service account;
- a Google account.

## Installation

Smart Service HA installs and sets up this integration for you (**Extensions → Integrations**).

Manual installation: copy `custom_components/smartservice_dysk` into the
`custom_components` folder of your configuration and restart Home Assistant.

## Privacy

- Your backups go straight from Home Assistant to your Google Drive. They never pass through Smart Service.
- The Smart Service panel only takes part in signing in and refreshing access. It does not keep your tokens.

## Support

[smartservice.net.pl](https://smartservice.net.pl) · [kontakt.smart.service@gmail.com](mailto:kontakt.smart.service@gmail.com)

Google Drive is a trademark of Google LLC. This integration is not made or endorsed by Google.
