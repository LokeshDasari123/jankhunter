/**
 * JankHunter Demo App — CLEAN reference version.
 *
 * Elements tracked:
 *   sprite      - bouncing player sprite
 *   hud_bar     - health bar in the HUD
 *   menu_panel  - sliding menu panel
 *   line_chart  - mini line chart (bottom-right)
 *
 * Ground-truth sidecar:
 *   window.__jh_gt is updated every frame with { tracks: { [label]: TrackPoint } }.
 *   Playwright reads this via page.evaluate() after capture.
 */

"use strict";

// ─── Canvas setup ─────────────────────────────────────────────────────────────
const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");

function resize() {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}
resize();
window.addEventListener("resize", resize);

// ─── State ────────────────────────────────────────────────────────────────────
const W = () => canvas.width;
const H = () => canvas.height;

// Sprite — bouncing ball
const sprite = {
  x: 100, y: 100,
  vx: 160, vy: 120,   // px/s  ← correct: velocity is per-second
  r: 24,
  color: "#4af",
};

// HUD health bar
const hud = {
  hp: 100, maxHp: 100,
  x: 16, y: 16,
  w: 200, h: 20,
  label: "HP",
};

// Sliding menu panel
const menu = {
  open: false,
  x: 0,               // current left edge (updated in update())
  targetX: 0,
  w: 180, h: 220,
  speed: 400,         // px/s
};

// Line chart (mini sparkline)
const chart = {
  data: [],
  maxPts: 60,
  x: () => W() - 200 - 16,
  y: () => H() - 100 - 16,
  w: 200, h: 100,
};

// Ground-truth sidecar exposed to Playwright
window.__jh_gt = { tracks: {}, frame: 0 };
window.__jh_gt_history = [];

// Font loading guard — measure HUD only after fonts are ready
let fontReady = false;
document.fonts.ready.then(() => { fontReady = true; });

// ─── Menu toggle on click ─────────────────────────────────────────────────────
canvas.addEventListener("click", () => {
  menu.open = !menu.open;
});

// ─── Reset counter (used in buggy variant to trigger flicker) ─────────────────
let frameCount = 0;
let stateResetEvery = 0; // 0 = never (clean version never resets)

// ─── Timing ───────────────────────────────────────────────────────────────────
let lastTime = null;
const startTime = performance.now();

// ─── Update ───────────────────────────────────────────────────────────────────
function update(dt) {
  // Sprite: correct dt-based motion
  sprite.x += sprite.vx * dt;
  sprite.y += sprite.vy * dt;

  // Bounce off walls
  if (sprite.x - sprite.r < 0) { sprite.x = sprite.r; sprite.vx = Math.abs(sprite.vx); }
  if (sprite.x + sprite.r > W()) { sprite.x = W() - sprite.r; sprite.vx = -Math.abs(sprite.vx); }
  if (sprite.y - sprite.r < 0) { sprite.y = sprite.r; sprite.vy = Math.abs(sprite.vy); }
  if (sprite.y + sprite.r > H()) { sprite.y = H() - sprite.r; sprite.vy = -Math.abs(sprite.vy); }

  // HUD: slowly drain HP
  hud.hp = Math.max(0, hud.hp - 0.05 * dt * 60);

  // Menu: slide in/out
  menu.targetX = menu.open ? 0 : -menu.w;
  const dx = menu.targetX - menu.x;
  menu.x += Math.sign(dx) * Math.min(menu.speed * dt, Math.abs(dx));

  // Chart: push new data point
  chart.data.push(50 + 40 * Math.sin(performance.now() / 800));
  if (chart.data.length > chart.maxPts) chart.data.shift();

  frameCount++;
}

// ─── Draw ─────────────────────────────────────────────────────────────────────
function draw(now) {
  ctx.clearRect(0, 0, W(), H());

  // Background grid
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1;
  for (let gx = 0; gx < W(); gx += 40) {
    ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H()); ctx.stroke();
  }
  for (let gy = 0; gy < H(); gy += 40) {
    ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W(), gy); ctx.stroke();
  }

  // Sprite
  ctx.beginPath();
  ctx.arc(sprite.x, sprite.y, sprite.r, 0, Math.PI * 2);
  ctx.fillStyle = sprite.color;
  ctx.fill();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2;
  ctx.stroke();

  // HUD health bar
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fillRect(hud.x - 4, hud.y - 4, hud.w + 8, hud.h + 24);

  if (fontReady) {
    ctx.font = "12px 'Courier New'";
    ctx.fillStyle = "#aaa";
    ctx.fillText(hud.label, hud.x, hud.y + hud.h + 14);
  }

  const fillW = Math.max(0, (hud.hp / hud.maxHp) * hud.w);
  ctx.fillStyle = "#222";
  ctx.fillRect(hud.x, hud.y, hud.w, hud.h);
  ctx.fillStyle = hud.hp > 50 ? "#4c4" : hud.hp > 25 ? "#ca4" : "#c44";
  ctx.fillRect(hud.x, hud.y, fillW, hud.h);
  ctx.strokeStyle = "#888";
  ctx.lineWidth = 1;
  ctx.strokeRect(hud.x, hud.y, hud.w, hud.h);

  // Sliding menu panel
  const mx = menu.x;
  const my = Math.round(H() / 2 - menu.h / 2);
  ctx.fillStyle = "rgba(30,30,60,0.92)";
  ctx.fillRect(mx, my, menu.w, menu.h);
  ctx.strokeStyle = "#44f";
  ctx.lineWidth = 2;
  ctx.strokeRect(mx, my, menu.w, menu.h);
  ctx.fillStyle = "#aaf";
  ctx.font = "14px 'Courier New'";
  ctx.fillText("[ MENU ]", mx + 12, my + 28);
  ["Resume", "Settings", "Help", "Quit"].forEach((item, i) => {
    ctx.fillStyle = "#ccc";
    ctx.font = "12px 'Courier New'";
    ctx.fillText(item, mx + 20, my + 60 + i * 26);
  });

  // Line chart
  const cx = chart.x(), cy = chart.y();
  ctx.fillStyle = "rgba(0,0,0,0.5)";
  ctx.fillRect(cx, cy, chart.w, chart.h);
  ctx.strokeStyle = "#333";
  ctx.lineWidth = 1;
  ctx.strokeRect(cx, cy, chart.w, chart.h);

  if (chart.data.length > 1) {
    ctx.beginPath();
    ctx.strokeStyle = "#0f8";
    ctx.lineWidth = 1.5;
    chart.data.forEach((v, i) => {
      const px = cx + (i / (chart.maxPts - 1)) * chart.w;
      const py = cy + chart.h - (v / 100) * chart.h;
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    });
    ctx.stroke();
  }
}

// ─── Ground-truth export ──────────────────────────────────────────────────────
function exportGT(now) {
  const t = (now - startTime) / 1000;

  function mkPoint(x, y, w, h, visible = true) {
    return {
      t,
      bbox: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)],
      centroid: [Math.round(x + w / 2), Math.round(y + h / 2)],
      area: Math.round(w * h),
      visible,
    };
  }

  const sprW = sprite.r * 2, sprH = sprite.r * 2;
  const myMenu = Math.round(H() / 2 - menu.h / 2);
  const menuVisible = menu.x > -menu.w + 4;

  window.__jh_gt = {
    frame: frameCount,
    t,
    tracks: {
      sprite: mkPoint(sprite.x - sprite.r, sprite.y - sprite.r, sprW, sprH),
      hud_bar: mkPoint(hud.x, hud.y, hud.w, hud.h),
      menu_panel: mkPoint(menu.x, myMenu, menu.w, menu.h, menuVisible),
      line_chart: mkPoint(chart.x(), chart.y(), chart.w, chart.h),
    },
  };
  window.__jh_gt_history.push(window.__jh_gt);
}

// ─── Main loop ────────────────────────────────────────────────────────────────
function loop(now) {
  if (lastTime === null) lastTime = now;
  const dt = Math.min((now - lastTime) / 1000, 0.1); // cap at 100 ms
  lastTime = now;

  update(dt);
  draw(now);
  exportGT(now);

  requestAnimationFrame(loop);
}

requestAnimationFrame(loop);
