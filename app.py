from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import librosa
import numpy as np
import pandas as pd
import plotly.express as px
import soundfile as sf
import streamlit as st


PITCH_NAMES = ["C", "C♯ / D♭", "D", "D♯ / E♭", "E", "F", "F♯ / G♭", "G", "G♯ / A♭", "A", "A♯ / B♭", "B"]
HINDUSTANI = ["Sa", "komal Re", "Re", "komal Ga", "Ga", "Ma", "tivra Ma", "Pa", "komal Dha", "Dha", "komal Ni", "Ni"]
CARNATIC = ["Sa", "Ri₁", "Ri₂ / Ga₁", "Ri₃ / Ga₂", "Ga₃", "Ma₁", "Ma₂", "Pa", "Da₁", "Da₂ / Ni₁", "Da₃ / Ni₂", "Ni₃"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
MAX_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 20 * 60
SAMPLE_RATE = 22050
RAGA_SCALES = {
    "Mohanam": {0, 2, 4, 7, 9}, "Hamsadhwani": {0, 2, 4, 7, 11},
    "Hindolam": {0, 3, 5, 8, 10}, "Shankarabharanam": {0, 2, 4, 5, 7, 9, 11},
    "Kalyani": {0, 2, 4, 6, 7, 9, 11}, "Kharaharapriya": {0, 2, 3, 5, 7, 9, 10},
    "Mayamalavagowla": {0, 1, 4, 5, 7, 8, 11}, "Charukesi": {0, 2, 4, 5, 7, 8, 10},
    "Keeravani": {0, 2, 3, 5, 7, 8, 11}, "Abheri": {0, 2, 3, 5, 7, 9, 10},
}
FFMPEG_FORMATS = {
    ".mp3": "mp3", ".mp2": "mp3", ".wav": "wav", ".wave": "wav",
    ".flac": "flac", ".m4a": "mov", ".mp4": "mov", ".mov": "mov",
    ".m4v": "mov", ".3gp": "mov", ".3g2": "mov", ".aac": "aac",
    ".ogg": "ogg", ".oga": "ogg", ".ogv": "ogg", ".opus": "ogg",
    ".webm": "matroska", ".mkv": "matroska", ".avi": "avi",
    ".wma": "asf", ".wmv": "asf", ".aif": "aiff", ".aiff": "aiff",
    ".caf": "caf", ".amr": "amr", ".ac3": "ac3", ".flv": "flv",
    ".mpg": "mpeg", ".mpeg": "mpeg", ".vob": "mpeg", ".ts": "mpegts",
    ".mts": "mpegts", ".m2ts": "mpegts", ".mxf": "mxf",
}


@dataclass
class Result:
    duration: float
    times: np.ndarray
    midi: np.ndarray
    confidence: np.ndarray
    counts: np.ndarray
    tonic_pc: int
    key: str
    key_strength: float
    events: list[tuple[float, float, int, float]]


def _detect_container(data: bytes, filename: str) -> str | None:
    """Identify common media containers before asking FFmpeg to open a file path."""
    suffix = Path(filename).suffix.lower()
    if suffix in FFMPEG_FORMATS:
        return FFMPEG_FORMATS[suffix]
    head = data[:64]
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        return "avi"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"OggS"):
        return "ogg"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov"
    if head.startswith(b"\x1aE\xdf\xa3"):
        return "matroska"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    if head.startswith(b"#!AMR"):
        return "amr"
    if head.startswith(b"caff"):
        return "caf"
    if head.startswith(b"FORM") and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head.startswith(b"\x00\x00\x01\xba"):
        return "mpeg"
    return None


def decode_upload(data: bytes, filename: str) -> tuple[np.ndarray, int, bytes]:
    """Decode common audio/video containers with a seekable temp input and network protocols disabled."""
    if not data:
        raise ValueError("That file is empty. Choose a song or a video with sound and try again.")
    if len(data) > MAX_BYTES:
        raise ValueError("This file is larger than 200 MB. Try a shorter song or a smaller audio export.")
    try:
        info = sf.info(io.BytesIO(data))
    except Exception:
        info = None
    if info is not None and info.duration > MAX_SECONDS:
        raise ValueError("This first version supports songs up to 20 minutes. Try a shorter clip.")
    try:
        if info is None:
            raise RuntimeError("No direct soundfile decoder for this format")
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
    except Exception:
        container = _detect_container(data, filename)
        if container is None:
            raise ValueError("I couldn't recognize this as a supported audio or video format. Try MP3, WAV, M4A, FLAC, OGG, AAC, MP4, MOV, MKV, AVI, or WebM.")
        try:
            with tempfile.TemporaryDirectory(prefix="swara_audio_") as temp_dir:
                suffix = Path(filename).suffix.lower()
                if not suffix or len(suffix) > 10 or not suffix[1:].isalnum():
                    suffix = ".media"
                input_path = Path(temp_dir) / f"upload{suffix}"
                input_path.write_bytes(data)
                decoded = subprocess.run(
                    [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
                     "-protocol_whitelist", "file,pipe", "-protocol_blacklist", "http,https,tcp,udp,tls,rtp,rtmp,rtmps,srt",
                     "-f", container, "-i", str(input_path), "-map", "0:a:0", "-vn",
                     "-t", str(MAX_SECONDS + 1), "-ac", "1", "-ar", str(SAMPLE_RATE),
                     "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"],
                    check=True, capture_output=True, timeout=240,
                )
                mono, sr = sf.read(io.BytesIO(decoded.stdout), dtype="float32", always_2d=True)
                mono = mono.mean(axis=1)
        except Exception as exc:
            suffix = filename.rsplit(".", 1)[-1].upper() if "." in filename else "this file"
            raise ValueError(f"I couldn't find a readable audio track in this {suffix} file. Try MP3, WAV, M4A, FLAC, OGG, MP4, MOV, or WebM. Videos need sound; images and documents can't be analyzed as music.") from exc
    if mono.size == 0:
        raise ValueError("The audio track decoded as empty. The file may be damaged or may not contain sound.")
    if len(mono) / sr > MAX_SECONDS:
        raise ValueError("This first version supports songs up to 20 minutes. Try a shorter clip.")
    mono = np.asarray(mono, dtype=np.float32)
    mono = np.nan_to_num(mono, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    if not np.any(np.abs(mono) > 1e-7):
        raise ValueError("The file has an audio track, but it is silent. Try another section or recording.")
    preview = io.BytesIO()
    sf.write(preview, mono, int(sr), format="WAV", subtype="PCM_16")
    return mono, int(sr), preview.getvalue()


def _key_estimate(counts: np.ndarray) -> tuple[str, float]:
    if np.std(counts) < 1e-8:
        return "Unclear", 0.0
    candidates: list[tuple[float, str]] = []
    for root in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            corr = float(np.corrcoef(counts, np.roll(profile, root))[0, 1])
            candidates.append((corr, f"{PITCH_NAMES[root]} {mode}"))
    candidates.sort(reverse=True)
    strength = max(0.0, min(1.0, (candidates[0][0] - candidates[1][0]) * 2.5))
    return candidates[0][1], strength


def analyze(audio: np.ndarray, sr: int) -> Result:
    if sr != SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
        sr = SAMPLE_RATE
    hop = 1024
    f0, voiced, probability = librosa.pyin(
        audio, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
        sr=sr, frame_length=2048, hop_length=hop, fill_na=np.nan,
    )
    all_times = librosa.times_like(f0, sr=sr, hop_length=hop)
    good = np.isfinite(f0) & voiced & (probability >= 0.35)
    if not good.any():
        raise ValueError("I couldn't find a steady melodic pitch. Try a clearer section with a sustained voice or instrument.")
    midi = librosa.hz_to_midi(f0[good])
    times = all_times[good]
    weights = np.nan_to_num(probability[good], nan=0.0)
    pcs = np.mod(np.rint(midi).astype(int), 12)
    weighted_counts = np.bincount(pcs, weights=weights, minlength=12)
    smooth_counts = weighted_counts + 0.25 * np.roll(weighted_counts, 1) + 0.25 * np.roll(weighted_counts, -1)
    tonic_pc = int(np.argmax(smooth_counts))
    key, key_strength = _key_estimate(weighted_counts)

    # Merge nearby frames into approximate note events; tolerate brief vibrato and tiny tracking gaps.
    notes = np.rint(midi).astype(int)
    events: list[tuple[float, float, int, float]] = []
    start = 0
    for idx in range(1, len(notes) + 1):
        split = idx == len(notes) or notes[idx] != notes[start] or times[idx] - times[idx - 1] > 0.18
        if split:
            begin = float(times[start])
            finish = float(times[idx]) if idx < len(times) else float(times[-1] + hop / sr)
            if finish - begin >= 0.10:
                note = int(np.rint(np.median(midi[start:idx])))
                events.append((begin, finish, note, float(np.mean(weights[start:idx]))))
            start = idx
    return Result(len(audio) / sr, times, midi, weights, smooth_counts, tonic_pc, key, key_strength, events)


def note_label(midi: int) -> str:
    return f"{PITCH_NAMES[midi % 12]}{midi // 12 - 1}"


def tonic_label(pc: int) -> str:
    return PITCH_NAMES[pc].split(" /")[0]


def rank_ragas(counts: np.ndarray, tonic_pc: int) -> list[tuple[str, float]]:
    total = float(counts.sum())
    if total <= 0:
        return []
    ranking = []
    observed = {int(i) for i in np.flatnonzero(counts > 0)}
    for name, scale in RAGA_SCALES.items():
        pcs = {(tonic_pc + degree) % 12 for degree in scale}
        explained = sum(float(counts[pc]) for pc in pcs) / total
        coverage = len(pcs & observed) / len(pcs)
        ranking.append((name, 100 * (0.8 * explained + 0.2 * coverage)))
    return sorted(ranking, key=lambda row: row[1], reverse=True)


st.set_page_config(page_title="Swara Music Studio", page_icon="🎼", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --ink:#25254b; --muted:#777899; --violet:#7357f6; --pink:#ff6f9e; --mint:#31c8a2; --paper:#f7f7ff; }
.stApp { background: radial-gradient(ellipse at 5% 0%, #f2eaff 0, transparent 32%), radial-gradient(ellipse at 95% 2%, #e5fffa 0, transparent 28%), #fafaff; color:var(--ink); font-family:'DM Sans',sans-serif; }
header[data-testid="stHeader"] { background:transparent; }
.block-container { max-width:1180px; padding-top:2rem; padding-bottom:4rem; }
h1,h2,h3 { font-family:'Manrope',sans-serif !important; letter-spacing:-.035em; color:var(--ink); }
.hero { border-radius:28px; padding:34px 38px 30px; color:white; background:linear-gradient(115deg,#6551e9 0%,#9371fa 52%,#f07bb2 120%); box-shadow:0 18px 50px #7c65ed30; position:relative; overflow:hidden; animation:rise .55s ease-out both; }
.hero:after { content:'♪'; position:absolute; font-size:190px; color:#ffffff18; right:38px; top:-38px; transform:rotate(12deg); }
.hero h1 { color:white !important; font-size:clamp(2.2rem,5vw,3.6rem); margin:8px 0 5px; }
.hero p { color:#f5f0ff; font-size:1.03rem; margin:0; max-width:660px; }
.eyebrow { color:#e7e0ff; text-transform:uppercase; letter-spacing:.16em; font-weight:700; font-size:.72rem; }
.upload-card { border:1.5px dashed #c9c1ff; border-radius:22px; padding:18px 22px 8px; background:#fff; box-shadow:0 9px 28px #584bd20b; }
.pill { display:inline-block; border-radius:99px; padding:7px 12px; background:#ffffff25; color:white; font-size:.8rem; margin-top:15px; }
.stFileUploader section { border:0 !important; background:transparent !important; }
.stFileUploader [data-testid="stFileUploaderDropzone"] { background:#faf9ff; border:1px dashed #c9c1ff; border-radius:16px; }
.stButton button, .stDownloadButton button { border:0; border-radius:13px; background:linear-gradient(110deg,#6f58f6,#a575fa); color:white; font-weight:700; box-shadow:0 8px 20px #755bf62c; transition:transform .15s, box-shadow .15s; }
.stButton button:hover, .stDownloadButton button:hover { transform:translateY(-2px); box-shadow:0 12px 25px #755bf64a; color:white; }
[data-testid="stMetric"] { background:white; border:1px solid #efedff; border-radius:18px; padding:18px 20px; box-shadow:0 7px 24px #4540730c; }
[data-testid="stMetricValue"] { color:#604ae0; font-family:'Manrope',sans-serif; font-weight:800; }
.stAlert { border-radius:16px; }
.stTabs [data-baseweb="tab-list"] { gap:10px; }
.stTabs [data-baseweb="tab"] { background:#fff; border-radius:12px; padding:10px 18px; }
div[data-testid="stDataFrame"] { border-radius:14px; overflow:hidden; }
.section-label { color:#807b9f; text-transform:uppercase; letter-spacing:.12em; font-size:.74rem; font-weight:700; margin:18px 0 7px; }
.disclaimer { background:#fff9e9; border:1px solid #ffe8ae; padding:14px 18px; border-radius:15px; color:#64552b; font-size:.9rem; }
@keyframes rise { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
@media (prefers-reduced-motion: reduce) { *,*:before,*:after { animation:none !important; transition:none !important; } }
</style>
<div class="hero"><div class="eyebrow">A little music, a lot of color</div><h1>Hear the notes.<br>Find your Sa.</h1><p>Drop in a song or a video with sound. Get a melody map, swara names, a tonic hint, transpose guidance, and a gentle raga shortlist.</p><span class="pill">♫ &nbsp; Your file stays in this app session</span></div>
""", unsafe_allow_html=True)
st.write("")
st.markdown('<div class="upload-card">', unsafe_allow_html=True)
uploaded = st.file_uploader("Choose any file · analysis starts as soon as it is selected", type=None, help="Audio and video files with an audio track can be analyzed. Images and documents are accepted for upload but cannot be analyzed as music.", label_visibility="visible")
st.caption("One selection, no extra upload button. Up to 200 MB · songs up to 20 minutes · sound is analyzed in this app session.")
st.markdown('</div>', unsafe_allow_html=True)

if uploaded is None:
    st.write("")
    col1, col2, col3 = st.columns(3)
    col1.markdown("**🎧 Melody map**  \nNotes with timing, Western pitch, octave, and swara names.")
    col2.markdown("**🎹 Tonic & transpose**  \nAuto-detected Sa with a manual override and semitone shift.")
    col3.markdown("**🌈 Raga ideas**  \nA cautious scale shortlist to explore, with clear limits.")
else:
    file_bytes = uploaded.getvalue()
    signature = hashlib.sha256(file_bytes).hexdigest()
    st.write("")
    st.caption(f"Selected **{uploaded.name}** · {len(file_bytes) / (1024 * 1024):.1f} MB · analyzing once…")
    if st.session_state.get("analysis_signature") != signature:
        try:
            with st.status("Getting your listening room ready…", expanded=True) as status:
                st.write("Reading the audio track from your file")
                audio, rate, preview = decode_upload(file_bytes, uploaded.name)
                st.write("Following the melody and building the note map")
                result = analyze(audio, rate)
                st.session_state["analysis_result"] = result
                st.session_state["audio_preview"] = preview
                st.session_state["analysis_signature"] = signature
                status.update(label="Your song is ready to explore ✨", state="complete", expanded=False)
        except Exception as exc:
            st.session_state.pop("analysis_signature", None)
            st.error(str(exc) if isinstance(exc, ValueError) else f"I couldn't finish that analysis: {exc}")
            st.stop()
    result: Result = st.session_state["analysis_result"]
    st.audio(st.session_state["audio_preview"], format="audio/wav")
    duration = result.duration
    st.caption(f"{duration // 60:.0f}:{duration % 60:04.1f} long · melodic pitch tracking is an estimate")

    tonic_pc = result.tonic_pc
    tonics = [name.split(" /")[0] for name in PITCH_NAMES]
    with st.expander("Know the Sa? Set it here for better swara and raga suggestions", expanded=False):
        selected = st.selectbox("Tonic / Sa", tonics, index=tonic_pc, key=f"tonic_{signature}")
        tonic_pc = tonics.index(selected)
        swara_style = st.radio("Swara names", ["Hindustani · Sa Re Ga Ma Pa", "Carnatic · swara positions"], horizontal=True)
    swaras = HINDUSTANI if swara_style.startswith("Hindustani") else CARNATIC
    top_raga = rank_ragas(result.counts, tonic_pc)
    key_strength = "more distinct" if result.key_strength >= .35 else "uncertain"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tonic hint / Sa", tonics[tonic_pc], "automatic estimate · confirm by ear")
    c2.metric("Likely Western key", result.key, f"profile match · {key_strength}")
    c3.metric("Note events", f"{len(result.events):,}", "approximate melodic notes")
    c4.metric("Top scale match", top_raga[0][0] if top_raga else "—", "exploratory shortlist")

    tab_notes, tab_raga, tab_transpose = st.tabs(["🎶  Note journey", "🌺  Raga shortlist", "🎛️  Transpose"])
    with tab_notes:
        if result.events:
            note_rows = []
            for start, end, note, confidence in result.events:
                octave = note // 12 - 1
                pc = note % 12
                degree = (pc - tonic_pc) % 12
                octave_label = "lower" if octave < 4 else ("higher" if octave > 4 else "middle")
                note_rows.append({"From": f"{start:0.2f}s", "To": f"{end:0.2f}s", "Time": round(end - start, 2), "Western note": note_label(note), "Swara from Sa": f"{swaras[degree]} · {octave_label} octave", "Pitch confidence": f"{confidence:.0%}"})
            notes_df = pd.DataFrame(note_rows)
            st.dataframe(notes_df, hide_index=True, use_container_width=True, height=390)
            csv = notes_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ Download note map · CSV", csv, file_name="svara-note-map.csv", mime="text/csv")
        else:
            st.info("No steady note events were long enough to list. Try a clearer melody section.")
        st.markdown('<div class="section-label">Pitch-class colors</div>', unsafe_allow_html=True)
        pitch_df = pd.DataFrame({"Pitch": PITCH_NAMES, "Detected prominence": result.counts, "Swara": [swaras[(i - tonic_pc) % 12] for i in range(12)]})
        fig = px.bar(pitch_df, x="Pitch", y="Detected prominence", color="Detected prominence", color_continuous_scale=["#d9d2ff", "#7357f6", "#ff79ae"], hover_data=["Swara"])
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=15, b=10), coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis_title=None)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Swara labels are semitone positions relative to Sa; gamakas, tuning bends, and microtones are simplified to nearby notes.")
    with tab_raga:
        st.markdown('<div class="disclaimer">These are <b>scale resemblance hints</b>, not raga identification or calibrated confidence. Raga identity depends on characteristic phrases, movement rules, ornamentation, and musical context that this pitch-only version does not understand.</div>', unsafe_allow_html=True)
        raga_df = pd.DataFrame(top_raga[:5], columns=["Raga scale", "Scale resemblance · heuristic"])
        if not raga_df.empty:
            raga_df["Scale resemblance · heuristic"] = raga_df["Scale resemblance · heuristic"].map(lambda score: f"{score:.0f}%")
            st.dataframe(raga_df, hide_index=True, use_container_width=True)
        st.caption(f"Shortlist uses **{tonics[tonic_pc]} as Sa**. Confirm or change the tonic above. The built-in catalog currently has ten scales; a strong-looking match still needs listening and expert confirmation.")
    with tab_transpose:
        st.write("Choose the Sa you want. The app calculates the semitone shift from your selected tonic.")
        target = st.selectbox("Target Sa", tonics, index=tonic_pc, key=f"target_{signature}")
        delta = (tonics.index(target) - tonic_pc + 6) % 12 - 6
        if delta == 0:
            st.success(f"You're already at {target} Sa. No shift needed.")
        else:
            direction = "up" if delta > 0 else "down"
            st.success(f"Shift the song {abs(delta)} semitone(s) {direction} to move {tonics[tonic_pc]} Sa to {target} Sa.")
        st.caption("This is transposition guidance only. The app does not alter or export a shifted song.")

st.divider()
st.markdown('<div class="disclaimer"><b>A kind note about accuracy:</b> the note map is a best-effort melody estimate, and key / Sa can be fooled by accompaniment, percussion, tuning, or polyphonic recordings. Raga suggestions are a small scale-based shortlist; perfect raga identification needs a validated model and musical phrase analysis. Any file type can be selected, but only files with readable audio can be analyzed.</div>', unsafe_allow_html=True)
st.caption("Swara Music Studio · a friendly first version for musical exploration · your uploaded song is processed in the app session and not saved as a project file.")
