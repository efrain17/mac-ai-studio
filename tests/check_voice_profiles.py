#!/usr/bin/env python3
"""Checks the voice profile library without opening the page: describe, save, reload, delete.

Runs in the stems environment against a temporary studio folder, so the owner's saved voices are
never touched. Exits non-zero on failure.
"""
import os
import pathlib
import sys
import tempfile

REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
failed = False


def check(label, ok, detail):
    global failed
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}", flush=True)
    failed = failed or not ok


def main():
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["STUDIO_HOME"] = temporary
        sys.path.insert(0, str(REPO_DIR / "runtime"))
        import stems_voices as page

        text = page.describe("young adult", "female", "warm", "clean", "", "")
        check("Description", text == "young adult female lead vocal, warm tone, clean voice", text)
        text = page.describe("elderly", "male", "dark", "raspy", "Irish", "sings close to the microphone")
        check("Description with accent and notes",
              text == "elderly male lead vocal, dark tone, raspy voice, Irish accent, sings close to the microphone",
              text)
        page.save_profiles({"Test voice": {"text": text}})
        check("Saved and reloaded", page.load_profiles().get("Test voice", {}).get("text") == text,
              f"{sorted(page.load_profiles())}")
        check("Stored inside the studio folder", str(page.PROFILES_FILE).startswith(temporary),
              str(page.PROFILES_FILE))
        page.save_profiles({})
        check("Deleted", page.load_profiles() == {}, "empty library")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
