// The project page below the first screen: the five-step stage of the method, the result grids, lazy clips.
// (The first screen's 3D scene is hero.js.)
(() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (root, sel) => root.querySelector(sel);
  const clip = (id) => ({ src: `media/video/${id}.mp4`, poster: `media/poster/${id}.jpg` });

  // ---- the clips each step of the method can show. A step's panel has one <video> per entry of `ids`.
  // An entry with `img` shows a figure from the paper instead (media/img/<img>.jpg, thumbnail media/poster/fig_<img>.jpg).
  const STEPS = {
    1: [
      { name: "Camera", ids: ["grasp_camera"] },
      { name: "Binoculars", ids: ["grasp_binoculars"] },
      { name: "Hammer", ids: ["grasp_hammer"] },
      { name: "How anchors are chosen", img: "anchors", alt: "Candidate generation, scoring and filtering, and the grasp anchors kept, for one hand and for two",
        note: "Candidates are generated in the object's frame, scored and filtered; the anchors kept are reused for every trajectory." },
    ],
    2: [
      { name: "Root + L wrist + R wrist", ids: ["body_root_lwrist_rwrist"] },
      { name: "Root + R wrist", ids: ["body_root_rwrist"] },
      { name: "Root + L wrist", ids: ["body_root_lwrist"] },
      { name: "L wrist + R wrist", ids: ["body_lwrist_rwrist"] },
      { name: "Root", ids: ["body_root"] },
      { name: "L wrist", ids: ["body_lwrist"] },
      { name: "R wrist", ids: ["body_rwrist"] },
    ],
    3: [
      { name: "Clothes stand · 1 hand", ids: ["hoi_clothesstand"] },
      { name: "Wooden chair · 2 hands", ids: ["hoi_woodchair"] },
      { name: "Large table · 2 hands", ids: ["hoi_largetable"] },
      { name: "One template, varied", img: "augment", alt: "Four rows of a humanoid picking up, carrying and putting down a wooden chair, each with a different grasp and path",
        note: "The same interaction with other grasp poses, pre-grasp motions and transport paths." },
    ],
    4: [
      { name: "Wooden chair", ids: ["ref_woodchair", "trk_woodchair"] },
      { name: "Clothes stand", ids: ["ref_clothesstand", "trk_clothesstand"] },
      { name: "Large table", ids: ["ref_largetable", "trk_largetable"] },
    ],
    5: [
      { name: "Large object", ids: ["g1_sim_pickplace", "g1_real_large"], contain: true },
      { name: "Tabletop", ids: ["g1_sim_tabletop", "g1_real_tabletop"], contain: true },
    ],
  };
  const NEXT = { 1: "Next: body motion", 2: "Next: synthetic HOI", 3: "Next: ManipTracker", 4: "Next: on the G1" };

  // ---- the stage: five steps, one showing. The section is tall and its content sticks, so scrolling down
  // walks through the steps; the rail and the Next button scroll the page to a step's place.
  const flow = $(document, "#method"), stage = $(document, "#stage"), thumbs = $(document, ".thumbs");
  const panels = [...stage.querySelectorAll(".panel")], steps = [...document.querySelectorAll(".rail [data-step]")];
  const next = $(document, "#next");
  const N = steps.length, chosen = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
  let step = 0, inView = false;
  const span = () => flow.offsetHeight - innerHeight;
  const where = (n) => flow.offsetTop + span() * ((n - 1) / N + 0.08);
  const panelOf = (n) => panels.find((p) => +p.dataset.step === n);
  const play = (v) => { v.play().catch(() => {}); };

  function choose(n, i) {
    chosen[n] = i;
    const item = STEPS[n][i], panel = panelOf(n);
    panel.classList.toggle("contain", !!item.contain);
    panel.classList.toggle("still-on", !!item.img);
    const still = $(panel, ".still");
    if (still) {
      still.hidden = !item.img;
      if (item.img) { still.src = `media/img/${item.img}.jpg`; still.alt = item.alt; $(panel, ".note").textContent = item.note; }
    }
    [...panel.querySelectorAll("video")].forEach((v, k) => {
      if (item.img) { v.pause(); return; }
      const c = clip(item.ids[k]);
      if (v.getAttribute("src") !== c.src) { v.poster = c.poster; v.src = c.src; }
      if (n === step && inView) play(v);
    });
    [...thumbs.children].forEach((b, k) => b.setAttribute("aria-selected", String(k === i)));
  }
  function fillThumbs(n) {
    thumbs.classList.toggle("compact", STEPS[n].length > 4);
    thumbs.replaceChildren(...STEPS[n].map((item, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(i === chosen[n]));
      const img = new Image();
      img.src = item.img ? `media/poster/fig_${item.img}.jpg` : clip(item.ids[item.ids.length - 1]).poster;
      img.alt = "";
      img.loading = "lazy";
      const label = document.createElement("span");
      label.textContent = item.name;
      b.append(img, label);
      b.addEventListener("click", () => choose(n, i));
      return b;
    }));
  }
  function render(n) {
    n = Math.max(1, Math.min(N, n));
    if (n !== step) {
      step = n;
      flow.dataset.step = step;
      for (const t of steps) {
        const k = +t.dataset.step;
        if (k === step) t.setAttribute("aria-current", "step"); else t.removeAttribute("aria-current");
        t.parentElement.classList.toggle("done", k < step);
      }
      if (step < N) $(next, "span").textContent = NEXT[step];
      fillThumbs(step);
    }
    for (const p of panels) {
      const on = +p.dataset.step === step;
      p.classList.toggle("on", on);
      const moving = on && inView && !p.classList.contains("still-on");
      for (const v of p.querySelectorAll("video")) { if (moving) play(v); else v.pause(); }
    }
  }
  function goTo(n) { scrollTo({ top: where(Math.max(1, Math.min(N, n))), behavior: reduced ? "auto" : "smooth" }); }
  function onScroll() {
    const y = scrollY - flow.offsetTop;
    inView = y > -innerHeight * 0.5 && y < span() + innerHeight * 0.5;
    render(Math.floor(Math.max(0, Math.min(0.999, y / span())) * N) + 1);
  }
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", onScroll);
  for (const t of steps) t.addEventListener("click", () => goTo(+t.dataset.step));
  next.addEventListener("click", () => goTo(step + 1));
  addEventListener("keydown", (e) => {
    if (!inView || e.target.closest("input, textarea")) return;
    if (e.key === "ArrowRight") goTo(step + 1);
    if (e.key === "ArrowLeft") goTo(step - 1);
  });
  $(document, 'a[href="#method"]').addEventListener("click", (e) => { e.preventDefault(); goTo(1); });
  function fromHash() {
    const m = /^#step=([1-5])$/.exec(location.hash);
    if (m) scrollTo({ top: where(+m[1]), behavior: "auto" });
    onScroll();
  }
  addEventListener("hashchange", fromHash);
  fromHash();

  // ---- more results: three sets of clips in one grid
  const SETS = {
    long: [
      ["long_woodchair", "Wooden chair", "Long sequence"], ["long_largetable", "Large table", "Long sequence"], ["long_plasticbox", "Plastic box", "Long sequence"],
    ],
    push: [
      ["push_grasp2_forward", "Push forward", "Grasp A"], ["push_grasp2_backward", "Pull backward", "Grasp A"],
      ["push_grasp3_forward", "Push forward", "Grasp B"], ["push_grasp3_backward", "Pull backward", "Grasp B"],
    ],
    g1: [
      ["g1body_root", "Root", "Sparse tracking"], ["g1body_lwrist", "L wrist", "Sparse tracking"], ["g1body_root_lwrist", "Root + L wrist", "Sparse tracking"],
      ["g1body_wrists", "L wrist + R wrist", "Sparse tracking"], ["g1body_root_wrists_look", "Root + L wrist + R wrist", "Sparse tracking"],
      ["g1body_root_wrists_salute", "Root + L wrist + R wrist", "Sparse tracking"], ["g1body_rwrist_writing", "R wrist", "Writing"],
    ],
  };
  // clips play only while on screen
  const playing = new IntersectionObserver((entries) => {
    for (const e of entries) { if (e.intersectionRatio >= 0.4) play(e.target); else e.target.pause(); }
  }, { threshold: [0, 0.4] });
  const grid = $(document, "#grid"), tabs = [...document.querySelectorAll(".tabs [data-set]")];
  function showSet(id) {
    for (const v of grid.querySelectorAll("video")) playing.unobserve(v);
    grid.replaceChildren(...SETS[id].map(([name, title, kind]) => {
      const fig = document.createElement("figure");
      fig.className = "card";
      const v = document.createElement("video");
      Object.assign(v, { muted: true, loop: true, playsInline: true, preload: "none", controls: true, ...clip(name) });
      const cap = document.createElement("figcaption");
      const k = document.createElement("span");
      k.textContent = kind;
      cap.append(k, title);
      fig.append(v, cap);
      playing.observe(v);
      return fig;
    }));
    for (const t of tabs) t.setAttribute("aria-selected", String(t.dataset.set === id));
  }
  for (const t of tabs) t.addEventListener("click", () => showSet(t.dataset.set));
  showSet("long");
  for (const v of document.querySelectorAll("video[data-autoplay]")) playing.observe(v);

  // ---- the citation's Copy button
  const copy = $(document, ".cite .copy");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($(document, "#bibtex").textContent); copy.textContent = "Copied"; }
    catch (e) { copy.textContent = "Select and copy"; }
    setTimeout(() => { copy.textContent = "Copy"; }, 1800);
  });
})();
