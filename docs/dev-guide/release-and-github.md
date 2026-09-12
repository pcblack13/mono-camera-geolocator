# Release & GitHub

Repo root is `~/Desktop/GEO-1`. The app lives at
`tools/mono-camera-geolocator`. Both matter — `git` runs from the repo root, most
build commands run from the software directory.

---

## ★ The two names you must not confuse

There are two different tags in play and they are **not** the same string:

| Tag | What it is | Example |
|---|---|---|
| `win-build-v<version>` | a **trigger**. Pushing it starts the Windows CI build. | `win-build-v1.2.6` |
| `gcp_picker-v<version>` | the **GitHub Release** the installer gets attached to. | `gcp_picker-v1.2.6` |

The workflow derives the second from the first:

```powershell
$tag = "gcp_picker-" + "${{ github.ref_name }}".Substring("win-build-".Length)
```

---

## ★ The release must exist BEFORE the build finishes

`.github/workflows/windows-installer.yml` ends with:

```yaml
gh release upload "${{ steps.rel.outputs.tag }}" $exe.FullName --clobber
```

`gh release upload` attaches an asset to an **existing** release. It never
creates one. If `gcp_picker-v<version>` does not exist, the job builds for
30–45 minutes and then fails on the very last step.

**Create the release before or during the build, not after.**

---

## Full release sequence

```bash
cd ~/Desktop/GEO-1/tools/mono-camera-geolocator

# 1. Bump the version
#    edit desktop/package.json  ->  "version": "1.2.6"

# 2. Write/refresh the notes
#    desktop/installer/1.2.6.md   (new file, per release)
#    INSTALL.md                   (version numbers + "What's new")
#    RELEASE_CHECKLIST.md         (any new manual checks)

# 3. Run everything in tests-and-builds.md and get it green

# 4. Commit
cd ~/Desktop/GEO-1
git status                       # READ this before staging
git add -A
git commit -m "Release 1.2.6"
git push

# 5. Create the GitHub Release FIRST
gh release create gcp_picker-v1.2.6 \
  --title "Mono Camera Geolocator 1.2.6" \
  --notes-file tools/mono-camera-geolocator/desktop/installer/1.2.6.md \
  --latest

# 6. Now trigger the Windows build
git tag win-build-v1.2.6
git push origin win-build-v1.2.6

# 7. Meanwhile, build the Linux artifacts locally
cd tools/mono-camera-geolocator/frontend && npm run build
cd ../desktop && npm run dist

# 8. Upload the Linux artifact
gh release upload gcp_picker-v1.2.6 \
  dist-installers/mono-camera-geolocator_1.2.6_amd64.deb --clobber

# 9. Watch the Windows job
gh run list --limit 3
```

---

## ★ Never `git push --tags`

```bash
git push --tags                       # ✗ DON'T
git push origin win-build-v1.2.6      # ✓ DO
```

`--tags` pushes **every** local tag the remote does not have. If an old
`win-build-*` tag is sitting in your local repo unpushed, it fires its workflow
too — a second 45-minute Windows build, from old source, competing with your
real release for a runner. This happened on the 1.2.6 release: `win-build-v1.2.3`
went along for the ride and had to be cancelled.

Inspect before pushing:

```bash
git tag -l "win-build-*"                    # local tags
git ls-remote --tags origin "win-build-*"   # remote tags
```

Anything in the first list but not the second will fire if you use `--tags`.

---

## `gh` commands worth knowing

```bash
# does this release exist?
gh release view gcp_picker-v1.2.6

# create it (--latest matters: README points users at /releases/latest)
gh release create gcp_picker-v1.2.6 \
  --title "Mono Camera Geolocator 1.2.6" \
  --notes-file tools/mono-camera-geolocator/desktop/installer/1.2.6.md \
  --latest

# attach or replace an asset
gh release upload gcp_picker-v1.2.6 path/to/file --clobber

# what assets are on it now
gh release view gcp_picker-v1.2.6 --json assets \
  --jq '.assets[] | "\(.name)  \(.size)"'

# list releases
gh release list

# workflow runs
gh run list --limit 5
gh run view <run-id>
gh run view <run-id> --log-failed     # only the failing step's log
gh run watch <run-id>                 # follow until it finishes
gh run cancel <run-id>
```

---

## Reading the workflow

`.github/workflows/windows-installer.yml`

- triggers on `push` of any tag matching `win-build-*`, or manual
  `workflow_dispatch` where you type the release tag yourself
- `runs-on: windows-latest` — **Windows only.** Nothing in CI builds the Linux
  `.deb` or `.AppImage`; you build those locally and upload them by hand
- caches the ~500 MB conda runtime, keyed on `backend/requirements.txt` and
  `build-runtime.ps1`. Change either and the next run rebuilds it (~15 min extra)
- `permissions: contents: write` — needed for `gh release upload`

Manual trigger without pushing a tag: Actions tab → `windows-installer` →
**Run workflow** → enter the existing release tag.

---

## ★ `${{ ... }}` is GitHub Actions syntax, not shell

Copying a line out of the workflow file into your terminal gives:

```
bash: ${{ steps.rel.outputs.tag }}: bad substitution
```

Those placeholders are filled in by the runner. Substitute the real value by
hand if you want to run the equivalent locally.

---

## After the release

```bash
# confirm both installers are attached
gh release view gcp_picker-v1.2.6

# confirm /releases/latest resolves to this one
gh release list --limit 3
```

Then work through `RELEASE_CHECKLIST.md` §3 — in particular, diff
`<app-data>/work/.env` against `backend/.env` on every machine you upgrade.
Nothing keeps them in sync, and a stale value there hid a working map provider
for an entire release.
