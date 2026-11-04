# Updating

Most of the studio's programs come from Homebrew, so one double-click updates them. The rest is kept at the versions that were tested, on purpose.

## The regular update

1. Quit Mac AI Studio.
2. Double-click **Update Mac AI Studio.command** in the installer folder. A Terminal window opens.
3. Wait for `All tools are up to date`. If a line says `FAIL`, see [After an update](TROUBLESHOOTING.md#after-an-update).
4. Open Mac AI Studio and run one image, to see that it still works.

Do this when you have no deadline, since new versions are not tested with the studio first. Once a month is enough.

| Updated by the double-click | Kept as installed |
| --- | --- |
| Git, Python 3.12, uv, FFmpeg 8 | ComfyUI and its Python packages |
| Miniconda, Stability Matrix | ACE-Step, Demucs, librosa |
| LM Studio, AnythingLLM | The models, including the chat model |

## Updates the apps offer by themselves

- **LM Studio** checks for a new version each time it opens and shows **Update now**. Accepting is fine; it is the same program the double-click updates.
- **Stability Matrix** can also update itself from its own settings.
- **AnythingLLM** does not update itself; the double-click does it.

## What is never updated, and why

ComfyUI, ACE-Step, Demucs, librosa and every model stay at the tested versions. A new release of any of them can change what a workflow produces or stop working on Metal. If you want a newer one, ask for a tested update of the installer; do not update them by hand.

## If the update breaks something

1. Run the milestone scripts again, in order: `./milestone1.sh`, `./milestone2.sh`, `./milestone3.sh`, `./milestone4.sh`. Each one is quick when nothing is missing, and rebuilds only what the update broke.
2. Run `./milestone1.sh --test` (and the `--test` of the milestone that failed).
3. If it still fails, read the newest log in `~/MacAIStudio/logs` and see [Problems and fixes](TROUBLESHOOTING.md).
