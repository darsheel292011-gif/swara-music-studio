# Swara Music Studio

A colorful, beginner-friendly Python music analyzer built with Streamlit. Choose an audio file or a video with sound and the app starts analyzing as soon as the file is selected. There is no second upload button. The file is sent to the Streamlit app to be analyzed; the app does not save it as a project file.

## What it does

- Accepts any file selection, then checks whether the file has a readable audio track.
- Reads common audio formats with `soundfile` and uses bundled FFmpeg through a restricted pipe for compressed formats and videos.
- Estimates a tonic (Sa) and a Western major/minor key.
- Lists approximate melody notes with start/end time, Western note name, octave, pitch confidence, and Hindustani or Carnatic swara labels relative to Sa.
- Provides a small, experimental raga scale shortlist and a semitone transpose suggestion.
- Exports the note table as CSV.

## Limits to know

Any file type can be selected so that the app can give a clear answer for unsupported files. A document or image has no song audio to analyze; a video must include an audio track and use a codec supported by FFmpeg. This version supports files up to 200 MB and songs up to 20 minutes. The uploader sends the file to the hosting service for processing, so only upload recordings you are comfortable processing there.

Pitch tracking is an estimate. Polyphonic music, percussion, strong accompaniment, tuning differences, and ornamentation can confuse the melody, key, or tonic. Raga suggestions are scale resemblance hints, not calibrated confidence or perfect identification. A raga is defined by characteristic phrases, note movement, ornamentation, and musical context as well as its scale; this starter app does not analyze those features. Transpose guidance reports semitones and does not produce a modified audio file.

## Run on Windows 11

Install Python 3.11 (64-bit), then open PowerShell in this project folder and run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

If PowerShell blocks activation, run this once in that terminal and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Publish for free

GitHub stores the project files. GitHub Pages serves static sites and cannot run this Python app by itself. To get a public, free website, put the code on GitHub and connect the repository to Streamlit Community Cloud.

1. Create a new GitHub repository, such as `swara-music-studio`.
2. Open PowerShell in this folder and run:

   ```powershell
   git init
   git add app.py README.md requirements.txt .gitignore .streamlit/config.toml
   git commit -m "Create Swara Music Studio analyzer"
   git branch -M main
   ```

3. On the new GitHub repository page, copy its HTTPS URL. Back in PowerShell, run `git remote add origin PASTE-THE-URL-HERE` and `git push -u origin main`.
4. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) with GitHub, create an app, select the new repository and `main` branch, and set the app file to `app.py`.
5. Streamlit provides a public `*.streamlit.app` address when deployment finishes.

The public app runs on the hosting service, so song uploads are sent to that service for analysis. Do not upload private recordings unless you are comfortable with that processing.
