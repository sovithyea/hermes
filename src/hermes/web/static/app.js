// Hermes front-end: chapter player, voice previews, and inline script editing.

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};

// One shared <audio> for short clips (voice previews, single lines).
const clip = new Audio();
function playClip(url, button) {
  clip.pause();
  const label = button.textContent;
  button.textContent = "…";
  button.disabled = true;
  clip.src = url;
  const reset = () => { button.textContent = label; button.disabled = false; };
  clip.oncanplay = reset;
  clip.onerror = () => { reset(); button.textContent = "!"; setTimeout(reset, 1500); };
  clip.play().catch(reset);
}

// ---------------------------------------------------------------------------
// Chapter player (book page). Remembers position per chapter and plays on.
// ---------------------------------------------------------------------------
const player = document.getElementById("player");
if (player) {
  const slug = player.dataset.slug;
  const audio = document.getElementById("audio");
  const title = document.getElementById("player-title");
  const speed = document.getElementById("speed");
  let current = null;
  let lastSave = 0;

  const posKey = (n) => `hermes:${slug}:pos:${n}`;

  function load(button, autoplay) {
    const n = button.dataset.play;
    current = Number(n);
    player.hidden = false;
    title.textContent = button.dataset.title;
    audio.src = `/book/${slug}/audio/${n}.mp3?v=${button.dataset.version}`;
    audio.playbackRate = Number(speed.value);
    const saved = Number(store.get(posKey(n)) || 0);
    audio.addEventListener("loadedmetadata", () => {
      if (saved > 0 && saved < audio.duration - 5) audio.currentTime = saved;
      audio.playbackRate = Number(speed.value);
    }, { once: true });
    store.set(`hermes:${slug}:last`, n);
    if (autoplay) audio.play();
    document.querySelectorAll("tr.playing").forEach((tr) => tr.classList.remove("playing"));
    button.closest("tr")?.classList.add("playing");
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-play]");
    if (btn) load(btn, true);
    const skip = e.target.closest("[data-skip]");
    if (skip) audio.currentTime = Math.max(0, audio.currentTime + Number(skip.dataset.skip));
  });

  audio.addEventListener("timeupdate", () => {
    if (current && Date.now() - lastSave > 3000) {
      store.set(posKey(current), audio.currentTime.toFixed(1));
      lastSave = Date.now();
    }
  });
  audio.addEventListener("ended", () => {
    store.set(posKey(current), 0);
    const next = document.querySelector(`[data-play="${current + 1}"]`);
    if (next) load(next, true);
  });

  const savedSpeed = store.get("hermes:speed");
  if (savedSpeed) speed.value = savedSpeed;
  speed.addEventListener("change", () => {
    audio.playbackRate = Number(speed.value);
    store.set("hermes:speed", speed.value);
  });

  // Offer to resume where the listener left off.
  const last = store.get(`hermes:${slug}:last`);
  const resume = last && document.querySelector(`[data-play="${last}"]`);
  if (resume) load(resume, false);
}

// ---------------------------------------------------------------------------
// Cast page: ▶ plays a sample of the voice currently selected in that row.
// ---------------------------------------------------------------------------
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button.preview");
  if (!btn) return;
  const select = btn.parentElement.querySelector("select");
  if (!select.value) return;
  const name = encodeURIComponent(btn.dataset.name || "");
  playClip(`/voice-preview?voice=${select.value}&name=${name}`, btn);
});

// ---------------------------------------------------------------------------
// Script page: every change saves immediately.
// ---------------------------------------------------------------------------
const script = document.querySelector("ol.script");
if (script) {
  const { slug, chapter } = script.dataset;

  async function save(li, fields) {
    const body = new FormData();
    for (const [k, v] of Object.entries(fields)) body.append(k, v);
    li.classList.add("saving");
    const res = await fetch(`/book/${slug}/chapter/${chapter}/line/${li.dataset.id}`, { method: "POST", body });
    li.classList.remove("saving");
    li.classList.toggle("save-failed", !res.ok);
  }

  function sync(li) {
    const type = li.querySelector("[name=type]").value;
    const speaker = li.querySelector("[name=speaker]");
    if (type === "narration") speaker.value = "Narrator";
    li.dataset.type = type;
    li.dataset.speaker = speaker.value;
    li.className = li.className.replace(/type-\S+/, `type-${type}`);
    li.classList.toggle("unknown", speaker.value === "Unknown");
  }

  script.addEventListener("change", (e) => {
    const li = e.target.closest("li.line");
    if (!li || !e.target.name) return;
    // A named speaker on a narration line means it's really dialogue.
    if (e.target.name === "speaker" && e.target.value !== "Narrator" && li.dataset.type === "narration") {
      li.querySelector("[name=type]").value = "dialogue";
    }
    sync(li);
    save(li, {
      speaker: li.querySelector("[name=speaker]").value,
      type: li.querySelector("[name=type]").value,
      emotion: li.querySelector("[name=emotion]").value,
    });
    applyFilter();
  });

  script.addEventListener("focusin", (e) => {
    if (e.target.classList.contains("line-text")) e.target.dataset.before = e.target.textContent;
  });
  script.addEventListener("focusout", (e) => {
    const p = e.target;
    if (p.classList.contains("line-text") && p.textContent !== p.dataset.before) {
      save(p.closest("li.line"), { text: p.textContent.trim() });
    }
  });

  script.addEventListener("click", (e) => {
    const btn = e.target.closest("button.say");
    if (!btn) return;
    const li = btn.closest("li.line");
    playClip(`/book/${slug}/line/${chapter}/${li.dataset.id}.wav?t=${Date.now()}`, btn);
  });

  const filter = document.getElementById("filter");
  const filterKey = `hermes:${slug}:filter`;
  function applyFilter() {
    const f = filter.value;
    for (const li of script.children) {
      let show = true;
      if (f === "spoken") show = li.dataset.type !== "narration";
      else if (f.startsWith("speaker:")) show = li.dataset.speaker === f.slice(8);
      li.hidden = !show;
    }
    store.set(filterKey, f);
  }
  const savedFilter = store.get(filterKey);
  if (savedFilter && [...filter.options].some((o) => o.value === savedFilter)) filter.value = savedFilter;
  filter.addEventListener("change", applyFilter);
  applyFilter();
}
