/**
 * Purely-geometric decorative helpers used to give the card a
 * "security document" look (soft wavy guilloché lines + a sunburst
 * seal) without depending on any external artwork. Colors are driven
 * entirely by the brand colors passed in from the request JSON.
 */

function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  const full =
    clean.length === 3
      ? clean.split('').map((c) => c + c).join('')
      : clean;
  const num = parseInt(full, 16);
  return {
    r: (num >> 16) & 255,
    g: (num >> 8) & 255,
    b: num & 255,
  };
}

function mixHex(hexA, hexB, t) {
  const a = hexToRgb(hexA);
  const b = hexToRgb(hexB);
  const r = Math.round(a.r + (b.r - a.r) * t);
  const g = Math.round(a.g + (b.g - a.g) * t);
  const bl = Math.round(a.b + (b.b - a.b) * t);
  return `#${[r, g, bl].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/**
 * Draws a band of soft wavy lines across a rectangle, alternating
 * between the two brand colors, reminiscent of a security-paper
 * guilloché pattern. Kept low-opacity so it never fights with text.
 */
function drawWaveBackground(doc, { x, y, w, h, colorA, colorB, lineCount = 26, opacity = 0.16 }) {
  doc.save();
  doc.rect(x, y, w, h).clip();

  const amplitude = h * 0.09;
  const step = h / (lineCount - 1);

  for (let i = 0; i < lineCount; i++) {
    const baseY = y + i * step;
    const t = i / (lineCount - 1);
    const color = mixHex(colorA, colorB, t);
    const phase = (i % 2 === 0 ? 1 : -1) * (Math.PI / 2);

    doc.save();
    doc.opacity(opacity);
    doc.lineWidth(1.1);
    doc.strokeColor(color);

    const points = [];
    const segments = 24;
    for (let s = 0; s <= segments; s++) {
      const px = x + (w * s) / segments;
      const py = baseY + amplitude * Math.sin((s / segments) * Math.PI * 2.4 + phase);
      points.push([px, py]);
    }

    doc.moveTo(points[0][0], points[0][1]);
    for (let s = 1; s < points.length; s++) {
      doc.lineTo(points[s][0], points[s][1]);
    }
    doc.stroke();
    doc.restore();
  }

  doc.restore();
}

/**
 * Draws a simple circular sunburst / rosette watermark, used as a
 * generic "official seal" placeholder when the caller doesn't supply
 * their own seal/crest image.
 */
function drawSunburstSeal(doc, { cx, cy, radius, color, opacity = 0.18, rays = 32 }) {
  doc.save();
  doc.opacity(opacity);
  doc.fillColor(color);

  for (let i = 0; i < rays; i++) {
    const a0 = (i / rays) * Math.PI * 2;
    const a1 = a0 + Math.PI / rays;
    doc.moveTo(cx, cy);
    doc.lineTo(cx + radius * Math.cos(a0), cy + radius * Math.sin(a0));
    doc.lineTo(cx + radius * Math.cos(a1), cy + radius * Math.sin(a1));
    doc.closePath();
    doc.fill();
  }

  doc.circle(cx, cy, radius * 0.32).fill('#ffffff');
  doc.restore();

  doc.save();
  doc.opacity(opacity * 1.3);
  doc.lineWidth(1);
  doc.strokeColor(color);
  doc.circle(cx, cy, radius).stroke();
  doc.circle(cx, cy, radius * 0.32).stroke();
  doc.restore();
}

/** Thin double hairline rule, a common ID-card header/footer accent. */
function drawDoubleRule(doc, { x, y, w, color, opacity = 1 }) {
  doc.save();
  doc.opacity(opacity);
  doc.lineWidth(1.4);
  doc.strokeColor(color);
  doc.moveTo(x, y).lineTo(x + w, y).stroke();
  doc.lineWidth(0.5);
  doc.moveTo(x, y + 2.2).lineTo(x + w, y + 2.2).stroke();
  doc.restore();
}

/**
 * Deterministic seeded PRNG (mulberry32) so each card gets its own
 * unique-but-reproducible micro-variation in the security pattern,
 * derived from the student ID / serial. Two renders of the SAME
 * student produce the SAME pattern; two DIFFERENT students produce
 * visibly different fine-line patterns, which is the same principle
 * real security printers use to make wholesale copying harder.
 */
function makeSeededRandom(seedStr) {
  let h = 1779033703 ^ String(seedStr || 'default').length;
  for (let i = 0; i < String(seedStr || 'default').length; i++) {
    h = Math.imul(h ^ String(seedStr).charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  let a = h >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Repeats a short text string edge-to-edge along a thin horizontal
 * band, like the microprinted borders found on banknotes/IDs. At
 * print resolution it reads as a fine textured line; on screen at
 * normal zoom it looks like a hairline rule.
 */
function drawMicrotextBand(doc, { x, y, w, text, color, opacity = 0.35, fontSize = 2.6 }) {
  doc.save();
  doc.opacity(opacity);
  doc.fillColor(color);
  doc.font('Helvetica-Bold').fontSize(fontSize);

  const unit = `${text} `;
  const unitWidth = doc.widthOfString(unit) || 1;
  const repeats = Math.ceil(w / unitWidth) + 1;
  doc.text(unit.repeat(repeats), x, y, { width: w, height: fontSize + 1, lineBreak: false });
  doc.restore();
}

/**
 * Faint, tiled, rotated watermark text (pantograph-style) across the
 * whole card — the same "hidden until copied" trick used on
 * cheques/certificates. Purely decorative and derived from the
 * organization name, so it's automatically unique to the branding.
 */
function drawPantographWatermark(doc, { x, y, w, h, text, color, opacity = 0.06, angle = -28, fontSize = 6.2 }) {
  doc.save();
  doc.rect(x, y, w, h).clip();
  doc.opacity(opacity);
  doc.fillColor(color);
  doc.font('Helvetica-Bold').fontSize(fontSize);

  const label = ` ${text.toUpperCase()} `;
  const stepX = doc.widthOfString(label) + fontSize * 2;
  const stepY = fontSize * 3.4;

  const diag = Math.sqrt(w * w + h * h);
  const cols = Math.ceil((diag * 2) / stepX) + 2;
  const rows = Math.ceil((diag * 2) / stepY) + 2;
  const cx = x + w / 2;
  const cy = y + h / 2;
  const rad = (angle * Math.PI) / 180;

  // PDFKit auto-paginates if a text call's y-coordinate falls outside the
  // current page bounds — even inside a clip region — so we must only call
  // doc.text() for tiles whose *rotated* position actually lands on the page.
  const pageW = doc.page.width;
  const pageH = doc.page.height;
  const margin = fontSize * 4;

  for (let r = -rows; r < rows; r++) {
    for (let c = -cols; c < cols; c++) {
      const lx = c * stepX + (r % 2 === 0 ? 0 : stepX / 2) - diag;
      const ly = r * stepY - diag;
      // Rotation sign convention in PDFKit's coordinate space can be
      // ambiguous from here, so check both rotation directions and only
      // skip a tile if it's off-page under both — false negatives (skipping
      // a tile that would actually be on-page) are far less costly than a
      // false positive (drawing a tile that re-triggers PDFKit's
      // auto-pagination), so we bias toward keeping tiles when unsure.
      let onPage = false;
      for (const sign of [1, -1]) {
        const a = sign * rad;
        const rx = cx + (lx * Math.cos(a) - ly * Math.sin(a));
        const ry = cy + (lx * Math.sin(a) + ly * Math.cos(a));
        if (rx >= -margin && rx <= pageW + margin && ry >= -margin && ry <= pageH + margin) {
          onPage = true;
          break;
        }
      }
      if (!onPage) continue;

      doc.save();
      doc.rotate(angle, { origin: [cx, cy] });
      doc.text(label, lx, ly, { lineBreak: false });
      doc.restore();
    }
  }
  doc.restore();
}

/**
 * A fine spirograph-style rosette (rose curve), the kind of intricate
 * medallion used as a corner guilloché feature on secure documents.
 * `seedRandom` lets each card render a subtly different rotation/petal
 * count so patterns aren't identical card-to-card.
 */
function drawGuillocheRosette(doc, { cx, cy, radius, color, opacity = 0.22, petals = 7, seedRandom }) {
  const rand = seedRandom || Math.random;
  const rotationOffset = rand() * Math.PI * 2;
  const rings = 3;

  doc.save();
  doc.opacity(opacity);
  doc.lineWidth(0.35);
  doc.strokeColor(color);

  for (let ring = 0; ring < rings; ring++) {
    const r = radius * (0.45 + ring * 0.22);
    const k = petals + ring;
    const segments = 260;
    let started = false;
    for (let s = 0; s <= segments; s++) {
      const theta = (s / segments) * Math.PI * 2;
      const rr = r * Math.cos(k * theta);
      const px = cx + rr * Math.cos(theta + rotationOffset);
      const py = cy + rr * Math.sin(theta + rotationOffset);
      if (!started) {
        doc.moveTo(px, py);
        started = true;
      } else {
        doc.lineTo(px, py);
      }
    }
    doc.stroke();
  }

  doc.circle(cx, cy, radius * 0.06).fill(color);
  doc.restore();
}

/**
 * Simulates an optically-variable-ink (OVI) foil strip — the
 * color-shifting band seen on many national IDs — as a static
 * multi-stop gradient bar. It won't shift in real life on paper, but
 * gives cards the visual language of a hologram/foil security strip.
 */
function drawOviStrip(doc, { x, y, w, h }) {
  doc.save();
  const grad = doc.linearGradient(x, y, x + w, y);
  grad.stop(0, '#7fb8e0').stop(0.2, '#c9a8e0').stop(0.4, '#e8b8c8').stop(0.6, '#f5d98a').stop(0.8, '#9fe0c8').stop(1, '#7fb8e0');
  doc.rect(x, y, w, h).fill(grad);
  doc.opacity(0.55);
  doc.rect(x, y, w, h).fill(grad);
  doc.restore();
}

/**
 * Fine crosshatch / lattice of thin diagonal lines in two directions,
 * the kind of engine-turned lattice texture used as security-paper
 * background fill. Purely geometric, low-opacity by default.
 */
function drawLatticePattern(doc, { x, y, w, h, color, opacity = 0.08, spacing = 3.2, angle = 30 }) {
  doc.save();
  doc.rect(x, y, w, h).clip();
  doc.opacity(opacity);
  doc.lineWidth(0.25);
  doc.strokeColor(color);

  const diag = Math.sqrt(w * w + h * h);
  const cx = x + w / 2;
  const cy = y + h / 2;
  const count = Math.ceil((diag * 1.5) / spacing);

  [angle, -angle].forEach((a) => {
    doc.save();
    doc.rotate(a, { origin: [cx, cy] });
    for (let i = -count; i <= count; i++) {
      const lx = cx + i * spacing;
      doc.moveTo(lx, cy - diag).lineTo(lx, cy + diag).stroke();
    }
    doc.restore();
  });

  doc.restore();
}

/**
 * Scattered fine dot noise ("stipple") seeded per-card, similar to the
 * random micro-texture printed as an anti-scan / anti-copy measure on
 * secure documents. Deterministic per card via seedRandom.
 */
function drawSecurityDots(doc, { x, y, w, h, color, opacity = 0.12, count = 900, seedRandom, dotRadius = 0.28 }) {
  const rand = seedRandom || Math.random;
  doc.save();
  doc.opacity(opacity);
  doc.fillColor(color);
  for (let i = 0; i < count; i++) {
    const px = x + rand() * w;
    const py = y + rand() * h;
    const r = dotRadius * (0.6 + rand() * 0.8);
    doc.circle(px, py, r).fill();
  }
  doc.restore();
}

/** Concentric thin rings, e.g. behind a photo, evoking an embossed security halo. */
function drawConcentricRings(doc, { cx, cy, rMax, rings = 10, color, opacity = 0.14 }) {
  doc.save();
  doc.opacity(opacity);
  doc.lineWidth(0.3);
  doc.strokeColor(color);
  for (let i = 1; i <= rings; i++) {
    doc.circle(cx, cy, (rMax * i) / rings).stroke();
  }
  doc.restore();
}

/**
 * Tiles a (typically small, square-ish) image — meant for a brand logo —
 * across a region at low opacity, rotated, so the logo itself becomes
 * part of the security-pattern texture rather than a single watermark.
 */
function drawTiledImageWatermark(doc, { x, y, w, h, imageBuffer, opacity = 0.07, tileSize = 10, angle = 20, gap = 6 }) {
  if (!imageBuffer) return;
  doc.save();
  doc.rect(x, y, w, h).clip();
  doc.opacity(opacity);

  const diag = Math.sqrt(w * w + h * h);
  const cx = x + w / 2;
  const cy = y + h / 2;
  const step = tileSize + gap;
  const n = Math.ceil((diag * 1.5) / step);
  const rad = (angle * Math.PI) / 180;

  const pageW = doc.page.width;
  const pageH = doc.page.height;
  const margin = tileSize * 2;

  for (let r = -n; r <= n; r++) {
    for (let c = -n; c <= n; c++) {
      const lx = c * step + (r % 2 === 0 ? 0 : step / 2) - tileSize / 2;
      const ly = r * step - tileSize / 2;

      let onPage = false;
      for (const sign of [1, -1]) {
        const a = sign * rad;
        const rx = cx + (lx * Math.cos(a) - ly * Math.sin(a));
        const ry = cy + (lx * Math.sin(a) + ly * Math.cos(a));
        if (rx >= -margin && rx <= pageW + margin && ry >= -margin && ry <= pageH + margin) {
          onPage = true;
          break;
        }
      }
      if (!onPage) continue;

      doc.save();
      doc.rotate(angle, { origin: [cx, cy] });
      try {
        doc.image(imageBuffer, lx, ly, { fit: [tileSize, tileSize] });
      } catch (e) {
        // ignore individual tile failures (e.g. malformed image edge cases)
      }
      doc.restore();
    }
  }
  doc.restore();
}

/** A single large, centered, very faint logo watermark (classic passport/ID background mark). */
function drawCenteredLogoWatermark(doc, { x, y, w, h, imageBuffer, opacity = 0.08, sizeRatio = 0.62, angle = 0 }) {
  if (!imageBuffer) return;
  const size = Math.min(w, h) * sizeRatio;
  const cx = x + w / 2;
  const cy = y + h / 2;
  doc.save();
  doc.rect(x, y, w, h).clip();
  doc.opacity(opacity);
  if (angle) doc.rotate(angle, { origin: [cx, cy] });
  doc.image(imageBuffer, cx - size / 2, cy - size / 2, { fit: [size, size] });
  doc.restore();
}

module.exports = {
  hexToRgb,
  mixHex,
  drawWaveBackground,
  drawSunburstSeal,
  drawDoubleRule,
  makeSeededRandom,
  drawMicrotextBand,
  drawPantographWatermark,
  drawGuillocheRosette,
  drawOviStrip,
  drawLatticePattern,
  drawSecurityDots,
  drawConcentricRings,
  drawTiledImageWatermark,
  drawCenteredLogoWatermark,
};
