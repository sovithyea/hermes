// Page scanner: photograph pages one after another; each is sent to the Mac, read, and the
// photo discarded. Uploads queue up so the reader never waits between shots.

const root = document.querySelector(".scan");
const slug = root.dataset.slug;
const countEl = document.getElementById("count");
const toast = document.getElementById("toast");
const recent = document.getElementById("recent");
const video = document.getElementById("video");
const viewfinder = document.getElementById("viewfinder");
const takePhoto = document.getElementById("take-photo");
const cameraInput = document.getElementById("camera-input");

const queue = [];
let sending = false;

function say(message, kind = "") {
  toast.textContent = message;
  toast.className = `toast ${kind}`;
}

function addRecent(result) {
  const li = document.createElement("li");
  li.dataset.id = result.id;
  li.innerHTML = `<span class="pno"></span><span class="ptext"></span><button class="btn small remove" title="Remove this page">✕</button>`;
  li.querySelector(".pno").textContent = result.page;
  li.querySelector(".ptext").textContent = (result.heading ? `${result.heading} · ` : "") + result.preview;
  recent.prepend(li);
  while (recent.children.length > 8) recent.lastElementChild.remove();
}

async function pump() {
  if (sending) return;
  sending = true;
  while (queue.length) {
    const blob = queue.shift();
    say(queue.length ? `Reading… (${queue.length} more waiting)` : "Reading…");
    try {
      const body = new FormData();
      body.append("file", blob, "page.jpg");
      const res = await fetch(`/book/${slug}/scan`, { method: "POST", body });
      const r = await res.json();
      if (r.ok) {
        countEl.textContent = r.page;
        addRecent(r);
        say(`Page ${r.page} read ✓`, "ok");
        navigator.vibrate?.(30);
      } else if (r.reason === "duplicate") {
        say("That's the same page as last time, so it was skipped. Turn the page and go on.", "warn");
      } else {
        say("Couldn't read that page. Try again with more light, holding the phone steady.", "warn");
        navigator.vibrate?.([60, 60, 60]);
      }
    } catch {
      say("Lost connection to the Mac. Check the Wi-Fi, then take that page again.", "warn");
    }
  }
  sending = false;
}

function enqueue(blob) {
  queue.push(blob);
  pump();
}

// --- live viewfinder (secure pages only) ----------------------------------------
async function startCamera() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return false;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 3840 }, height: { ideal: 2160 } },
      audio: false,
    });
    video.srcObject = stream;
    viewfinder.hidden = false;
    takePhoto.hidden = true;
    navigator.wakeLock?.request("screen").catch(() => {});
    const track = stream.getVideoTracks()[0];
    const capture = "ImageCapture" in window ? new ImageCapture(track) : null;

    document.getElementById("shutter").addEventListener("click", async () => {
      viewfinder.classList.add("flash");
      setTimeout(() => viewfinder.classList.remove("flash"), 150);
      let blob = null;
      try { blob = capture ? await capture.takePhoto() : null; } catch { blob = null; }
      if (!blob) {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext("2d").drawImage(video, 0, 0);
        blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", 0.92));
      }
      enqueue(blob);
    });
    return true;
  } catch {
    return false;
  }
}

// --- fallback: the phone's own camera, one page per tap ----------------------------
cameraInput.addEventListener("change", () => {
  const file = cameraInput.files[0];
  if (file) enqueue(file);
  cameraInput.value = "";
});

// --- removing a page (e.g. a bad shot that slipped through) ------------------------
recent.addEventListener("click", async (e) => {
  const btn = e.target.closest("button.remove");
  if (!btn) return;
  const li = btn.closest("li");
  const res = await fetch(`/book/${slug}/scan/${encodeURIComponent(li.dataset.id)}/delete`, { method: "POST" });
  if (res.ok) {
    const r = await res.json();
    countEl.textContent = r.page;
    li.remove();
    say("Page removed. Take it again whenever you're ready.");
  }
});

startCamera();
