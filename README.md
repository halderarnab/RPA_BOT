# CPCB Waste Tyre RPA Bot

Desktop automation scaffold for the CPCB Waste Tyre EPR portal workflow described in `RPA BOT - Tyre Recycler.docx`.

## What It Does

- Opens the portal in Chrome.
- Prompts for captcha and OTP during login.
- Reads Procurement, Recycling/Production, and Sales Excel files.
- Validates mandatory fields before submitting anything.
- Checks that invoice PDFs exist before upload.
- Continues from the last unprocessed row using `state/bot_state.json`.
- Logs every success and failure to `logs/rpa_bot.log`.
- Shows recent errors from the GUI.

## Run

```powershell
python app.py
```

## First-Time Setup

1. Edit `config.json`.
2. Replace `portal_url` with the real CPCB portal login URL.
3. Fill the selector arrays in `selectors` and `field_selectors`.
4. Start the app with `python app.py`.
5. Pick the Excel files and invoice folder in the GUI.

## Button Behavior

- **Open Browser**: launches Chrome and navigates to the configured portal URL.
- **Continue Data Entry**: logs in if needed, validates files, then resumes entry for procurement, recycling, and sales rows.
- **Show Errors**: displays recent `ERROR` entries from `logs/rpa_bot.log`.
- **Logout**: logs out the current logged in user.