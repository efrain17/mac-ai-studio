# Training session guide

A 1.5 to 2 hour live session where the owner does the clicking. Use placeholder content only.

## Before the session

- [ ] `./milestone5.sh` shows every line as `PASS`
- [ ] Open each tab once, so the models are loaded
- [ ] Render one video ahead of time, because video is slow
- [ ] Agree on how you will record. On a Mac, press Cmd+Shift+5 to record the screen, and choose a microphone under **Options**
- [ ] Do a 30-second recording test and play it back

## During the session

Start recording first. Say the date and what the session covers.

| Time | Topic | The owner does this |
| --- | --- | --- |
| 10 min | Opening | Opens and quits the app. Finds **My Files** |
| 25 min | Images | Opens each style, changes a prompt, renders, finds the file |
| 25 min | Video | Adds a sketch to the folder, runs a batch, runs sketch and fill |
| 25 min | Music | Pastes lyrics, generates, tries the Temperature, Top-K and Top-P controls |
| 10 min | Stems and voices | Splits a song, reads its tempo and key with Analyze, reads its chords with Chords, drags stems into a music app, saves a voice profile |
| 10 min | Training a LoRA | Walks through the page and runs a small batch. Explain the known limits |
| 10 min | Chat | Asks the assistant how to do something from the session, then, with `@agent`, asks it to render one image |
| 10 min | Independent test | Runs one custom prompt alone while you stay online and quiet |

## Daily rules to teach

1. Open the app. Quit it when finished.
2. Finished work is in `My Files`. Back up that folder.
3. Keep the style words in a prompt.
4. A slow render is normal. Close other heavy apps for the big ones.
5. No internet is needed.
6. To update, quit the app and double-click **Update Mac AI Studio.command**. Do it when you have no deadline, because new versions are not tested first.
7. If something fails, quit and reopen the app first.
8. Not sure how to do something? Ask the Chat tab. It has read the studio's guides.

## Closing the session

The owner must complete one custom test prompt without help.

- [ ] Independent test passed
- [ ] Recording saved, played back and delivered
- [ ] `docs/TROUBLESHOOTING.md` and `docs/UPDATING.md` handed over
