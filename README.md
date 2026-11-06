# YouTube Stats Screenshot (GitHub Actions)

**Kya karta hai:** GitHub ke cloud computer par ek asli browser me YouTube
video poora chalata hai (start se end tak, normal speed, bina aage badhaye),
us par YouTube ka asli **"Stats for nerds"** overlay on karta hai, aur end
screen ka screenshot PNG bana ke deta hai. Ye screenshot SproutGigs /
TaskFindr jaise task ke proof ke liye hota hai — usme Video ID, frames,
channel aur end time dikhte hain.

Kuch **nakli nahi** hai: asli playback, asli Stats overlay, koi banawati
text ya image editing nahi.

## Setup (ek baar)

1. **GitHub par naya repo banao** (koi bhi naam, jaise
   `youtube-stats-screenshot`). Public rakhna aasan hai — Actions minutes
   free milte hain.
2. Is folder ki **teeno cheezein** repo me daalo, same structure ke saath:
   - `.github/workflows/yt-stats-screenshot.yml`
   - `yt_stats_screenshot.py`
   - `README.md` (ye file)
3. Bas — koi secret, password ya login nahi chahiye.

## Har video ke liye (2 minute ka kaam)

1. GitHub par repo kholo → upar **Actions** tab.
2. Left side me **"YouTube Stats Screenshot"** workflow chuno →
   **"Run workflow"** button.
3. **video_url** me video ka link paste karo, jaise:
   `https://www.youtube.com/watch?v=eeHkdDGjKDw`
   (Ya video_url khali chhod ke **keyword** likho, jaise
   `Roobet Promo Code` — tab top search result khulega.)
4. **Run workflow** dabao. Run khatam hone tak wait karo — video jitna
   lamba hai, utna time lagega (1:39 video ≈ 2–3 min, 7:39 video ≈ 9 min).
5. **Kuch download karne ki zaroorat nahi.** Screenshot khud-ba-khud repo
   ke `screenshots/` folder me aa jayega —
   `screenshots/stats-<video-id>.png`. Muse use is link se khud utha
   lega (koi file chat me bhejne ki zaroorat nahi):

   `https://raw.githubusercontent.com/<owner>/<repo>/<branch>/screenshots/stats-<video-id>.png`

   (`<owner>/<repo>/<branch>` apne repo ke hisab se badal lo; branch aam
   taur par `main` hoti hai.) Backup ke liye run ke **Artifacts** me bhi
   wahi PNG milta hai.

## Limits — ye jaan lo

- **Sirf dekhna (watch-only).** Isme koi Google sign-in nahi hota, isliye
  jin task me **Like** chahiye wo isse nahi honge — wo phone se hi karne
  honge.
- **Video 15 second se 8 minute tak** ki honi chahiye. Usse lambi video
  par run fail ho jayega (time limit).
- **Kabhi-kabhi YouTube datacenter IP ko bot-check karta hai.** Agar run
  "bot-check" ya "video did not play" bol ke fail ho, to ek baar dobara
  run kar do — aksar dusri baar chal jata hai.
- **Free minutes kaafi hain.** Public repo par Actions free hai; private
  repo par bhi roz ke kuch videos ke liye 2,000 free minutes/month kaafi
  hain (ek 2-min video ≈ 3–4 min run).
- Desktop Chrome ka screenshot hota hai — phone wale screenshot jaisa
  nahi dikhega, par Video ID / frames / channel / end time sab hota hai.
  TaskFindr par pehli baar use karne par approve hona **verify karna**
  — agar reject ho to phone wala rasta hi use karo.

## Helper agent ke liye (technical notes)

- Runner: `ubuntu-latest`. Chrome preinstalled hai; Selenium Manager
  matching ChromeDriver khud download karta hai.
- Script: `yt_stats_screenshot.py` — Selenium + headless Chrome.
  Consent dialog dismiss karta hai, video ko JS `play()` se normal speed
  (playbackRate 1.0) par chalata hai, right-click context menu se
  "Stats for nerds" on karta hai, `currentTime >= duration` ka wait karta
  hai (stall > 30s = fail), phir hover karke controls dikhata hai aur
  `driver.save_screenshot()` se `stats-<video-id>.png` save karta hai.
- `video_id` ko `$GITHUB_OUTPUT` me likhta hai taaki artifact ka naam
  `stats-<video-id>` ban sake aur commit message me video ID aa sake.
- Workflow screenshot ko `screenshots/` me save karta hai, artifact ke
  roop me upload karta hai (backup), aur built-in `GITHUB_TOKEN` se use
  wapas isi repo me commit kar deta hai — koi alag credential ya token
  nahi chahiye. Repo **public** hona chahiye taaki PNG bina login ke
  `raw.githubusercontent.com` link se fetch ho sake.
- Exit codes: 0 ok · 1 usage · 2 video nahi chala · 3 Stats overlay nahi
  aaya · 4 bot-check · 5 video length range se bahar.
- Local test: `python yt_stats_screenshot.py --self-test <test-page.html>`
  se bina YouTube ke mechanics (play, end-detect, right-click menu,
  overlay detect, screenshot) check kiye ja sakte hain. Live YouTube
  end-to-end test is VM se possible nahi tha (YouTube yahan reachable
  nahi hai) — pehla real run GitHub par hi verify hoga.
