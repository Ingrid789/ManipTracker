// Screenshots of the page at several scroll positions, to check the layout:  node tools/shots.mjs [url] [outdir]
// Needs puppeteer-core and a Chrome (CHROME=/path/to/chrome); serve the page first (python3 -m http.server 8000).
import { createRequire } from "node:module";
const require = createRequire(process.env.NODE_MODULES ? process.env.NODE_MODULES + "/" : import.meta.url);
const puppeteer = require("puppeteer-core");
const url = process.argv[2] || "http://localhost:8000/", out = process.argv[3] || "/tmp/mt";
const browser = await puppeteer.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", headless: "new",
  args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"] });
for (const [name, w, h] of [["desk", 1440, 810], ["phone", 390, 780]]) {
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log("PAGE ERROR", e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") console.log(m.type(), m.text()); });
  page.on("requestfailed", (r) => console.log("FAILED", r.url()));
  await page.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
  await page.goto(url, { waitUntil: "load" });
  await new Promise((r) => setTimeout(r, 1500));
  const info = await page.evaluate(() => ({ hero: document.querySelector(".scrolly").offsetHeight, flowTop: document.querySelector("#method").offsetTop,
    flow: document.querySelector("#method").offsetHeight, total: document.documentElement.scrollHeight, over: document.documentElement.scrollWidth - innerWidth,
    ovTop: document.querySelector("#overview").offsetTop, galTop: document.querySelector("#results").offsetTop, numTop: document.querySelector("#numbers").offsetTop }));
  console.log(name, JSON.stringify(info));
  const at = [];
  for (const p of [0, 0.08, 0.22, 0.29, 0.4, 0.5, 0.62, 0.72, 0.8, 0.9, 0.99]) at.push([`hero${String(Math.round(p * 100)).padStart(2, "0")}`, (info.hero - h) * p]);
  for (let k = 0; info.ovTop + h * 0.9 * k < info.flowTop - h * 0.3; k++) at.push([`ov${k + 1}`, info.ovTop + h * 0.9 * k]);
  for (let n = 1; n <= 5; n++) at.push([`step${n}`, info.flowTop + (info.flow - h) * ((n - 1) / 5 + 0.08)]);
  at.push(["gal", info.galTop], ["num", info.numTop - 40], ["end", info.total]);
  for (const [tag, y] of at) {
    await page.evaluate((y) => scrollTo({ top: y, behavior: "instant" }), y);
    await new Promise((r) => setTimeout(r, 1300));
    await page.screenshot({ path: `${out}/${name}_${tag}.jpg`, quality: 70 });
    // steps 1 and 3 end their choices with a figure from the paper: one more shot with it chosen
    if (tag === "step1" || tag === "step3") {
      await page.evaluate(() => document.querySelector(".thumbs button:last-child").click());
      await new Promise((r) => setTimeout(r, 900));
      await page.screenshot({ path: `${out}/${name}_${tag}fig.jpg`, quality: 70 });
      await page.evaluate(() => document.querySelector(".thumbs button").click());
    }
  }
  await page.close();
}
await browser.close();
