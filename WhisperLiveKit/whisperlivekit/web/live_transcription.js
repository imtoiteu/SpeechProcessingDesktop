const isExtension = typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.getURL;
if (isExtension) {
  document.documentElement.classList.add('is-extension');
}
const isWebContext = !isExtension;

let isRecording = false;
let websocket = null;
let recorder = null;
let chunkDuration = 100;
let websocketUrl = "ws://localhost:8000/asr";
let userClosing = false;
let wakeLock = null;
let startTime = null;
let timerInterval = null;
let audioContext = null;
let analyser = null;
let microphone = null;
let workletNode = null;
let recorderWorker = null;
let waveCanvas = document.getElementById("waveCanvas");
let waveCtx = waveCanvas.getContext("2d");
let animationFrame = null;
let waitingForStop = false;
let lastReceivedData = null;
let lastSignature = null;
let availableMicrophones = [];
let selectedMicrophoneId = null;
let serverUseAudioWorklet = null;
let configReadyResolve;
const configReady = new Promise((r) => (configReadyResolve = r));
let outputAudioContext = null;
let audioSource = null;

waveCanvas.width = 60 * (window.devicePixelRatio || 1);
waveCanvas.height = 30 * (window.devicePixelRatio || 1);
waveCtx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

const statusText = document.getElementById("status");
const recordButton = document.getElementById("recordButton");
const chunkSelector = document.getElementById("chunkSelector");
const websocketInput = document.getElementById("websocketInput");
const websocketDefaultSpan = document.getElementById("wsDefaultUrl");
const linesTranscriptDiv = document.getElementById("linesTranscript");
const timerElement = document.querySelector(".timer");
const themeRadios = document.querySelectorAll('input[name="theme"]');
const microphoneSelect = document.getElementById("microphoneSelect");

const settingsToggle = document.getElementById("settingsToggle");
const settingsDiv = document.querySelector(".settings");

// if (isExtension) {
//   chrome.runtime.onInstalled.addListener((details) => {
//     if (details.reason.search(/install/g) === -1) {
//       return;
//     }
//     chrome.tabs.create({
//       url: chrome.runtime.getURL("welcome.html"),
//       active: true
//     });
//   });
// }

const translationIcon = `<svg xmlns="http://www.w3.org/2000/svg" height="12px" viewBox="0 -960 960 960" width="12px" fill="#5f6368"><path d="m603-202-34 97q-4 11-14 18t-22 7q-20 0-32.5-16.5T496-133l152-402q5-11 15-18t22-7h30q12 0 22 7t15 18l152 403q8 19-4 35.5T868-80q-13 0-22.5-7T831-106l-34-96H603ZM362-401 188-228q-11 11-27.5 11.5T132-228q-11-11-11-28t11-28l174-174q-35-35-63.5-80T190-640h84q20 39 40 68t48 58q33-33 68.5-92.5T484-720H80q-17 0-28.5-11.5T40-760q0-17 11.5-28.5T80-800h240v-40q0-17 11.5-28.5T360-880q17 0 28.5 11.5T400-840v40h240q17 0 28.5 11.5T680-760q0 17-11.5 28.5T640-720h-76q-21 72-63 148t-83 116l96 98-30 82-122-125Zm266 129h144l-72-204-72 204Z"/></svg>`
const silenceIcon = `<svg xmlns="http://www.w3.org/2000/svg" style="vertical-align: text-bottom;" height="14px" viewBox="0 -960 960 960" width="14px" fill="#5f6368"><path d="M514-556 320-752q9-3 19-5.5t21-2.5q66 0 113 47t47 113q0 11-1.5 22t-4.5 22ZM40-200v-32q0-33 17-62t47-44q51-26 115-44t141-18q26 0 49.5 2.5T456-392l-56-54q-9 3-19 4.5t-21 1.5q-66 0-113-47t-47-113q0-11 1.5-21t4.5-19L84-764q-11-11-11-28t11-28q12-12 28.5-12t27.5 12l675 685q11 11 11.5 27.5T816-80q-11 13-28 12.5T759-80L641-200h39q0 33-23.5 56.5T600-120H120q-33 0-56.5-23.5T40-200Zm80 0h480v-32q0-14-4.5-19.5T580-266q-36-18-92.5-36T360-320q-71 0-127.5 18T140-266q-9 5-14.5 14t-5.5 20v32Zm240 0Zm560-400q0 69-24.5 131.5T829-355q-12 14-30 15t-32-13q-13-13-12-31t12-33q30-38 46.5-85t16.5-98q0-51-16.5-97T767-781q-12-15-12.5-33t12.5-32q13-14 31.5-13.5T829-845q42 51 66.5 113.5T920-600Zm-182 0q0 32-10 61.5T700-484q-11 15-29.5 15.5T638-482q-13-13-13.5-31.5T633-549q6-11 9.5-24t3.5-27q0-14-3.5-27t-9.5-25q-9-17-8.5-35t13.5-31q14-14 32.5-13.5T700-716q18 25 28 54.5t10 61.5Z"/></svg>`;
const languageIcon = `<svg xmlns="http://www.w3.org/2000/svg" height="12" viewBox="0 -960 960 960" width="12" fill="#5f6368"><path d="M480-80q-82 0-155-31.5t-127.5-86Q143-252 111.5-325T80-480q0-83 31.5-155.5t86-127Q252-817 325-848.5T480-880q83 0 155.5 31.5t127 86q54.5 54.5 86 127T880-480q0 82-31.5 155t-86 127.5q-54.5 54.5-127 86T480-80Zm0-82q26-36 45-75t31-83H404q12 44 31 83t45 75Zm-104-16q-18-33-31.5-68.5T322-320H204q29 50 72.5 87t99.5 55Zm208 0q56-18 99.5-55t72.5-87H638q-9 38-22.5 73.5T584-178ZM170-400h136q-3-20-4.5-39.5T300-480q0-21 1.5-40.5T306-560H170q-5 20-7.5 39.5T160-480q0 21 2.5 40.5T170-400Zm216 0h188q3-20 4.5-39.5T580-480q0-21-1.5-40.5T574-560H386q-3 20-4.5 39.5T380-480q0 21 1.5 40.5T386-400Zm268 0h136q5-20 7.5-39.5T800-480q0-21-2.5-40.5T790-560H654q3 20 4.5 39.5T660-480q0 21-1.5 40.5T654-400Zm-16-240h118q-29-50-72.5-87T584-782q18 33 31.5 68.5T638-640Zm-234 0h152q-12-44-31-83t-45-75q-26 36-45 75t-31 83Zm-200 0h118q9-38 22.5-73.5T376-782q-56 18-99.5 55T204-640Z"/></svg>`
const speakerIcon = `<svg xmlns="http://www.w3.org/2000/svg" height="16px" style="vertical-align: text-bottom;" viewBox="0 -960 960 960" width="16px" fill="#5f6368"><path d="M480-480q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 66-47 113t-113 47ZM160-240v-32q0-34 17.5-62.5T224-378q62-31 126-46.5T480-440q66 0 130 15.5T736-378q29 15 46.5 43.5T800-272v32q0 33-23.5 56.5T720-160H240q-33 0-56.5-23.5T160-240Zm80 0h480v-32q0-11-5.5-20T700-306q-54-27-109-40.5T480-360q-56 0-111 13.5T260-306q-9 5-14.5 14t-5.5 20v32Zm240-320q33 0 56.5-23.5T560-640q0-33-23.5-56.5T480-720q-33 0-56.5 23.5T400-640q0 33 23.5 56.5T480-560Zm0-80Zm0 400Z"/></svg>`;

function getWaveStroke() {
  const styles = getComputedStyle(document.documentElement);
  const v = styles.getPropertyValue("--wave-stroke").trim();
  return v || "#000";
}

let waveStroke = getWaveStroke();
function updateWaveStroke() {
  waveStroke = getWaveStroke();
}

function applyTheme(pref) {
  if (pref === "light") {
    document.documentElement.setAttribute("data-theme", "light");
  } else if (pref === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  updateWaveStroke();
}

// Persisted theme preference
const savedThemePref = localStorage.getItem("themePreference") || "system";
applyTheme(savedThemePref);
if (themeRadios.length) {
  themeRadios.forEach((r) => {
    r.checked = r.value === savedThemePref;
    r.addEventListener("change", () => {
      if (r.checked) {
        localStorage.setItem("themePreference", r.value);
        applyTheme(r.value);
      }
    });
  });
}

// React to OS theme changes when in "system" mode
const darkMq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
const handleOsThemeChange = () => {
  const pref = localStorage.getItem("themePreference") || "system";
  if (pref === "system") updateWaveStroke();
};
if (darkMq && darkMq.addEventListener) {
  darkMq.addEventListener("change", handleOsThemeChange);
} else if (darkMq && darkMq.addListener) {
  // deprecated, but included for Safari compatibility
  darkMq.addListener(handleOsThemeChange);
}

async function enumerateMicrophones() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(track => track.stop());

    const devices = await navigator.mediaDevices.enumerateDevices();
    availableMicrophones = devices.filter(device => device.kind === 'audioinput');

    populateMicrophoneSelect();
    console.log(`Found ${availableMicrophones.length} microphone(s)`);
  } catch (error) {
    console.error('Error enumerating microphones:', error);
    statusText.textContent = "Error accessing microphones. Please grant permission.";
  }
}

function populateMicrophoneSelect() {
  if (!microphoneSelect) return;

  microphoneSelect.innerHTML = '<option value="">Default Microphone</option>';

  availableMicrophones.forEach((device, index) => {
    const option = document.createElement('option');
    option.value = device.deviceId;
    option.textContent = device.label || `Microphone ${index + 1}`;
    microphoneSelect.appendChild(option);
  });

  const savedMicId = localStorage.getItem('selectedMicrophone');
  if (savedMicId && availableMicrophones.some(mic => mic.deviceId === savedMicId)) {
    microphoneSelect.value = savedMicId;
    selectedMicrophoneId = savedMicId;
  }
}

function handleMicrophoneChange() {
  selectedMicrophoneId = microphoneSelect.value || null;
  localStorage.setItem('selectedMicrophone', selectedMicrophoneId || '');

  const selectedDevice = availableMicrophones.find(mic => mic.deviceId === selectedMicrophoneId);
  const deviceName = selectedDevice ? selectedDevice.label : 'Default Microphone';

  console.log(`Selected microphone: ${deviceName}`);
  statusText.textContent = `Microphone changed to: ${deviceName}`;

  if (isRecording) {
    statusText.textContent = "Switching microphone... Please wait.";
    stopRecording().then(() => {
      setTimeout(() => {
        toggleRecording();
      }, 1000);
    });
  }
}

// Helpers
function fmt1(x) {
  const n = Number(x);
  return Number.isFinite(n) ? n.toFixed(1) : x;
}

let host, port, protocol;
port = 8000;
if (isExtension) {
    host = "localhost";
    protocol = "ws";
} else {
    host = window.location.hostname || "localhost";
    port = window.location.port;
    protocol = window.location.protocol === "https:" ? "wss" : "ws";
}
const defaultWebSocketUrl = `${protocol}://${host}${port ? ":" + port : ""}/asr`;

// Populate default caption and input
if (websocketDefaultSpan) websocketDefaultSpan.textContent = defaultWebSocketUrl;
websocketInput.value = defaultWebSocketUrl;
websocketUrl = defaultWebSocketUrl;

// Optional chunk selector (guard for presence)
if (chunkSelector) {
  chunkSelector.addEventListener("change", () => {
    chunkDuration = parseInt(chunkSelector.value);
  });
}

// WebSocket input change handling
websocketInput.addEventListener("change", () => {
  const urlValue = websocketInput.value.trim();
  if (!urlValue.startsWith("ws://") && !urlValue.startsWith("wss://")) {
    statusText.textContent = "Invalid WebSocket URL (must start with ws:// or wss://)";
    return;
  }
  websocketUrl = urlValue;
  statusText.textContent = "WebSocket URL updated. Ready to connect.";
});

function setupWebSocket(urlOverride) {
  return new Promise((resolve, reject) => {
    const url = urlOverride || websocketUrl;
    try {
      websocket = new WebSocket(url);
    } catch (error) {
      statusText.textContent = "Invalid WebSocket URL. Please check and try again.";
      reject(error);
      return;
    }

    websocket.onopen = () => {
      statusText.textContent = "Connected to server.";
      resolve();
    };

    websocket.onclose = () => {
      if (userClosing) {
        if (waitingForStop) {
          statusText.textContent = "Processing finalized or connection closed.";
          if (lastReceivedData) {
          renderLinesWithBuffer(
              getStoreLines(),
              lastReceivedData.buffer_diarization || "",
              lastReceivedData.buffer_transcription || "",
              lastReceivedData.buffer_translation || "",
              0,
              0,
              true
            );
          }
        }
      } else {
        statusText.textContent = "Disconnected from the WebSocket server. (Check logs if model is loading.)";
        if (isRecording) {
          stopRecording();
        }
      }
      isRecording = false;
      waitingForStop = false;
      userClosing = false;
      lastReceivedData = null;
      websocket = null;
      updateUI();
    };

    websocket.onerror = () => {
      statusText.textContent = "Error connecting to WebSocket.";
      reject(new Error("Error connecting to WebSocket"));
    };

    websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "config") {
        serverUseAudioWorklet = !!data.useAudioWorklet;
        statusText.textContent = serverUseAudioWorklet
          ? "Connected. Using AudioWorklet (PCM)."
          : "Connected. Using MediaRecorder (WebM).";
        if (configReadyResolve) configReadyResolve();
        return;
      }

      // Ignore diff/snapshot messages — the default frontend uses full-state mode.
      // These are only sent when a client explicitly opts in via ?mode=diff.
      if (data.type === "diff" || data.type === "snapshot") {
        console.warn("Received diff-protocol message but frontend is in full mode; ignoring.", data.type);
        return;
      }

      // Server-side error (e.g. /asr/file ffmpeg decode failure).
      if (data.type === "error") {
        statusText.textContent = "Server error: " + (data.message || "transcription failed");
        console.error("Server error message:", data.message);
        return;
      }

      if (data.type === "ready_to_stop") {
        console.log("Ready to stop received, finalizing display and closing WebSocket.");
        waitingForStop = false;

        if (lastReceivedData) {
          renderLinesWithBuffer(
            getStoreLines(),
            lastReceivedData.buffer_diarization || "",
            lastReceivedData.buffer_transcription || "",
            lastReceivedData.buffer_translation || "",
            0,
            0,
            true
          );
        }
        statusText.textContent = "Finished processing audio! Ready to record again.";
        recordButton.disabled = false;

        if (websocket) {
          websocket.close();
        }
        return;
      }

      lastReceivedData = data;

      const {
        lines = [],
        buffer_transcription = "",
        buffer_diarization = "",
        buffer_translation = "",
        remaining_time_transcription = 0,
        remaining_time_diarization = 0,
        status = "active_transcription",
      } = data;

      // Accumulate committed lines client-side: the server prunes its state to a
      // ~5-minute window, so we must keep our own running transcript (mic + file).
      upsertLines(lines);

      renderLinesWithBuffer(
        getStoreLines(),
        buffer_diarization,
        buffer_transcription,
        buffer_translation,
        remaining_time_diarization,
        remaining_time_transcription,
        false,
        status
      );
    };
  });
}

function renderLinesWithBuffer(
  lines,
  buffer_diarization,
  buffer_transcription,
  buffer_translation,
  remaining_time_diarization,
  remaining_time_transcription,
  isFinalizing = false,
  current_status = "active_transcription"
) {
  if (current_status === "no_audio_detected" && (!lines || lines.length === 0)) {
    linesTranscriptDiv.innerHTML =
      "<p style='text-align: center; color: var(--muted); margin-top: 20px;'><em>No audio detected...</em></p>";
    return;
  }

  const showLoading = !isFinalizing && (lines || []).some((it) => it.speaker == 0);
  const showTransLag = !isFinalizing && remaining_time_transcription > 0;
  const showDiaLag = !isFinalizing && !!buffer_diarization && remaining_time_diarization > 0;
  const signature = JSON.stringify({
    lines: (lines || []).map((it) => ({ speaker: it.speaker, text: it.text, start: it.start, end: it.end, detected_language: it.detected_language })),
    buffer_transcription: buffer_transcription || "",
    buffer_diarization: buffer_diarization || "",
    buffer_translation: buffer_translation,
    status: current_status,
    showLoading,
    showTransLag,
    showDiaLag,
    isFinalizing: !!isFinalizing,
  });
  if (lastSignature === signature) {
    const t = document.querySelector(".lag-transcription-value");
    if (t) t.textContent = fmt1(remaining_time_transcription);
    const d = document.querySelector(".lag-diarization-value");
    if (d) d.textContent = fmt1(remaining_time_diarization);
    const ld = document.querySelector(".loading-diarization-value");
    if (ld) ld.textContent = fmt1(remaining_time_diarization);
    return;
  }
  lastSignature = signature;

  // -------- strict segment model --------------------------------------
  // Render the transcript as discrete segments: each visible timestamp owns
  // exactly one text block. Drop silence/loading/empty entries so there are
  // never orphan timestamps or untimed text blocks (rules 1-3).
  const allLines = lines || [];
  const segments = allLines.filter(
    (it) => it && it.speaker !== -2 && it.speaker !== 0 &&
            it.text != null && String(it.text).trim().length > 0
  );

  const bufTrans = (buffer_transcription || "").trim();
  const bufDia = (buffer_diarization || "").trim();
  const bufTrl = (buffer_translation || "").trim();
  const hasBuffer = bufTrans.length > 0 || bufDia.length > 0;

  if (segments.length === 0 && !hasBuffer) {
    linesTranscriptDiv.innerHTML = isFinalizing
      ? ""
      : "<p class='transcript-empty'><em>Listening…</em></p>";
    return;
  }

  const multiSpeaker = new Set(segments.map((s) => s.speaker)).size > 1;
  const blocks = [];
  let prevSpeaker = null;
  let prevLang = null;

  segments.forEach((item, idx) => {
    const isLast = idx === segments.length - 1;

    // One timestamp chip per segment (click-to-seek unchanged: .ts-chip + data-s).
    const startStr = (item.start !== undefined && item.start !== null)
      ? item.start : formatTime(item.start_s);
    const sec = (item.start_s !== undefined && item.start_s !== null)
      ? item.start_s : parseTimeStr(item.start);
    const chip = `<span class="ts-chip" data-s="${sec}" title="Seek media to ${startStr}">${escapeHtml(startStr)}</span>`;

    // Low-noise badges, shown only when they change vs the previous segment.
    let meta = "";
    if (multiSpeaker && item.speaker !== prevSpeaker) {
      meta += `<span class="seg-speaker">${speakerIcon}<span class="speaker-badge">${item.speaker}</span></span>`;
    }
    if (item.detected_language && item.detected_language !== prevLang) {
      meta += `<span class="label_language">${languageIcon}<span>${escapeHtml(item.detected_language)}</span></span>`;
    }
    prevSpeaker = item.speaker;
    if (item.detected_language) prevLang = item.detected_language;

    // Committed text (escaped). The live buffer belongs to the last segment
    // only, so streaming text always stays under a timestamp (rules 3 + 7).
    let textHtml = escapeHtml(String(item.text).trim());
    if (isLast) {
      if (isFinalizing) {
        const tail = [bufDia, bufTrans].filter(Boolean).join(" ");
        if (tail) textHtml += " " + escapeHtml(tail);
      } else {
        if (bufDia) textHtml += ` <span class="buffer_diarization">${escapeHtml(bufDia)}</span>`;
        if (bufTrans) textHtml += ` <span class="buffer_transcription">${escapeHtml(bufTrans)}</span>`;
      }
    }

    // Optional translation sub-line (only when translation is in use).
    let translation = item.translation ? escapeHtml(item.translation.trim()) : "";
    if (isLast && bufTrl) {
      translation += (translation ? " " : "") +
        `<span class="buffer_translation">${escapeHtml(bufTrl)}</span>`;
    }
    const translationHtml = translation
      ? `<div class="segment-translation">${translationIcon}<span>${translation}</span></div>`
      : "";

    // Streaming lag hint on the active segment (a status badge, not a text block).
    let lagHtml = "";
    if (isLast && !isFinalizing && remaining_time_transcription > 0) {
      lagHtml = `<span class="seg-lag"><span class="spinner"></span>` +
        `<span class="lag-transcription-value">${fmt1(remaining_time_transcription)}</span>s</span>`;
    }

    blocks.push(
      `<div class="segment">` +
        `<div class="segment-time">${chip}${meta}${lagHtml}</div>` +
        `<div class="segment-text">${textHtml}</div>` +
        translationHtml +
      `</div>`
    );
  });

  // No committed segment yet but buffer text exists: show it under a 0:00 chip
  // so there is never an untimed text block.
  if (segments.length === 0 && hasBuffer) {
    const tail = [bufDia, bufTrans].filter(Boolean).join(" ");
    blocks.push(
      `<div class="segment">` +
        `<div class="segment-time">` +
          `<span class="ts-chip" data-s="0" title="Seek media to 0:00:00.00">0:00:00.00</span>` +
        `</div>` +
        `<div class="segment-text"><span class="buffer_transcription">${escapeHtml(tail)}</span></div>` +
      `</div>`
    );
  }

  const linesHtml = blocks.join("");

  // Preserve auto-scroll, but only when the user is already near the bottom, so
  // scrolling up to read a long transcript isn't yanked back on each update.
  const transcriptContainer = document.querySelector(".transcript-container");
  const nearBottom = transcriptContainer
    ? (transcriptContainer.scrollHeight - transcriptContainer.scrollTop - transcriptContainer.clientHeight) < 120
    : true;
  linesTranscriptDiv.innerHTML = linesHtml;
  if (transcriptContainer && nearBottom) {
    transcriptContainer.scrollTo({ top: transcriptContainer.scrollHeight, behavior: "smooth" });
  }
}

function updateTimer() {
  if (!startTime) return;

  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const minutes = Math.floor(elapsed / 60).toString().padStart(2, "0");
  const seconds = (elapsed % 60).toString().padStart(2, "0");
  timerElement.textContent = `${minutes}:${seconds}`;
}

function drawWaveform() {
  if (!analyser) return;

  const bufferLength = analyser.frequencyBinCount;
  const dataArray = new Uint8Array(bufferLength);
  analyser.getByteTimeDomainData(dataArray);

  waveCtx.clearRect(
    0,
    0,
    waveCanvas.width / (window.devicePixelRatio || 1),
    waveCanvas.height / (window.devicePixelRatio || 1)
  );
  waveCtx.lineWidth = 1;
  waveCtx.strokeStyle = waveStroke;
  waveCtx.beginPath();

  const sliceWidth = (waveCanvas.width / (window.devicePixelRatio || 1)) / bufferLength;
  let x = 0;

  for (let i = 0; i < bufferLength; i++) {
    const v = dataArray[i] / 128.0;
    const y = (v * (waveCanvas.height / (window.devicePixelRatio || 1))) / 2;

    if (i === 0) {
      waveCtx.moveTo(x, y);
    } else {
      waveCtx.lineTo(x, y);
    }

    x += sliceWidth;
  }

  waveCtx.lineTo(
    waveCanvas.width / (window.devicePixelRatio || 1),
    (waveCanvas.height / (window.devicePixelRatio || 1)) / 2
  );
  waveCtx.stroke();

  animationFrame = requestAnimationFrame(drawWaveform);
}

async function startRecording() {
  try {
    resetTranscriptStore();
    // A mic recording becomes the single active source: abandon any pending
    // file selection and remove its stale preview so the player/timestamps
    // cannot point at a different asset than the (upcoming) mic transcript.
    selectedFile = null;
    updateStartEnabled();
    resetMicCapture();
    clearActiveMedia("mic");
    try {
      wakeLock = await navigator.wakeLock.request("screen");
    } catch (err) {
      console.log("Error acquiring wake lock.");
    }

    let stream;
    
    // chromium extension. in the future, both chrome page audio and mic will be used
    if (isExtension) {
      try {
        stream = await new Promise((resolve, reject) => {
          chrome.tabCapture.capture({audio: true}, (s) => {
            if (s) {
              resolve(s);
            } else {
              reject(new Error('Tab capture failed or not available'));
            }
          });
        });
        
        try {
          outputAudioContext = new (window.AudioContext || window.webkitAudioContext)();
          audioSource = outputAudioContext.createMediaStreamSource(stream);
          audioSource.connect(outputAudioContext.destination);
        } catch (audioError) {
          console.warn('could not preserve system audio:', audioError);
        }
        
        statusText.textContent = "Using tab audio capture.";
      } catch (tabError) {
        console.log('Tab capture not available, falling back to microphone', tabError);
        const audioConstraints = selectedMicrophoneId
          ? { audio: { deviceId: { exact: selectedMicrophoneId } } }
          : { audio: true };
        stream = await navigator.mediaDevices.getUserMedia(audioConstraints);
        statusText.textContent = "Using microphone audio.";
      }
    } else if (isWebContext) {
      const audioConstraints = selectedMicrophoneId 
        ? { audio: { deviceId: { exact: selectedMicrophoneId } } }
        : { audio: true };
      stream = await navigator.mediaDevices.getUserMedia(audioConstraints);
    }

    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    microphone = audioContext.createMediaStreamSource(stream);
    microphone.connect(analyser);

    if (serverUseAudioWorklet) {
      if (!audioContext.audioWorklet) {
        throw new Error("AudioWorklet is not supported in this browser");
      }
      await audioContext.audioWorklet.addModule("/web/pcm_worklet.js");
      workletNode = new AudioWorkletNode(audioContext, "pcm-forwarder", { numberOfInputs: 1, numberOfOutputs: 0, channelCount: 1 });
      microphone.connect(workletNode);

      recorderWorker = new Worker("/web/recorder_worker.js");
      recorderWorker.postMessage({
        command: "init",
        config: {
          sampleRate: audioContext.sampleRate,
        },
      });

      micRecordedKind = "wav"; // worker emits 16 kHz s16le mono
      recorderWorker.onmessage = (e) => {
        const ab = e.data.buffer;
        // Keep a copy for local playback before the buffer is sent/queued.
        micRecordedParts.push(new Uint8Array(ab.slice(0)));
        if (websocket && websocket.readyState === WebSocket.OPEN) {
          websocket.send(ab);
        }
      };

      workletNode.port.onmessage = (e) => {
        const data = e.data;
        const ab = data instanceof ArrayBuffer ? data : data.buffer;
        recorderWorker.postMessage(
          {
            command: "record",
            buffer: ab,
          },
          [ab]
        );
      };
    } else {
      try {
        recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      } catch (e) {
        recorder = new MediaRecorder(stream);
      }
      micRecordedKind = "webm";
      micRecordedMime = recorder.mimeType || "audio/webm";
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          micRecordedParts.push(e.data); // keep for local playback
          if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(e.data);
          }
        }
      };
      // The final dataavailable fires before onstop, so build the asset there.
      recorder.onstop = () => finalizeMicAsset();
      recorder.start(chunkDuration);
    }

    startTime = Date.now();
    timerInterval = setInterval(updateTimer, 1000);
    drawWaveform();

    isRecording = true;
    updateUI();
  } catch (err) {
    if (window.location.hostname === "0.0.0.0") {
      statusText.textContent =
        "Error accessing microphone. Browsers may block microphone access on 0.0.0.0. Try using localhost:8000 instead.";
    } else {
      statusText.textContent = "Error accessing microphone. Please allow microphone access.";
    }
    console.error(err);
  }
}

async function stopRecording() {
  if (wakeLock) {
    try {
      await wakeLock.release();
    } catch (e) {
      // ignore
    }
    wakeLock = null;
  }

  userClosing = true;
  waitingForStop = true;

  if (websocket && websocket.readyState === WebSocket.OPEN) {
    const emptyBlob = new Blob([], { type: "audio/webm" });
    websocket.send(emptyBlob);
    statusText.textContent = "Recording stopped. Processing final audio...";
  }

  if (recorder) {
    try {
      recorder.stop();
    } catch (e) {
    }
    recorder = null;
  }

  if (recorderWorker) {
    recorderWorker.terminate();
    recorderWorker = null;
  }

  // Build the playable asset from captured PCM. (The MediaRecorder/webm path
  // builds its asset in recorder.onstop instead, after its final chunk.)
  if (micRecordedKind === "wav") {
    finalizeMicAsset();
  }

  if (workletNode) {
    try {
      workletNode.port.onmessage = null;
    } catch (e) {}
    try {
      workletNode.disconnect();
    } catch (e) {}
    workletNode = null;
  }

  if (microphone) {
    microphone.disconnect();
    microphone = null;
  }

  if (analyser) {
    analyser = null;
  }

  if (audioContext && audioContext.state !== "closed") {
    try {
      await audioContext.close();
    } catch (e) {
      console.warn("Could not close audio context:", e);
    }
    audioContext = null;
  }

  if (audioSource) {
    audioSource.disconnect();
    audioSource = null;
  }

  if (outputAudioContext && outputAudioContext.state !== "closed") {
    outputAudioContext.close()
    outputAudioContext = null;
  }

  if (animationFrame) {
    cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  timerElement.textContent = "00:00";
  startTime = null;

  isRecording = false;
  updateUI();
}

async function toggleRecording() {
  if (!isRecording) {
    if (waitingForStop) {
      console.log("Waiting for stop, early return");
      return;
    }
    console.log("Connecting to WebSocket");
    try {
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        await configReady;
        await startRecording();
      } else {
        await setupWebSocket(withLanguage(websocketUrl));
        await configReady;
        await startRecording();
      }
    } catch (err) {
      statusText.textContent = "Could not connect to WebSocket or access mic. Aborted.";
      console.error(err);
    }
  } else {
    console.log("Stopping recording");
    stopRecording();
  }
}

function updateUI() {
  recordButton.classList.toggle("recording", isRecording);
  recordButton.disabled = waitingForStop;

  if (waitingForStop) {
    if (statusText.textContent !== "Recording stopped. Processing final audio...") {
      statusText.textContent = "Please wait for processing to complete...";
    }
  } else if (isRecording) {
    statusText.textContent = "";
  } else {
    if (
      statusText.textContent !== "Finished processing audio! Ready to record again." &&
      statusText.textContent !== "Processing finalized or connection closed."
    ) {
      statusText.textContent = "Click to start transcription";
    }
  }
  if (!waitingForStop) {
    recordButton.disabled = false;
  }
}

recordButton.addEventListener("click", toggleRecording);

if (microphoneSelect) {
  microphoneSelect.addEventListener("change", handleMicrophoneChange);
}
document.addEventListener('DOMContentLoaded', async () => {
  try {
    await enumerateMicrophones();
  } catch (error) {
    console.log("Could not enumerate microphones on load:", error);
  }
});
navigator.mediaDevices.addEventListener('devicechange', async () => {
  console.log('Device change detected, re-enumerating microphones');
  try {
    await enumerateMicrophones();
  } catch (error) {
    console.log("Error re-enumerating microphones:", error);
  }
});


settingsToggle.addEventListener("click", () => {
settingsDiv.classList.toggle("visible");
settingsToggle.classList.toggle("active");
});

if (isExtension) {
  async function checkAndRequestPermissions() {
    const micPermission = await navigator.permissions.query({
      name: "microphone",
    });

    const permissionDisplay = document.getElementById("audioPermission");
    if (permissionDisplay) {
      permissionDisplay.innerText = `MICROPHONE: ${micPermission.state}`;
    }

    // if (micPermission.state !== "granted") {
    //   chrome.tabs.create({ url: "welcome.html" });
    // }

    const intervalId = setInterval(async () => {
      const micPermission = await navigator.permissions.query({
        name: "microphone",
      });
      if (micPermission.state === "granted") {
        if (permissionDisplay) {
          permissionDisplay.innerText = `MICROPHONE: ${micPermission.state}`;
        }
        clearInterval(intervalId);
      }
    }, 100);
  }

  void checkAndRequestPermissions();
}

// =====================================================================
// File transcription (audio + video), media player, transcript tools.
// All additive; reuses setupWebSocket()/renderLinesWithBuffer() above.
// =====================================================================

// --- client-side transcript store (keystone) -------------------------
// The server prunes its state to a ~5 min window, so we accumulate every
// committed line here, keyed by its numeric start, to keep a full,
// navigable transcript for mic AND file sessions.
const transcriptStore = new Map();

// --- single active source/session model ------------------------------
// Core invariant: the transcript on screen, its timestamps, and the media
// player ALWAYS refer to the same source. currentObjectUrl is the media that
// generated the displayed transcript; activeSourceType says where it came from.
let currentObjectUrl = null;
let activeSourceType = null;        // 'mic' | 'file' | null
// Captured chunks of the in-progress mic recording (made playable on stop).
let micRecordedParts = [];
let micRecordedKind = null;         // 'webm' (MediaRecorder) | 'wav' (PCM worklet)
let micRecordedMime = "audio/webm";

function upsertLines(lines) {
  if (!Array.isArray(lines)) return;
  for (const ln of lines) {
    if (!ln) continue;
    const key =
      (ln.start_s !== undefined && ln.start_s !== null) ? String(ln.start_s)
      : (ln.start !== undefined && ln.start !== null) ? String(ln.start)
      : `idx-${transcriptStore.size}`;
    transcriptStore.set(key, ln);
  }
}

function getStoreLines() {
  return Array.from(transcriptStore.values());
}

function resetTranscriptStore() {
  transcriptStore.clear();
  lastSignature = null;
  lastReceivedData = null;
  if (linesTranscriptDiv) linesTranscriptDiv.innerHTML = "";
}

// --- time helpers (mirror server format_time / its inverse) ----------
function parseTimeStr(t) {
  if (typeof t !== "string") { const n = Number(t); return Number.isFinite(n) ? n : 0; }
  const parts = t.split(":");
  let s = 0;
  if (parts.length === 3) s = Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2]);
  else if (parts.length === 2) s = Number(parts[0]) * 60 + Number(parts[1]);
  else s = Number(parts[0]);
  return Number.isFinite(s) ? s : 0;
}

function formatTime(sec) {
  if (sec === null || sec === undefined || !Number.isFinite(Number(sec))) return "";
  let s = Math.max(0, Number(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = Math.floor(s % 60);
  const cs = Math.floor((s - Math.floor(s)) * 100);
  return `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// --- DOM refs --------------------------------------------------------
const fileInput = document.getElementById("fileInput");
const mediaPlayer = document.getElementById("mediaPlayer");
const mediaContainer = document.getElementById("mediaContainer");
const mediaFileName = document.getElementById("mediaFileName");
const copyBtn = document.getElementById("copyBtn");
const exportBtn = document.getElementById("exportBtn");
const clearBtn = document.getElementById("clearBtn");
const showTimestamps = document.getElementById("showTimestamps");
const languageSelect = document.getElementById("languageSelect");
const modelSelect = document.getElementById("modelSelect");
const startBtn = document.getElementById("startBtn");

// File chosen for transcription; only transcribed when Start is clicked (req 2).
let selectedFile = null;

// --- active media control (one source at a time) ---------------------
// Force a media element to expose a finite, seekable duration. MediaRecorder
// blobs report duration === Infinity until the browser is nudged to the end.
function ensureSeekableDuration() {
  if (!mediaPlayer) return;
  mediaPlayer.addEventListener("loadedmetadata", function fix() {
    const d = mediaPlayer.duration;
    if (d === Infinity || Number.isNaN(d)) {
      const onTU = () => {
        mediaPlayer.removeEventListener("timeupdate", onTU);
        try { mediaPlayer.currentTime = 0; } catch (e) {}
      };
      mediaPlayer.addEventListener("timeupdate", onTU);
      try { mediaPlayer.currentTime = 1e101; } catch (e) {}
    }
  }, { once: true });
}

// Point the player at a new asset and record which source owns it. Revokes the
// previous object URL so the old source can never be seeked into again.
function setActiveMedia(url, name, sourceType, kind) {
  if (currentObjectUrl && currentObjectUrl !== url) {
    URL.revokeObjectURL(currentObjectUrl);
  }
  currentObjectUrl = url;
  activeSourceType = sourceType || null;
  if (mediaPlayer) {
    ensureSeekableDuration();
    mediaPlayer.src = url;
    try { mediaPlayer.load(); } catch (e) {}
  }
  if (mediaContainer) {
    mediaContainer.classList.remove("hidden");
    mediaContainer.classList.toggle("audio-only", kind === "audio");
  }
  if (mediaFileName) mediaFileName.textContent = name || "";
}

// Remove any media from the player (no asset belongs to the new source yet).
function clearActiveMedia(sourceType) {
  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl);
    currentObjectUrl = null;
  }
  activeSourceType = sourceType || null;
  if (mediaPlayer) {
    mediaPlayer.removeAttribute("src");
    try { mediaPlayer.load(); } catch (e) {}
  }
  if (mediaContainer) {
    mediaContainer.classList.add("hidden");
    mediaContainer.classList.remove("audio-only");
  }
  if (mediaFileName) mediaFileName.textContent = "";
}

// Show an uploaded file as the active source (audio vs video by MIME).
function showFileMedia(file) {
  if (!file) return;
  const kind = (file.type && file.type.startsWith("video")) ? "video" : "audio";
  setActiveMedia(URL.createObjectURL(file), file.name, "file", kind);
}

// Seek the player — always within the asset that produced the current
// transcript, never beyond its duration, never into a stale/other source.
function seekMediaTo(seconds) {
  if (!mediaPlayer || !currentObjectUrl) {
    statusText.textContent = "No media is loaded for this transcript.";
    return;
  }
  let t = Number(seconds);
  if (!Number.isFinite(t) || t < 0) t = 0;
  const dur = mediaPlayer.duration;
  if (Number.isFinite(dur) && dur > 0) {
    t = Math.min(t, Math.max(0, dur - 0.05)); // never past the end
  }
  try { mediaPlayer.currentTime = t; } catch (e) {}
  if (mediaPlayer.paused) mediaPlayer.play().catch(() => {});
}

// --- microphone -> playable asset (req 6) ----------------------------
function resetMicCapture() {
  micRecordedParts = [];
  micRecordedKind = null;
  micRecordedMime = "audio/webm";
}

// Wrap captured 16 kHz s16le mono PCM (the worklet transport) into a WAV blob.
function pcm16ToWavBlob(chunks, sampleRate) {
  let dataSize = 0;
  for (const c of chunks) dataSize += c.byteLength;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);            // PCM fmt chunk size
  view.setUint16(20, 1, true);             // PCM
  view.setUint16(22, 1, true);             // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true);             // block align
  view.setUint16(34, 16, true);            // bits/sample
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);
  let offset = 44;
  const bytes = new Uint8Array(buffer);
  for (const c of chunks) { bytes.set(c, offset); offset += c.byteLength; }
  return new Blob([buffer], { type: "audio/wav" });
}

// Build a playable asset from the just-finished recording and make it the
// active source, so replay + timestamp seeking target the mic audio (not a
// previously uploaded file).
function finalizeMicAsset() {
  if (!micRecordedParts.length) return;
  let blob = null;
  if (micRecordedKind === "wav") {
    blob = pcm16ToWavBlob(micRecordedParts, 16000);
  } else {
    blob = new Blob(micRecordedParts, { type: micRecordedMime || "audio/webm" });
  }
  micRecordedParts = [];
  if (blob && blob.size > 0) {
    setActiveMedia(URL.createObjectURL(blob), "Microphone recording", "mic", "audio");
  }
}

// --- language + model selectors -------------------------------------
const LANGUAGES = [
  { code: "auto", label: "Auto Detect" },
  { code: "vi", label: "Vietnamese" },
  { code: "en", label: "English" },
];
// Models offered per transcription mode, for benchmarking accuracy/speed/memory.
// Whisper sizes ascending; large-v3 is intentionally omitted (too heavy for testing).
// Streaming runs the in-process MLX-Whisper singleton (chosen at startup, no hot-swap);
// Batch can additionally use ChunkFormer (Vietnamese), which runs out-of-process.
const WHISPER_SIZES = [
  { value: "tiny", label: "tiny" },
  { value: "base", label: "base" },
  { value: "small", label: "small" },
  { value: "medium", label: "medium" },
  { value: "large-v3-turbo", label: "large-v3-turbo" },
];
// Streaming: large-v3-turbo is the DEFAULT (listed first => first enabled).
const STREAMING_MODELS = [
  { value: "large-v3-turbo", label: "large-v3-turbo" },
  { value: "tiny", label: "tiny" },
  { value: "base", label: "base" },
  { value: "small", label: "small" },
  { value: "medium", label: "medium" },
];
// Batch: ChunkFormer is the DEFAULT (first), then Whisper sizes for easy comparison.
const BATCH_MODELS = [
  { value: "chunkformer", label: "ChunkFormer (Vietnamese)" },
  ...WHISPER_SIZES,
];

let runningModel = null;     // what the server actually loaded (from /health), for streaming
let batchBackendAvail = {};  // { id: true/false } per batch backend, reported by /health

function getSelectedLanguage() {
  return (languageSelect && languageSelect.value) || "auto";
}

function getSelectedMode() {
  return (document.querySelector('input[name="mode"]:checked') || {}).value || "stream";
}

function getSelectedModel() {
  return (modelSelect && modelSelect.value) || "large-v3-turbo";
}

// Append ?language=<code> to a ws/http URL (works with or without an existing query).
function withLanguage(url) {
  const lang = getSelectedLanguage();
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}language=${encodeURIComponent(lang)}`;
}

// Base ws://host:port derived from the (possibly user-edited) websocket URL.
function getWsBase() {
  return (websocketUrl || "").replace(/\?.*$/, "").replace(/\/asr$/, "");
}
function getFileWsUrl() {
  return getWsBase() + "/asr/file";
}
function getHttpBase() {
  return getWsBase().replace(/^ws/, "http");
}

function updateStartEnabled() {
  if (startBtn) startBtn.disabled = !selectedFile;
}

// Populate the language selector (persisted across reloads).
if (languageSelect) {
  LANGUAGES.forEach((l) => {
    const opt = document.createElement("option");
    opt.value = l.code;
    opt.textContent = l.label;
    languageSelect.appendChild(opt);
  });
  const savedLang = localStorage.getItem("transcriptionLanguage");
  if (savedLang && LANGUAGES.some((l) => l.code === savedLang)) {
    languageSelect.value = savedLang;
  }
  languageSelect.addEventListener("change", () => {
    localStorage.setItem("transcriptionLanguage", languageSelect.value);
  });
}

// Streaming uses the model loaded at startup (a singleton, no hot-swap). If the
// selected streaming model differs from what the server actually loaded, surface an
// honest "restart with --model X" note rather than silently transcribing with the wrong one.
function reconcileStreamingModel() {
  if (getSelectedMode() === "batch") return;
  const sel = (modelSelect && modelSelect.value) || "large-v3-turbo";
  if (runningModel && runningModel !== sel && statusText && !statusText.textContent) {
    statusText.textContent =
      `Note: streaming uses the model loaded at startup ("${runningModel}"). ` +
      `To stream with "${sel}", restart the server with --model ${sel}.`;
  }
}

// Rebuild the model dropdown for the current mode:
//   Streaming -> large-v3-turbo only (the in-process engine).
//   Batch     -> ChunkFormer (default) + large-v3-turbo.
// Batch backends the server reports as unavailable are shown disabled.
function repopulateModelSelect() {
  if (!modelSelect) return;
  const mode = getSelectedMode();
  const list = mode === "batch" ? BATCH_MODELS : STREAMING_MODELS;
  modelSelect.innerHTML = "";
  list.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.value;
    opt.textContent = m.label;
    if (mode === "batch" && m.value in batchBackendAvail && !batchBackendAvail[m.value]) {
      opt.disabled = true;
      opt.textContent = `${m.label} (unavailable — see docs)`;
    }
    modelSelect.appendChild(opt);
  });
  // Default to the first enabled option (Batch -> ChunkFormer, Streaming -> large-v3-turbo).
  const firstEnabled = Array.from(modelSelect.options).find((o) => !o.disabled);
  if (firstEnabled) modelSelect.value = firstEnabled.value;
  reconcileStreamingModel();
}

if (modelSelect) {
  repopulateModelSelect();
  fetch(getHttpBase() + "/health")
    .then((r) => r.json())
    .then((h) => {
      runningModel = h && h.model ? h.model : null;
      if (h && Array.isArray(h.batch_backends)) {
        h.batch_backends.forEach((b) => {
          batchBackendAvail[b.id] = !!b.available;
        });
      }
      repopulateModelSelect(); // re-render with availability + streaming note
    })
    .catch(() => {});

  // Switching the batch model is free (out-of-process). Only the streaming Whisper engine
  // is a startup singleton, so warn about a restart there alone.
  modelSelect.addEventListener("change", () => {
    if (getSelectedMode() !== "batch" && runningModel && modelSelect.value !== runningModel) {
      statusText.textContent =
        `Model "${modelSelect.value}" requires restarting the server with --model ${modelSelect.value} ` +
        `(cannot hot-swap). Currently running: ${runningModel}.`;
    }
  });

  // Toggling Streaming/Batch re-populates the available models for that mode.
  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener("change", repopulateModelSelect);
  });
}

// --- clickable timestamp chips seek the media player -----------------
if (linesTranscriptDiv) {
  linesTranscriptDiv.addEventListener("click", (e) => {
    const chip = e.target.closest(".ts-chip");
    if (!chip) return;
    // Seeks always target the media that produced THIS transcript; clamped to
    // its duration. seekMediaTo no-ops when no asset is loaded (e.g. mid-record).
    seekMediaTo(parseFloat(chip.dataset.s));
  });
}

// --- show/hide timestamps -------------------------------------------
function applyTimestampVisibility() {
  document.body.classList.toggle("hide-timestamps", showTimestamps ? !showTimestamps.checked : false);
}
if (showTimestamps) {
  showTimestamps.addEventListener("change", applyTimestampVisibility);
  applyTimestampVisibility();
}

// --- transcript text + toolbar --------------------------------------
function getTranscriptText() {
  const withTs = !!(showTimestamps && showTimestamps.checked);
  return getStoreLines()
    .filter((l) => l && l.text && l.speaker !== -2)
    .map((l) => (withTs && l.start ? `[${l.start}] ` : "") + String(l.text).trim())
    .join("\n");
}

if (copyBtn) {
  copyBtn.addEventListener("click", async () => {
    const text = getTranscriptText();
    if (!text) { statusText.textContent = "Nothing to copy yet."; return; }
    try {
      await navigator.clipboard.writeText(text);
      const prev = copyBtn.textContent;
      copyBtn.textContent = "Copied";
      setTimeout(() => { copyBtn.textContent = prev; }, 1200);
    } catch (e) {
      statusText.textContent = "Copy failed (clipboard blocked).";
    }
  });
}

if (exportBtn) {
  exportBtn.addEventListener("click", () => {
    const text = getTranscriptText();
    if (!text) { statusText.textContent = "Nothing to export yet."; return; }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "transcript.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

if (clearBtn) {
  clearBtn.addEventListener("click", () => {
    resetTranscriptStore();
    statusText.textContent = "Transcript cleared.";
  });
}

// --- feed an uploaded file's bytes into the live /asr WebSocket -------
async function streamFileToWebSocket(file) {
  const CHUNK = 256 * 1024;
  const MAX_BUFFERED = 8 * 1024 * 1024; // backpressure threshold
  let offset = 0;
  while (offset < file.size) {
    if (!websocket || websocket.readyState !== WebSocket.OPEN) break;
    while (websocket && websocket.bufferedAmount > MAX_BUFFERED) {
      await new Promise((r) => setTimeout(r, 40));
    }
    const buf = await file.slice(offset, offset + CHUNK).arrayBuffer();
    if (!websocket || websocket.readyState !== WebSocket.OPEN) break;
    websocket.send(buf);
    offset += CHUNK;
  }
}

async function transcribeFileStreaming(file) {
  statusText.textContent = "Streaming file for transcription…";
  waitingForStop = false;
  userClosing = false;
  // Dedicated endpoint: buffers the upload to a seekable temp file and decodes it
  // server-side, so video / moov-at-end containers (which the live /asr pipe
  // cannot decode progressively) work and long files stay memory-bounded.
  await setupWebSocket(withLanguage(getFileWsUrl()));
  await configReady;
  await streamFileToWebSocket(file);
  // End-of-upload sentinel: empty frame (matches the server's receive loop).
  userClosing = true;
  waitingForStop = true;
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send(new Blob([], { type: "application/octet-stream" }));
  }
  statusText.textContent = "File sent. Finishing transcription…";
  updateUI();
}

// --- batch transcription via the existing OpenAI-compatible REST endpoint
async function transcribeFileBatch(file) {
  const model = getSelectedModel();
  statusText.textContent = model.includes("chunkformer")
    ? "Transcribing with ChunkFormer (first run loads the model, may take ~20–40s)…"
    : `Uploading file (batch, ${model})…`;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("model", model);
  fd.append("response_format", "verbose_json");
  fd.append("language", getSelectedLanguage());
  const resp = await fetch(`${getHttpBase()}/v1/audio/transcriptions`, { method: "POST", body: fd });
  if (!resp.ok) {
    let detail = `server ${resp.status}`;
    try {
      const errData = await resp.json();
      if (errData && errData.detail) detail = errData.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  const data = await resp.json();
  resetTranscriptStore();
  (data.segments || []).forEach((seg) => {
    transcriptStore.set(String(seg.start), {
      speaker: 1,
      text: seg.text,
      start_s: seg.start,
      end_s: seg.end,
      start: formatTime(seg.start),
      end: formatTime(seg.end),
    });
  });
  renderLinesWithBuffer(getStoreLines(), "", "", "", 0, 0, true);
  statusText.textContent = "Batch transcription complete.";
}

// --- file picker: preview only; transcription waits for Start (req 2) -
if (fileInput) {
  fileInput.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;

    selectedFile = file;

    // Selecting a file makes it the single active source: switch the player to
    // it and clear any prior transcript, so the displayed transcript + media +
    // timestamps never refer to different sources during the preview window.
    showFileMedia(file);
    resetTranscriptStore();

    updateStartEnabled();
    statusText.textContent = `Ready: "${file.name}". Click Start Transcription.`;
  });
}

// --- explicit Start: configure (mode/language) then transcribe -------
if (startBtn) {
  startBtn.addEventListener("click", async () => {
    if (!selectedFile) {
      statusText.textContent = "Choose a file first.";
      return;
    }
    const file = selectedFile;
    // Re-assert this file as the active source (a mic recording may have taken
    // over the player since selection), then start from a clean transcript.
    if (activeSourceType !== "file" || !currentObjectUrl) {
      showFileMedia(file);
    }
    resetTranscriptStore();
    const mode = (document.querySelector('input[name="mode"]:checked') || {}).value || "stream";
    startBtn.disabled = true;
    try {
      if (mode === "batch") await transcribeFileBatch(file);
      else await transcribeFileStreaming(file);
    } catch (err) {
      statusText.textContent = "File transcription error: " + (err && err.message ? err.message : err);
      console.error(err);
    } finally {
      updateStartEnabled();
    }
  });
}
