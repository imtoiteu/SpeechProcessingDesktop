// Verifies the strict segment renderer in live_transcription.js against the
// rules: every visible timestamp owns exactly one text block; no orphan
// timestamps; no untimed text; streaming buffer stays under the last segment.
// Runs the REAL renderLinesWithBuffer in a stubbed DOM (no browser needed).

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const file = path.join(__dirname, "..", "WhisperLiveKit", "whisperlivekit", "web", "live_transcription.js");
const code = fs.readFileSync(file, "utf8");

// --- minimal DOM/browser stubs --------------------------------------
const elements = {};
function makeEl() {
  return {
    innerHTML: "", textContent: "", value: "", disabled: false,
    dataset: {}, style: {}, src: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, appendChild() {},
    removeAttribute() {}, setAttribute() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, load() {}, play() { return Promise.resolve(); },
    scrollTo() {}, getContext() { return { scale() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {} }; },
    get paused() { return true; },
    scrollHeight: 0, scrollTop: 0, clientHeight: 0,
  };
}
const document = {
  documentElement: { classList: { add() {}, remove() {} }, setAttribute() {}, removeAttribute() {}, style: {} },
  body: { classList: { add() {}, remove() {}, toggle() {} } },
  getElementById(id) { return elements[id] || (elements[id] = makeEl()); },
  querySelector(sel) { return sel === ".transcript-container" ? makeEl() : null; },
  querySelectorAll() { return []; },
  addEventListener() {}, createElement() { return makeEl(); },
};
const sandbox = {
  document,
  window: {
    devicePixelRatio: 1, location: { hostname: "localhost", port: "8000", protocol: "http:" },
    matchMedia: () => ({ addEventListener() {}, addListener() {} }),
    AudioContext: function () {}, webkitAudioContext: function () {},
  },
  navigator: { mediaDevices: { addEventListener() {}, getUserMedia: () => Promise.resolve({}), enumerateDevices: () => Promise.resolve([]) }, wakeLock: {} },
  localStorage: { getItem: () => null, setItem() {} },
  getComputedStyle: () => ({ getPropertyValue: () => "" }),
  fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
  URL: { createObjectURL: () => "blob:stub", revokeObjectURL() {} },
  requestAnimationFrame: () => 0, cancelAnimationFrame() {},
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
  console, JSON, Math, Date, Array, Object, String, Number, Set, Map,
};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const render = sandbox.renderLinesWithBuffer;
const out = () => elements["linesTranscript"].innerHTML;

// --- helpers ---------------------------------------------------------
function count(html, re) { return (html.match(re) || []).length; }
function segmentsOf(html) {
  // split into per-segment chunks
  return html.split('<div class="segment">').slice(1);
}
let failures = 0;
function check(name, cond, extra) {
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${name}${extra && !cond ? "  -> " + extra : ""}`);
  if (!cond) failures++;
}

function assertStrictPairing(label, html) {
  const segs = segmentsOf(html);
  const nChip = count(html, /class="ts-chip"/g);
  const nText = count(html, /class="segment-text"/g);
  console.log(`\n[${label}] segments=${segs.length} chips=${nChip} text-blocks=${nText}`);
  check("equal counts: segments == chips == text-blocks", segs.length === nChip && nChip === nText, `${segs.length}/${nChip}/${nText}`);
  let everySegOneChipOneText = segs.length > 0;
  for (const s of segs) {
    const c = count(s, /class="ts-chip"/g);
    const t = count(s, /class="segment-text"/g);
    if (c !== 1 || t !== 1) { everySegOneChipOneText = false; break; }
  }
  check("each segment has exactly one chip and one text block (rules 1-3)", everySegOneChipOneText);
  // no <p>/<div> nesting invalidity: no <div> inside <p>
  check("no <div> nested inside <p> (valid HTML)", !/<p>[^]*?<div/.test(html));
  return { segs, nChip, nText };
}

// --- Case A: committed segments (batch/finalize) --------------------
const lines3 = [
  { speaker: 1, text: "Xin chào xin xin chào!", start: "0:00:01.00", start_s: 1.0, detected_language: "vi" },
  { speaker: 1, text: "Hôm nay là một ngày thực sự rất đẹp trời...", start: "0:00:07.00", start_s: 7.0, detected_language: "vi" },
  { speaker: 1, text: "Tôi nghĩ hôm nay rất thích hợp...", start: "0:00:15.00", start_s: 15.0, detected_language: "vi" },
  { speaker: 1, text: "Chúng ta hãy cùng nhau...", start: "0:00:22.00", start_s: 22.0, detected_language: "vi" },
];
render(lines3, "", "", "", 0, 0, true, "active_transcription");
let htmlA = out();
assertStrictPairing("A: finalized 4 segments", htmlA);
check("A: data-s carries seek seconds (click-to-seek, rule 4)", /data-s="1"/.test(htmlA) && /data-s="22"/.test(htmlA));
check("A: bracketed time text present", htmlA.includes("0:00:07.00"));
check("A: language badge shown once (only on first, then on change)", count(htmlA, /label_language/g) === 1, String(count(htmlA, /label_language/g)));

// --- Case B: streaming (buffer belongs to last segment only) --------
render(lines3, "", "đang nói thêm", "", 0, 2.4, false, "active_transcription");
let htmlB = out();
const rB = assertStrictPairing("B: streaming with live buffer", htmlB);
check("B: still 4 segments (buffer did NOT create a new one, rule 7)", rB.segs.length === 4);
check("B: buffer text is inside the LAST segment-text", /buffer_transcription/.test(rB.segs[rB.segs.length - 1]));
check("B: streaming lag hint present on active segment", /seg-lag/.test(htmlB));

// --- Case C: buffer-only, nothing committed yet ---------------------
render([], "", "Xin", "", 0, 1.0, false, "active_transcription");
let htmlC = out();
const rC = assertStrictPairing("C: buffer-only (pre-commit)", htmlC);
check("C: exactly one segment under a 0:00 chip (no untimed text, rule 3)", rC.segs.length === 1 && /data-s="0"/.test(htmlC));

// --- Case D: HTML in text is escaped --------------------------------
render([{ speaker: 1, text: "a < b & c > d", start: "0:00:01.00", start_s: 1.0 }], "", "", "", 0, 0, true);
let htmlD = out();
check("D: special chars escaped (no raw <, &)", htmlD.includes("a &lt; b &amp; c &gt; d"));

// --- Case E: silence / loading entries are dropped (no orphans) -----
render([
  { speaker: -2, text: "", start: "0:00:00.00", start_s: 0 },              // silence
  { speaker: 0, text: "", start: "0:00:01.00", start_s: 1 },              // loading
  { speaker: 1, text: "Real text", start: "0:00:02.00", start_s: 2 },     // real
], "", "", "", 0, 0, true);
let htmlE = out();
const rE = assertStrictPairing("E: silence/loading dropped", htmlE);
check("E: only the one real segment renders (rules 2-3)", rE.segs.length === 1 && htmlE.includes("Real text"));

console.log(`\n==== ${failures === 0 ? "ALL CHECKS PASS" : failures + " CHECK(S) FAILED"} ====`);
process.exit(failures === 0 ? 0 : 1);
