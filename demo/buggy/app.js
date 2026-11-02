/**
 * JankHunter Demo App — BUGGY version.
 *
 * This file contains THREE intentional source-level bugs for the fix-loop to find
 * and patch. It is otherwise identical in structure to demo/app/app.js.
 *
 * Bug 1 — STUTTER + JITTER (sprite movement)
 *   Location: update() sprite motion
 *   Root cause: uses a fixed 3 px step per frame instead of velocity * dt,
 *               AND applies Math.floor() to coordinates, introducing a
 *               1-px rounding jitter.
 *   Expected defects: "stutter" (frame-rate-dependent velocity), "jitter"
 *
 * Bug 2 — LAYOUT JUMP (HUD health bar)
 *   Location: draw() HUD label measurement
 *   Root cause: measureText() and label render happen BEFORE document.fonts.ready,
 *               so the first few frames show an incorrectly-sized label region,
 *               and the bar appears to jump once the real font loads.
 *   Expected defect: "layout_jump"
 *
 * Bug 3 — FLICKER (sprite)
 *   Location: update() state reset
 *   Root cause: every 120 frames, the sprite object is RE-CREATED as a new
 *               object literal, causing the tracker to see a 1-frame ID gap
 *               (old track ends, new track starts at the same position).
 *   Expected defect: "flicker"
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

// BUG 3 — sprite is stored in a mutable variable so it can be replaced
let sprite = {
  x: 100, y: 100,
  vx: 160, vy: 120,
  r: 24,
  color: "#4af",
  visible: true,
};

const hud = {
  hp: 100, maxHp: 100,
  x: 16, y: 16,
  w: 40, h: 20,
  label: "HP",
};

const menu = {
  open: false,
  x: 0,
  targetX: 0,
  w: 180, h: 220,
  speed: 400,
};

const chart = {
  data: [],
  maxPts: 60,
  x: () => W() - 200 - 16,
  y: () => H() - 100 - 16,
  w: 200, h: 100,
};

window.__jh_gt = { tracks: {}, frame: 0 };
window.__jh_gt_history = [];

// BUG 2 — delayed font/content readiness changes the content-sized HUD after
// it is already visible, producing a measurable width jump.
let fontReady = false;
window.setTimeout(() => {
  fontReady = true;
  hud.label = "HEALTH";
  ctx.font = "14px 'Courier New'";
  hud.w = Math.ceil(ctx.measureText(hud.label).width + 24);
}, 900);

let frameCount = 0;
const STATE_RESET_EVERY = 120; // BUG 3 trigger interval

let lastTime = null;
const startTime = performance.now();

// ─── Update ───────────────────────────────────────────────────────────────────
function update(dt) {
  // BUG 1 — fixed 3 px/frame step instead of velocity * dt
  //          Math.floor adds a 1-px rounding jitter on each axis.
  sprite.x = Math.floor(sprite.x + 3);   // WRONG: ignores dt and vx
  sprite.y = Math.floor(sprite.y + 2);   // WRONG: ignores dt and vy

  // Bounce (uses same fixed-step logic, so it will overshoot/undershoot)
  if (sprite.x - sprite.r < 0) { sprite.x = sprite.r; sprite.vx = Math.abs(sprite.vx); }
  if (sprite.x + sprite.r > W()) { sprite.x = W() - sprite.r; sprite.vx = -Math.abs(sprite.vx); }
  if (sprite.y - sprite.r < 0) { sprite.y = sprite.r; sprite.vy = Math.abs(sprite.vy); }
  if (sprite.y + sprite.r > H()) { sprite.y = H() - sprite.r; sprite.vy = -Math.abs(sprite.vy); }

  hud.hp = Math.max(0, hud.hp - 0.05 * dt * 60);

  menu.targetX = menu.open ? 0 : -menu.w;
  const dx = menu.targetX - menu.x;
  menu.x += Math.sign(dx) * Math.min(menu.speed * dt, Math.abs(dx));

  chart.data.push(50 + 40 * Math.sin(performance.now() / 800));
  if (chart.data.length > chart.maxPts) chart.data.shift();

  frameCount++;

  // BUG 1 — synchronous work stalls the main thread every 45 frames.
  if (frameCount % 45 === 0) {
    const started = performance.now();
    while (performance.now() - started < 45) { /* simulate an expensive update */ }
  }

  // BUG 3 — replacing the sprite drops it for the reset frame.
  if (frameCount % STATE_RESET_EVERY === 0) {
    const oldX = sprite.x, oldY = sprite.y;
    sprite = {                // ← new object: tracker loses continuity
      x: oldX, y: oldY,
      vx: 160, vy: 120,
      r: 24,
      color: "#4af",
      visible: false,
    };
  } else {
    sprite.visible = true;
  }
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
  if (sprite.visible) {
    ctx.beginPath();
    ctx.arc(sprite.x, sprite.y, sprite.r, 0, Math.PI * 2);
    ctx.fillStyle = sprite.color;
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // BUG 2 — the late label/font update resizes the HUD while visible.
  ctx.fillStyle = "rgba(0,0,0,0.6)";
  ctx.fillRect(hud.x - 4, hud.y - 4, hud.w + 8, hud.h + 24);

  if (fontReady) {
    ctx.font = "12px 'Courier New'";
    // BUG 2: no await on fonts.ready — text width may be wrong at first
    const textW = ctx.measureText(hud.label).width;
    ctx.fillStyle = "#aaa";
    ctx.fillText(hud.label, hud.x + hud.w / 2 - textW / 2, hud.y + hud.h + 14);
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

  const spriteVisible = sprite.visible;

  window.__jh_gt = {
    frame: frameCount,
    t,
    tracks: {
      sprite: mkPoint(sprite.x - sprite.r, sprite.y - sprite.r, sprW, sprH, spriteVisible),
      hud_bar: mkPoint(hud.x, hud.y, hud.w, hud.h),
      menu_panel: mkPoint(menu.x, myMenu, menu.w, menu.h, menuVisible),
      line_chart: mkPoint(chart.x(), chart.y(), chart.w, chart.h),
    },
  };
  window.__jh_gt_history.push(window.__jh_gt);
}

// ─── Menu toggle ──────────────────────────────────────────────────────────────
canvas.addEventListener("click", () => {
  menu.open = !menu.open;
});

// ─── Main loop ────────────────────────────────────────────────────────────────
function loop(now) {
  if (lastTime === null) lastTime = now;
  const dt = Math.min((now - lastTime) / 1000, 0.1);
  lastTime = now;

  update(dt);
  draw(now);
  exportGT(now);

  requestAnimationFrame(loop);
}

requestAnimationFrame(loop);
