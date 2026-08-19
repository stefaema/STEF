# Notes

Things the reference states that are easy to lose, and cost a reel to relearn.

## Preflight

- **Pin the image quality.** RAW+JPEG writes two files per release, so one
  capture stops meaning one entry in `addedcontents`. Read
  `shooting/settings/stillimagequality`, refuse to start if it is not the
  recipe.
- **Disable auto power-off** (`functions/autopoweroff`). A body that sleeps
  mid-reel looks exactly like a network fault.
- **Drive mode to single.** Continuous turns one release into a burst.
- **AF operation to one-shot**, and `af: false` everywhere. Servo refocuses
  between frames; AF hunts on grain.
- **Shutter mode to electronic**, falling back to `elec_1st_curtain`. Shutter
  shock softens the frame.
- **Read settings back after writing.** A setting unavailable in the current
  mode returns an empty value and an empty ability list rather than an error.

## Temperature is a ladder, not a threshold

`normal → warning → stillqualitywarning → disablerelease`

`stillqualitywarning` means the camera is still shooting and the frames are
degraded. Waiting for `disablerelease` means a silently damaged run. Pause at
`warning`, stop at `stillqualitywarning`.

## The link

- **No USB transport.** Wi-Fi or wired LAN only; USB is for the one-time
  activation. Most enthusiast bodies have no Ethernet port.
- **Activation and enabling are different.** A one-time unlock with Canon's
  tool, then a menu toggle that is not sticky across power cycles on every
  body. Three distinct probe findings: unreachable, not activated, not enabled.
- **One client at a time.** Any phone app still connected blocks the PC.
- **Roughly 2-5 MB/s.** A card reader is ~90 MB/s, so the card is the fast path
  and bulk transfer over CCAPI is never the right choice. Pull thumbnails
  during a run for evidence; pull the card afterwards for the frames.

## Refusals

Retry only what clears on its own: `Device busy`, `Taken in preparation`,
`During shooting or recording`. `Mode not supported`, `Already started` and
`Not started` never will, and backing off only spends the time.

## Free reconciliation

`devicestatus/storage` carries `contentsnumber`, the file count on the card. It
answers "did every frame land" in one small call, with no transfer.
