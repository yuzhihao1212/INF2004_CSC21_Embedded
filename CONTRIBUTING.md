# How we work: the PR workflow

`main` is **protected**. You can't push to it directly. Every change goes through a
pull request (PR) that needs:

1. **CI passing:** the firmware must build with Pico SDK 1.5.1 and the Python must compile.
2. **One approval** from any teammate.

This keeps `main` always buildable, which matters most when we integrate everyone's
subsystems into one node.

---

## One-time setup

The repo moved to `yuzhihao1212/INF2004_CSC21_Embedded`. Point your local copy at it:

```
git remote set-url origin https://github.com/yuzhihao1212/INF2004_CSC21_Embedded.git
git fetch
```

## Everyday workflow

**1. Start from an up-to-date `main`**
```
git switch main
git pull
```

**2. Create a branch for one piece of work**
```
git switch -c feat/co2-slope
```
Name it `<type>/<short-description>`:

| Type     | Use for                                   | Example                  |
|----------|-------------------------------------------|--------------------------|
| `feat/`  | New functionality                         | `feat/wifi-udp-sender`   |
| `fix/`   | Bug fixes                                 | `fix/dht22-timeout`      |
| `test/`  | Test programs, validation, measurements   | `test/dsp-latency`       |
| `docs/`  | Documentation only                        | `docs/protocol-spec`     |
| `chore/` | Build, CI, repo housekeeping              | `chore/update-gitignore` |

**3. Commit as you go**
```
git add <files>
git commit -m "Add CO2 rate-of-change over a 60 s window"
```
Write the message as what the commit *does*, e.g. "Add ...", "Fix ...", "Move ...".

**4. Push and open a PR**
```
git push -u origin feat/co2-slope
```
GitHub prints a link to open the PR, or use the **Compare & pull request** button on the
repo page. Fill in the template: what changed, how you tested it, and which hardware you
flashed it on.

**5. Get it reviewed and merged**
- Wait for the CI checks to go green ✅. If one fails, click **Details** to see the error, fix it,
  then commit and push again. The PR updates automatically.
- A reviewer is requested automatically based on which folders you changed (see
  `.github/CODEOWNERS`). Anyone on the team can approve.
- Once approved and green, click **Merge pull request** (keep the default
  **Create a merge commit**), then **Delete branch**.

**6. Clean up locally**
```
git switch main
git pull
git branch -d feat/co2-slope
```

## Keeping your branch up to date

If `main` has moved on while you're working (or GitHub says your branch has conflicts):
```
git switch main
git pull
git switch feat/co2-slope
git merge main
```
Fix any conflicts VS Code shows, then `git add` the files, `git commit` and `git push`.

## Reviewing a teammate's PR

- Open the PR → **Files changed**. Read the diff and leave comments on specific lines.
- Check: does it build (CI green)? Is it tested? Does it touch anyone else's interface
  (pin assignments, packet format, feature order)?
- **Review changes** → **Approve**, or **Request changes** with what needs fixing.
- Aim to review within a day. Small PRs get reviewed faster, so keep them focused.

## Rules of thumb

- **Small, short-lived PRs.** Merge within 1–2 days. Long-lived branches drift and conflict.
- **One topic per PR.** Don't mix a sensor fix with a CMake restructure.
- **Never commit `build/` folders**, `.uf2` files, Python virtualenvs or large raw audio.
  `.gitignore` covers these.
- **Binary documents** (`.docx`, `.pdf`, `.xlsx`) can't be merged if two people edit them.
  Write the report and slides in Google Docs / OneDrive, not in the repo.
- **Changing a shared interface** (pins, packet format, ML feature order, config parameters)?
  Tag the affected teammates in the PR description.

## Colour rules (dashboard)

The dashboard (`pc/mosaic/web/`) uses five colour families. Each one has a single job, so a colour always means the same thing wherever it shows up. The tokens live at the top of `style.css` in both light and dark mode. Use the tokens and never write a hex value in a component rule.

| Family | Tokens | Use it for | Never for |
|---|---|---|---|
| Neutral | `--text`, `--muted`, `--border`, `--surface`, `--bg`, `--header` | Everything by default: text, cards, labels, "Simulated", "Warming up", timestamps | — |
| Brand purple | `--accent`, `--accent-text`, `--accent-control`, `--accent-soft` | Things you can click or that are selected: active page, chosen class type, buttons, links, focus ring | Data, status or decoration |
| Status | `--ok-*`, `--warn-*`, `--error*` | Room health (fine, keep an eye on it, act now) and sensor link health | Anything that isn't a health state |
| Sensor tints | `--sense-comfort`, `--sense-air`, `--sense-motion`, `--sense-sound` | Which sensor: the icon next to a reading, and sensor bars | Tag or card backgrounds (amber and coral would read as alerts) |
| Area looks | `--look-speak`, `--look-settled`, `--look-talk`, `--look-loud`, `--look-none` (and `-text` pairs) | What an area is doing right now on the Live room map, its key, the loudness bar and the last-10-minutes bar. Settled, talk and loud follow the status colours; speak (blue) is the lecturer's voice | Anything outside those four places |

Chart lines use `--series-1` to `--series-6`, one per node, together with a dash pattern. Series colours appear only inside charts and in the node key on the Sensors page.

Tags all share one shape: a white pill with neutral text. The colour sits only in the dot or the leading icon. Only "Act now" and "Connection lost" get a solid red fill, so they're the only things on screen that shout. Every status also carries an icon or a word, never colour alone.

A new colour needs a new job. If it doesn't fit one of the families above, raise it in the group chat before adding a token.

## Who owns what

Reviewers are auto-requested from `.github/CODEOWNERS`:

| Area                                         | Owner(s)          |
|----------------------------------------------|-------------------|
| Environmental sensors (`firmware/tests/`)    | Kendrick          |
| Audio DSP (`firmware/tests/audio_dsp*`)      | Moe               |
| ML pipeline (`ml/`)                          | Darius, Moe       |
| PC gateway, fusion, dashboard (`pc/`)        | ZhiHao, Arif      |
| Networking / protocol (`pc/prototype/`)      | Arif, ZhiHao      |
| CI, repo setup, docs                         | ZhiHao            |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `push declined due to repository rule` / `protected branch` | You tried to push to `main`. Create a branch: `git switch -c feat/my-change`, then push that. |
| Committed to `main` locally by mistake | `git switch -c feat/my-change` (keeps your commits on a new branch), then `git switch main` and `git reset --hard origin/main`. |
| CI "Build firmware" failed | Click **Details**, scroll to the first `error:`. Build locally first: `cmake -S firmware -B firmware/build -G Ninja` and `ninja -C firmware/build`. |
| Merge conflict | See [Keeping your branch up to date](#keeping-your-branch-up-to-date). Ask in the group chat if it's in someone else's file. |
| VS Code can't find the build after pulling | Ctrl+Shift+P → **CMake: Delete Cache and Reconfigure**. |
