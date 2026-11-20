# TSU Grade Watcher

Get a Telegram message when something changes on your grades page of the TSU student portal ([uni.tsu.ge](https://uni.tsu.ge)).

It logs in with your account, reads the same JSON data the portal's own page uses, compares it with the last saved copy, and tells you exactly which values are new or changed.

> **Unofficial.** Not affiliated with TSU. It uses the portal's internal API, which can change without notice. Use it only on your own account, keep the check interval reasonable, and check your university's rules. No warranty, see [LICENSE](LICENSE).

## Features

- Login with the same `/api/Auth/Login` request the website uses (cookie session, no browser needed)
- Detects any change in the response and sends the new and removed values
- Telegram notifications to one person or several
- Alerts you once if the check keeps failing (3 failures in a row), instead of every run
- `watch.sh` for running it on a phone (Termux) or PC: wake lock, interval in minutes
- Helper commands: `inspect`, `chat-id`, `test-telegram`, `reset`
- Small: one Python file, one dependency (`requests`)

## Requirements

- Python 3.8+
- A Telegram account and a bot token (free, from @BotFather)
- Your TSU portal username and password

## Setup

```bash
git clone https://github.com/<your-username>/tsu-grade-watcher.git
cd tsu-grade-watcher
pip install -r requirements.txt
cp config.example.json config.json
chmod 600 config.json
```

### 1. Create the Telegram bot

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the steps. Copy the token it gives you.
2. Open your new bot, press **Start**, and send it any message. Bots cannot message you first.
3. Put the token in `config.json` as `telegram_token`.
4. Run `python check_grades.py chat-id`. Copy the number it prints into `telegram_chat_id`.
5. Run `python check_grades.py test-telegram`. You should get a test message.

To notify several people, make each person press Start on the bot and message it, run `chat-id` again, and use a list:

```json
"telegram_chat_id": [123456789, 987654321]
```

Everyone on the list receives the full alert, including your grade values.

### 2. Add your portal login

Set `username` and `password` in `config.json`. You can also use environment variables instead of writing them in the file: `PORTAL_USER`, `PORTAL_PASS`, `TG_TOKEN`, `TG_CHAT_ID`.

### 3. Check that it works

```bash
python check_grades.py inspect
```

This logs in, prints the shape of the login response, fetches the grades request, and shows the first 40 values. If you see your courses or scores, it works.

## Usage

```bash
python check_grades.py                 # one check (the first run saves a baseline)
python check_grades.py inspect         # debug login and response
python check_grades.py chat-id         # find your Telegram chat id
python check_grades.py test-telegram   # send a test message
python check_grades.py reset           # forget saved state, next run = new baseline
```

### Run it repeatedly

**Loop script (PC or Android/Termux).** Run it when you expect grades:

```bash
sh watch.sh        # every 10 minutes
sh watch.sh 5      # every 5 minutes
```

It holds the Termux wake lock while running and releases it on Ctrl+C. Please don't go below about 5 minutes.

**Cron (always-on Linux machine):**

```cron
*/30 * * * * cd /path/to/tsu-grade-watcher && /usr/bin/python3 check_grades.py >> log.txt 2>&1
```

### Android (Termux)

1. Install **Termux** from F-Droid (the Play Store version is outdated).
2. `pkg update && pkg install python git && pip install requests`
3. Clone or copy this folder, create `config.json`, then run `python check_grades.py inspect`.
4. In Android settings, set Termux battery use to **Unrestricted**.
5. Start `sh watch.sh 10` when you want it watching, and leave the session open.

## How it works

1. `GET /` to receive the load-balancer cookie.
2. `POST /api/Auth/Login` with a JSON body. The server sets a session cookie.
3. Request `grades_path` (default `/api/Card/StudentProfile`, `POST`, body `1`).
4. Flatten the JSON into `path = value` lines and compare with `state.json`.
5. If anything differs, send the new and removed lines to Telegram, then save them as the new baseline. The baseline only advances if the message was actually delivered.

## Configuration

| Key | Meaning |
|---|---|
| `base_url` | Portal address |
| `login_path`, `login_payload` | Login request. `{user}` and `{pass}` are replaced with your credentials |
| `grades_path`, `grades_method`, `grades_body` | The request that returns your data. POST with no body sends `{}` |
| `ignore_keys` | JSON keys to skip, for values that change on every request (timestamps, counters) |
| `username`, `password` | Your portal login |
| `telegram_token`, `telegram_chat_id` | Bot token and one chat id, or a list of them |

## Troubleshooting

| Message | Meaning |
|---|---|
| `Login failed: HTTP ...` or no session cookie | Wrong credentials, or the field names in `login_payload` don't match. Compare with DevTools, Network tab, `Auth/Login`, Payload |
| `returned the portal's HTML page, not JSON` | `grades_path` is a page address. It must be the `/api/...` request behind the page |
| `HTTP 405` | Wrong method. Set `grades_method` to match DevTools |
| `HTTP 415` | The server wants a JSON body. Set `grades_body` |
| `HTTP 400` ... `Unexpected character` | The body has the wrong type. Copy the Payload from DevTools exactly (it can be a bare number like `1`) |
| Telegram `chat not found` | Wrong chat id, or you never pressed Start on the bot. Run `chat-id` |
| Alert on every run | Some field changes every time. Run `inspect` twice, compare, and add those keys to `ignore_keys` |

## Security notes

- `config.json`, `state.json`, `log.txt` and `debug_*.json` hold your password, grades, or personal data. They are in `.gitignore`. **Never commit them.** If you ever do, change your password and revoke the bot token with @BotFather.
- Use `chmod 600 config.json`.
- Anyone in `telegram_chat_id` sees your grade values.

## Adapting to another portal

If the portal is a single-page app with a JSON API, only the config needs to change: login path and payload, and the data request. Find them in the browser DevTools (Network tab, Fetch/XHR). Server-rendered portals would need HTML parsing instead.

## License

[MIT](LICENSE)
