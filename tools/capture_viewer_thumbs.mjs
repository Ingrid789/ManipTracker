#!/usr/bin/env node
// Capture crisp 480x270 thumbnails directly from the live Three.js 3D viewer AND smoke-test all 48 clips!
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const REPO = "/home/yufeizhu/repos/ManipTracker";
const THUMB_DIR = path.join(REPO, "media/viewer/thumbs");
fs.mkdirSync(THUMB_DIR, { recursive: true });

const srv = spawn("python3", ["-m", "http.server", "8766", "--bind", "127.0.0.1"], {
  cwd: REPO, stdio: "ignore",
});
const chrome = spawn("/usr/bin/google-chrome", [
  "--headless=new", "--no-sandbox", "--disable-gpu-sandbox",
  "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
  "--remote-debugging-port=9230", "--window-size=960,600", "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitCdp() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await fetch("http://127.0.0.1:9230/json/list").then((r) => r.json());
      const page = list.find((t) => t.type === "page");
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error("Chrome CDP not ready");
}

let errors = 0;
try {
  const wsUrl = await waitCdp();
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) rej(new Error(msg.error.message)); else res(msg.result);
    } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
      errors++;
      console.log("[CONSOLE ERROR]", msg.params.args.map((a) => a.value ?? a.description).join(" "));
    } else if (msg.method === "Runtime.exceptionThrown") {
      errors++;
      console.log("[EXCEPTION]", msg.params.exceptionDetails.text, msg.params.exceptionDetails.exception?.description || "");
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const evalJs = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result?.value;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 960, height: 600, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: "http://127.0.0.1:8766/index.html?capture=1" });

  // Wait until viewer is ready
  for (let i = 0; i < 60; i++) {
    const ready = await evalJs(`Boolean(window.__resultsViewer?.captureClip)`);
    if (ready) break;
    await sleep(300);
  }
  await evalJs(`document.querySelector('#results').scrollIntoView({ behavior: 'instant' });`);
  await sleep(500);

  const manifest = JSON.parse(fs.readFileSync(path.join(REPO, "media/viewer/manifest.json"), "utf8"));
  let count = 0;
  for (const [tabId, tab] of Object.entries(manifest.tabs)) {
    for (const clip of tab.clips) {
      const frac = clip.id.includes("inhand") ? 0.50 : (clip.id.includes("soccer") || clip.id.includes("throw") || clip.id.includes("basketball")) ? 0.52 : 0.45;
      const dataUrl = await evalJs(`(async () => {
        const src = await window.__resultsViewer.captureClip(${JSON.stringify(tabId)}, ${JSON.stringify(clip.id)}, ${frac});
        const img = new Image();
        img.src = src;
        await img.decode();
        const c = document.createElement('canvas');
        c.width = 480; c.height = 270;
        const ctx = c.getContext('2d');
        const sw = img.width, sh = img.height, ar = 480 / 270;
        let sx = 0, sy = 0, cw = sw, ch = sh;
        if (sw / sh > ar) { cw = sh * ar; sx = (sw - cw) / 2; }
        else { ch = sw / ar; sy = (sh - ch) / 2; }
        ctx.drawImage(img, sx, sy, cw, ch, 0, 0, 480, 270);
        return c.toDataURL('image/jpeg', 0.86);
      })()`);
      const b64 = dataUrl.split(",")[1];
      const outPath = path.join(THUMB_DIR, `${clip.id}.jpg`);
      fs.writeFileSync(outPath, Buffer.from(b64, "base64"));
      count++;
      console.log(`[OK ${String(count).padStart(2, "0")}] ${tabId}/${clip.id}.jpg (${(fs.statSync(outPath).size / 1024).toFixed(1)} KB)`);
    }
  }
  console.log(`=== CAPTURED & VERIFIED ${count} CLIPS (errors=${errors}) ===`);
  ws.close();
  if (errors > 0) process.exitCode = 1;
} finally {
  chrome.kill();
  srv.kill();
}
