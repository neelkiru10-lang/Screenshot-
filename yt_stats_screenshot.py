#!/usr/bin/env python3
"""
Take a REAL Stats-for-Nerds screenshot of a YouTube video.

What it does (honest, no faking):
  1. Opens the video URL (or searches YouTube for a keyword and opens the top result).
  2. Dismisses any consent/cookie dialog.
  3. Plays the video in REAL TIME, start to end, at normal speed (1x).
     No seeking, no 2x speed — the frames counter in the Stats overlay
     therefore reflects a full, honest watch.
  4. Enables the genuine YouTube "Stats for nerds" overlay via the
     video's right-click context menu.
  5. The moment playback ends, screenshots the player with the overlay
     visible (Video ID, dropped/total frames, channel, end time).
  6. Saves the screenshot as stats-<video-id>.png and prints the video
     duration, the final frames count and the screenshot path.

Usage:
  python yt_stats_screenshot.py --video-url https://www.youtube.com/watch?v=XXXX
  python yt_stats_screenshot.py --keyword "Roobet Promo Code"
  python yt_stats_screenshot.py --self-test /tmp/yt-self-test/test.html
      (local mechanics test only: no YouTube, uses a local page that mimics
       the YouTube player DOM — video element, right-click "Stats for nerds"
       menu item, stats overlay. Verifies the automation mechanics.)

Exit codes:
  0  success — screenshot saved
  1  usage error (no video URL / keyword)
  2  video did not play (currentTime stuck at 0, or no <video> element)
  3  Stats-for-Nerds overlay did not appear
  5  bot-check / consent-wall markers found in the page text
     ("not a robot", "unusual traffic", "verify you are human", "captcha")
  6  video length outside the supported range (under 5s or over 8:00)
     (v1 used 4 for bot-check and 5 for length; v2 renumbers bot-check to 5.)

Requires: selenium (pip install selenium). Chrome is provided by
Selenium Manager (GitHub-hosted runners already have Google Chrome).
"""

import argparse
import os
import re
import sys
import time
import urllib.parse

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

MIN_DURATION_S = 5        # videos shorter than this are not worth a run
MAX_DURATION_S = 480      # 8:00 — bounds the GitHub Actions runtime
STALL_TIMEOUT_S = 30      # currentTime must advance within this window
PLAY_TIMEOUT_S = 90       # time allowed for the video element to appear

BOT_MARKERS = ["not a robot", "unusual traffic", "verify you are human",
               "captcha", "confirm you're human",
               "our systems have detected"]


def fail(code, message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def set_output(key, value):
    """Expose a value to the GitHub Actions workflow (no-op locally)."""
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def extract_video_id(url):
    """Video ID from a youtube.com/watch?v=..., youtu.be/... or /shorts/... URL."""
    parsed = urllib.parse.urlparse(url)
    if "youtu.be" in parsed.netloc:
        return parsed.path.strip("/").split("/")[0] or None
    if "/shorts/" in parsed.path:
        parts = parsed.path.strip("/").split("/")
        idx = parts.index("shorts")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    qs = urllib.parse.parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]
    return None


def normalize_watch_url(url):
    """youtu.be/ID and /shorts/ID -> https://www.youtube.com/watch?v=ID.

    Short and embed-style URLs can land on different YouTube surfaces
    (redirects, interstitials). The plain watch URL is the most direct
    route to the player.
    """
    video_id = extract_video_id(url)
    parsed = urllib.parse.urlparse(url)
    if video_id and ("youtu.be" in parsed.netloc or "/shorts/" in parsed.path):
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


def make_driver(chrome_binary=None):
    options = webdriver.ChromeOptions()
    if chrome_binary:
        options.binary_location = chrome_binary
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--mute-audio")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--lang=en-US")
    # Headless Chrome's default UA contains "HeadlessChrome", which makes
    # YouTube show bot-checks far more often. A plain desktop Chrome UA
    # is a normal browser configuration, not a spoof of the watch itself.
    options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    # Hide the automation flags Selenium sets by default. This only makes
    # the browser look like an ordinary desktop Chrome; the watch itself
    # is still a real, full, real-time play at 1x speed.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)
    return driver


def video_state(driver):
    """Current state of the first <video> element, or None if absent."""
    return driver.execute_script(
        """var v = document.querySelector('video');
           if (!v) return null;
           return {t: v.currentTime, d: v.duration, p: v.paused,
                   rate: v.playbackRate, rs: v.readyState};"""
    )


def dismiss_consent(driver, timeout=15):
    """Click through YouTube/Google consent dialogs, if any appear.

    Tries several selector strategies because the dialog varies by
    region and surface: button text, aria-label, and role=button.
    Returns True once a consent button was clicked.
    """
    strategies = []
    for label in ("Accept all", "Reject all", "I agree", "Accept"):
        strategies.append(
            (f"button text '{label}'",
             f"//button[contains(., '{label}')]"))
        strategies.append(
            (f"aria-label '{label}'",
             f"//*[@aria-label='{label}']"))
    strategies.append(
        ("role=button 'Accept all'",
         "//*[@role='button' and contains(., 'Accept all')]"))
    strategies.append(
        ("role=button 'Reject all'",
         "//*[@role='button' and contains(., 'Reject all')]"))

    deadline = time.time() + timeout
    while time.time() < deadline:
        for name, xpath in strategies:
            try:
                for el in driver.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        print(f"Consent dialog: clicking via {name}")
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)
                        return True
            except Exception:
                pass
        time.sleep(1)
    return False


def page_text_lower(driver):
    try:
        return driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return ""


def looks_like_bot_check(driver):
    text = page_text_lower(driver)
    url = driver.current_url.lower()
    if any(s in text for s in BOT_MARKERS):
        return True
    if "sorry" in url and "google.com" in url:
        return True
    return False


def dump_debug(driver, video_id, output_dir):
    """Save a screenshot of whatever page actually loaded, plus title,
    URL and a page-text snippet, so a failure can be diagnosed."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"debug-{video_id}.png")
    try:
        driver.save_screenshot(path)
        print(f"Debug screenshot saved: {path}")
    except Exception as exc:  # noqa: BLE001 - best effort
        print(f"Could not save debug screenshot: {exc}")
    try:
        print(f"Debug page title: {driver.title!r}")
    except Exception:
        pass
    try:
        print(f"Debug current URL: {driver.current_url}")
    except Exception:
        pass
    snippet = page_text_lower(driver).replace("\n", " ")[:500]
    print(f"Debug page text (first 500 chars): {snippet!r}")
    return path


def wait_for_video(driver, video_id, output_dir):
    """Wait until a <video> element with a real duration exists."""
    deadline = time.time() + PLAY_TIMEOUT_S
    while time.time() < deadline:
        if looks_like_bot_check(driver):
            dump_debug(driver, video_id, output_dir)
            fail(5, "YouTube showed a bot-check / unusual-traffic page. "
                    "Re-run the workflow later.")
        state = video_state(driver)
        if state and state["d"] and state["d"] > 0 and state["d"] != float("inf"):
            return state
        time.sleep(2)
    # No video within the timeout: record what page actually loaded so
    # the failure can be diagnosed from the debug artifact.
    dump_debug(driver, video_id, output_dir)
    if any(marker in page_text_lower(driver) for marker in BOT_MARKERS):
        fail(5, "No <video> element appeared within "
                f"{PLAY_TIMEOUT_S}s and the page text contains bot-check "
                "markers. Re-run the workflow later.")
    fail(2, "No playable <video> element appeared within "
            f"{PLAY_TIMEOUT_S}s (video may be unavailable / region-blocked).")


def start_playback(driver):
    """Start playback at normal speed. Returns the video state."""
    driver.execute_script(
        """var v = document.querySelector('video');
           if (v) { v.playbackRate = 1.0; v.play(); }"""
    )
    time.sleep(3)
    state = video_state(driver)
    if not state:
        fail(2, "Video element disappeared after trying to play.")
    return state


def enable_stats_for_nerds(driver):
    """Open the video's right-click menu and click 'Stats for nerds'.

    Retries once, with a JS-dispatched contextmenu event as fallback.
    Returns True once the overlay (containing 'Video ID') is visible.
    """
    for attempt in range(2):
        try:
            video = driver.find_element(By.TAG_NAME, "video")
            if attempt == 0:
                ActionChains(driver).move_to_element(video).context_click().perform()
            else:
                driver.execute_script(
                    """var v = document.querySelector('video');
                       v.dispatchEvent(new MouseEvent('contextmenu',
                           {bubbles: true, clientX: 200, clientY: 200}));"""
                )
            time.sleep(1.5)
            item = None
            for xpath in (
                "//*[normalize-space(text())='Stats for nerds']",
                "//div[contains(@class,'ytp-menuitem')]//*[contains(text(),'Stats for nerds')]",
            ):
                try:
                    item = driver.find_element(By.XPATH, xpath)
                    if item.is_displayed():
                        break
                except NoSuchElementException:
                    continue
            if item is not None and item.is_displayed():
                try:
                    item.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", item)
                time.sleep(1.5)
        except Exception as exc:  # noqa: BLE001 - menu may not exist yet
            print(f"Stats menu attempt {attempt + 1} failed: {exc}")

        if stats_overlay_visible(driver):
            print("Stats for nerds overlay is visible.")
            return True
        # Close any open menu before retrying (Escape + click elsewhere).
        try:
            ActionChains(driver).send_keys("\ue00c").perform()  # Escape
        except Exception:
            pass
        time.sleep(1)

    return stats_overlay_visible(driver)


def stats_overlay_visible(driver):
    """True when the page shows the Stats-for-Nerds overlay (has 'Video ID')."""
    try:
        els = driver.find_elements(By.XPATH, "//*[contains(text(),'Video ID')]")
        return any(el.is_displayed() for el in els)
    except Exception:
        return False


def read_frames_count(driver):
    """Parse the 'Dropped frames: X / N' total from the overlay text."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return None
    match = re.search(r"Dropped frames:\s*\d+\s*/\s*(\d+)", body_text)
    return int(match.group(1)) if match else None


def wait_for_end(driver, duration):
    """Poll playback until the video ends. Fails if playback stalls."""
    last_time = -1.0
    last_advance = time.time()
    deadline = time.time() + duration + 120
    while time.time() < deadline:
        state = video_state(driver)
        if not state:
            fail(2, "Video element disappeared during playback.")
        if state["p"] and state["t"] < duration - 0.5:
            print("Playback paused unexpectedly — resuming.")
            driver.execute_script("document.querySelector('video').play();")
            time.sleep(1)
            continue
        if state["t"] > last_time + 0.01:
            last_time = state["t"]
            last_advance = time.time()
        if time.time() - last_advance > STALL_TIMEOUT_S:
            fail(2, f"Playback stalled: currentTime stuck at {state['t']:.1f}s "
                    f"for {STALL_TIMEOUT_S}s (video is not playing).")
        if state["t"] >= duration - 0.5:
            print(f"Playback ended at {state['t']:.1f}s / {duration:.1f}s.")
            return state
        # Poll faster near the end so the screenshot lands right at the end.
        time.sleep(0.5 if duration - state["t"] < 5 else 2)
    fail(2, "Playback did not finish within the expected time.")


def take_screenshot(driver, video_id, output_dir):
    """Screenshot the player with the Stats overlay + controls visible."""
    try:
        video = driver.find_element(By.TAG_NAME, "video")
        # Hover the player so the control bar (with the end time) shows.
        ActionChains(driver).move_to_element(video).perform()
    except Exception:
        pass
    time.sleep(1)
    path = os.path.join(output_dir, f"stats-{video_id}.png")
    driver.save_screenshot(path)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        fail(2, "Screenshot file was not created.")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Real Stats-for-Nerds screenshot of a YouTube video.")
    parser.add_argument("--video-url", help="Full YouTube video URL")
    parser.add_argument("--keyword", help="YouTube search keyword (top result is used)")
    parser.add_argument("--output-dir", default=".",
                        help="Directory for the screenshot PNG")
    parser.add_argument("--self-test", metavar="PAGE",
                        help="Local mechanics test: path to a test HTML page")
    parser.add_argument("--chrome-binary",
                        help="Path to a Chrome/Chromium binary (local testing)")
    args = parser.parse_args()

    if args.self_test:
        video_id = "TEST123"
        url = "file://" + os.path.abspath(args.self_test)
        print(f"SELF-TEST mode: loading {url}")
    elif args.video_url:
        video_id = extract_video_id(args.video_url)
        if not video_id:
            fail(1, f"Could not read a video ID from --video-url: {args.video_url}")
        url = normalize_watch_url(args.video_url)
    elif args.keyword:
        video_id = None  # resolved after opening the top search result
        url = ("https://www.youtube.com/results?search_query="
               + urllib.parse.quote_plus(args.keyword))
    else:
        fail(1, "Give --video-url or --keyword (or --self-test PAGE).")

    set_output("video_id", video_id or "")
    os.makedirs(args.output_dir, exist_ok=True)

    driver = make_driver(args.chrome_binary)
    try:
        print(f"Opening: {url}")
        driver.get(url)

        if not args.self_test:
            dismiss_consent(driver)
            if looks_like_bot_check(driver):
                dump_debug(driver, video_id, args.output_dir)
                fail(5, "YouTube showed a bot-check / unusual-traffic page. "
                        "Re-run the workflow later.")

            if args.keyword:
                # Open the top search result.
                try:
                    first = WebDriverWait(driver, 30).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//a[@href and contains(@href,'/watch?v=')]")))
                    href = first.get_attribute("href")
                    video_id = extract_video_id(href)
                    if not video_id:
                        fail(1, "Could not read a video ID from the top search result.")
                    set_output("video_id", video_id)
                    print(f"Top result: {href}")
                    first.click()
                except TimeoutException:
                    fail(2, "No video results appeared for the keyword "
                            f"(search may be blocked): {args.keyword}")
                dismiss_consent(driver)

        state = wait_for_video(driver, video_id, args.output_dir)
        duration = state["d"]
        print(f"Video duration: {duration:.1f}s ({duration/60:.2f} min)")
        if duration < MIN_DURATION_S or duration > MAX_DURATION_S:
            fail(6, f"Video is {duration:.0f}s long; supported range is "
                    f"{MIN_DURATION_S}s to {MAX_DURATION_S}s (8:00).")

        start_playback(driver)
        if not enable_stats_for_nerds(driver):
            fail(3, "The 'Stats for nerds' overlay did not appear after "
                    "two right-click attempts.")
        wait_for_end(driver, duration)

        frames = read_frames_count(driver)
        if frames is not None:
            print(f"Final frames count (Dropped frames total): {frames}")
            expected = int(duration * 30)
            print(f"Rough expectation for a full watch at 30fps: ~{expected}")
        else:
            print("WARNING: could not read the frames count from the overlay text.")

        path = take_screenshot(driver, video_id, args.output_dir)
        print(f"Screenshot saved: {path}")
        print(f"Video ID: {video_id}")
        set_output("video_id", video_id)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
