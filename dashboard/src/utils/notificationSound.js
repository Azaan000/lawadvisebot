// Shared Web Audio notification sound + browser Notification helpers.
// Extracted from App.js so any component can play the same alert sound
// through the SAME AudioContext instance — creating a second, independent
// AudioContext elsewhere would need its own unlock-on-gesture handling
// and could hit the browser's cap on concurrent contexts (~4-6).

const DEBUG_CONSULT = false;
export const trace = (...args) => {
  if (DEBUG_CONSULT || window.DEBUG_CONSULT) console.log(...args);
};

let _audioCtx = null;
function getAudioContext() {
  if (!_audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    _audioCtx = new AC();
  }
  return _audioCtx;
}

export function unlockAudioOnFirstGesture() {
  const unlock = () => {
    const ctx = getAudioContext();
    if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
    window.removeEventListener("click", unlock);
    window.removeEventListener("keydown", unlock);
  };
  window.addEventListener("click", unlock);
  window.addEventListener("keydown", unlock);
}

// Play a notification sound using Web Audio API — no file needed
export function playNotificationSound() {
  try {
    const ctx = getAudioContext();
    trace("[TRACE 4] AudioContext state:", ctx?.state);
    if (!ctx) { trace("[TRACE 4] No AudioContext available (unsupported browser)"); return; }

    const schedule = () => {
      const playTone = (freq, start, duration, gain = 0.3) => {
        const osc = ctx.createOscillator();
        const gainNode = ctx.createGain();
        osc.connect(gainNode);
        gainNode.connect(ctx.destination);
        osc.frequency.value = freq;
        osc.type = "sine";
        gainNode.gain.setValueAtTime(0, ctx.currentTime + start);
        gainNode.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.02);
        gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + start + duration);
        osc.start(ctx.currentTime + start);
        osc.stop(ctx.currentTime + start + duration + 0.05);
      };
      // Three ascending tones — pleasant alert
      playTone(523, 0,    0.15);  // C5
      playTone(659, 0.18, 0.15);  // E5
      playTone(784, 0.36, 0.25);  // G5
    };

    if (ctx.state === "suspended") {
      // Still locked (no gesture yet this session) — try to resume and
      // play once it succeeds; fail silently instead of throwing, so
      // any accompanying browser notification/toast still fire.
      ctx.resume().then(schedule).catch(() => {});
    } else {
      schedule();
    }
  } catch (e) {
    console.log("Audio not available:", e);
  }
}

// Request browser notification permission once
export function requestNotificationPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}