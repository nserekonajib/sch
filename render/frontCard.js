const QRCode = require('qrcode');
const { mm } = require('../units');
const {
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
} = require('./decorations');
const { dataUrlToBuffer, formatDate } = require('../utils');

/**
 * Renders the single face of the card (this IS the whole card — no back
 * side). Layer order matters a lot here:
 *   1. Base fill
 *   2. Full-card security patterns (waves x2, lattice, dot noise,
 *      tiled logo watermark, pantograph text watermark, rosette, OVI strip)
 *   3. Photo — drawn semi-transparently ON TOP of those patterns, then a
 *      second, tighter pattern pass drawn again OVER the photo, so the
 *      photo visually reads as sitting "under" a laminated security layer
 *      rather than pasted on top of a plain box.
 *   4. Opaque header / fields / QR / footer text on top of everything,
 *      so the card stays fully legible despite all the texture beneath it.
 */
async function renderFrontCard(doc, { originX, originY, cardW, cardH }, data) {
  const { branding, student, qrData, options = {} } = data;
  const primary = branding.primaryColor || '#1a5fa8';
  const secondary = branding.secondaryColor || '#e8b400';

  const X = originX;
  const Y = originY;

  const cardSeed = `${student.studentId || ''}|${student.serial || ''}|${branding.organizationName || ''}`;
  const seededRandom = makeSeededRandom(cardSeed);
  const logoBuf = branding.logoBase64 ? dataUrlToBuffer(branding.logoBase64) : null;

  // ---------------------------------------------------------------
  // 1. base fill
  // ---------------------------------------------------------------
  doc.save();
  doc.rect(X, Y, cardW, cardH).fill('#f7fbff');
  doc.restore();

  // ---------------------------------------------------------------
  // 2. full-card security pattern stack
  // ---------------------------------------------------------------
  drawWaveBackground(doc, {
    x: X, y: Y, w: cardW, h: cardH,
    colorA: primary, colorB: secondary,
    lineCount: 30, opacity: 0.13,
  });

  drawWaveBackground(doc, {
    x: X, y: Y, w: cardW, h: cardH,
    colorA: secondary, colorB: primary,
    lineCount: 21 + Math.floor(seededRandom() * 6), opacity: 0.07,
  });

  drawLatticePattern(doc, {
    x: X, y: Y, w: cardW, h: cardH,
    color: primary, opacity: 0.07, spacing: mm(1.1), angle: 32,
  });

  drawSecurityDots(doc, {
    x: X, y: Y, w: cardW, h: cardH,
    color: primary, opacity: 0.10, count: 1400, seedRandom: seededRandom,
  });

  if (logoBuf) {
    drawTiledImageWatermark(doc, {
      x: X, y: Y, w: cardW, h: cardH,
      imageBuffer: logoBuf, opacity: 0.05, tileSize: mm(6), gap: mm(4.5), angle: 18,
    });
  }

  drawPantographWatermark(doc, {
    x: X, y: Y, w: cardW, h: cardH,
    text: branding.organizationName || 'ORIGINAL',
    color: primary, opacity: 0.045,
    angle: -28 + (seededRandom() * 10 - 5),
  });

  drawGuillocheRosette(doc, {
    cx: X + cardW - mm(9), cy: Y + cardH - mm(9),
    radius: mm(8.5), color: primary, opacity: 0.15, petals: 6, seedRandom: seededRandom,
  });

  drawOviStrip(doc, { x: X, y: Y + cardH - mm(2.6), w: cardW, h: mm(1.3) });

  const microLabel = `${(branding.organizationName || 'STUDENT ID').toUpperCase()} • AUTHENTIC •`;
  drawMicrotextBand(doc, { x: X + mm(1), y: Y + mm(0.6), w: cardW - mm(2), text: microLabel, color: primary, opacity: 0.4 });
  drawMicrotextBand(doc, { x: X + mm(1), y: Y + cardH - mm(1.8), w: cardW - mm(2), text: microLabel, color: primary, opacity: 0.4 });

  // large faint centered logo watermark, behind the photo/fields but on top of the fine patterns
  if (logoBuf) {
    drawCenteredLogoWatermark(doc, {
      x: X + mm(24), y: Y + mm(3), w: cardW - mm(28), h: cardH - mm(6),
      imageBuffer: logoBuf, opacity: 0.07, sizeRatio: 0.85, angle: -8,
    });
  }

  // left color spine
  doc.save();
  doc.rect(X, Y, mm(2.2), cardH).fill(primary);
  doc.restore();

  // ---------------------------------------------------------------
  // header (opaque, on top of the pattern stack)
  // ---------------------------------------------------------------
  const headerX = X + mm(4);
  const headerTopY = Y + mm(3);
  const headerW = cardW - mm(24) - mm(4);

  if (logoBuf) {
    doc.image(logoBuf, headerX, headerTopY, { fit: [mm(9), mm(9)] });
  }

  const titleX = headerX + (logoBuf ? mm(11) : 0);
  doc.fillColor(primary).font('Helvetica-Bold').fontSize(6.6)
    .text((branding.organizationName || '').toUpperCase(), titleX, headerTopY, {
      width: headerW - (logoBuf ? mm(11) : 0), lineBreak: false,
    });
  doc.fillColor('#333333').font('Helvetica').fontSize(4.6)
    .text((branding.organizationSubtitle || 'Student ID Card').toUpperCase(), titleX, headerTopY + mm(3.4), {
      width: headerW - (logoBuf ? mm(11) : 0), lineBreak: false,
    });
  doc.fillColor(secondary).font('Helvetica-Bold').fontSize(7.6)
    .text('STUDENT IDENTITY CARD', headerX, headerTopY + mm(6.4), { width: headerW, lineBreak: false, align: 'center' });

  drawDoubleRule(doc, { x: headerX, y: headerTopY + mm(9.8), w: cardW - mm(8), color: primary, opacity: 0.6 });

  // ---------------------------------------------------------------
  // seal watermark top-right (behind the "seal" position on the header row)
  // ---------------------------------------------------------------
  const sealCx = X + cardW - mm(11);
  const sealCy = Y + mm(9);
  drawSunburstSeal(doc, { cx: sealCx, cy: sealCy, radius: mm(8), color: primary, opacity: 0.16 });
  if (branding.sealBase64) {
    const sealBuf = dataUrlToBuffer(branding.sealBase64);
    if (sealBuf) {
      doc.save();
      doc.opacity(0.9);
      doc.image(sealBuf, sealCx - mm(6.5), sealCy - mm(6.5), { width: mm(13), height: mm(13) });
      doc.restore();
    }
  }

  // ---------------------------------------------------------------
  // 3. photo box — drawn so it visually sits BEHIND a security layer
  // ---------------------------------------------------------------
  const photoX = X + mm(4);
  const photoY = headerTopY + mm(10.5);
  const photoW = mm(19);
  const photoH = mm(18.5);
  const photoCx = photoX + photoW / 2;
  const photoCy = photoY + photoH / 2;

  doc.save();
  doc.lineWidth(0.8).strokeColor(primary).rect(photoX, photoY, photoW, photoH).stroke();
  doc.restore();

  const photoBuf = dataUrlToBuffer(student.photoBase64);
  if (photoBuf) {
    doc.save();
    doc.rect(photoX, photoY, photoW, photoH).clip();

    // faint concentric halo behind the photo for extra "embedded" texture
    drawConcentricRings(doc, { cx: photoCx, cy: photoCy, rMax: Math.max(photoW, photoH) * 0.75, rings: 8, color: primary, opacity: 0.10 });

    // the photo itself, slightly less than fully opaque so the pattern
    // underneath still reads through it a little
    doc.save();
    doc.opacity(0.94);
    doc.image(photoBuf, photoX, photoY, { width: photoW, height: photoH });
    doc.restore();

    // a second, tighter security-pattern pass drawn ON TOP of the photo —
    // this is what makes the photo look laminated under the security layer
    // rather than just a picture sitting in a box
    drawWaveBackground(doc, {
      x: photoX, y: photoY, w: photoW, h: photoH,
      colorA: primary, colorB: secondary, lineCount: 8, opacity: 0.16,
    });
    drawLatticePattern(doc, {
      x: photoX, y: photoY, w: photoW, h: photoH,
      color: primary, opacity: 0.12, spacing: mm(1.6), angle: 30,
    });
    if (logoBuf) {
      drawTiledImageWatermark(doc, {
        x: photoX, y: photoY, w: photoW, h: photoH,
        imageBuffer: logoBuf, opacity: 0.10, tileSize: mm(5), gap: mm(3.5), angle: 18,
      });
    }

    doc.restore(); // release clip
  }

  // ---------------------------------------------------------------
  // QR code — stacked directly below the photo, in the same narrow
  // left column (kept off to the side so it never competes with the
  // fields column for vertical space). QR is on the FRONT of the card.
  // ---------------------------------------------------------------
  const qrSize = mm(13.5);
  const qrX = photoX + (photoW - qrSize) / 2;
  const qrY = photoY + photoH + mm(1.6);

  const qrPayload = typeof qrData === 'string' ? qrData : JSON.stringify(qrData);
  const qrPngBuffer = await QRCode.toBuffer(qrPayload, {
    type: 'png', margin: 0, width: 500,
    color: { dark: '#16202a', light: '#ffffff00' },
    errorCorrectionLevel: 'M',
  });

  doc.save();
  doc.rect(qrX - mm(0.8), qrY - mm(0.8), qrSize + mm(1.6), qrSize + mm(1.6)).fill('#ffffff');
  doc.lineWidth(0.6).strokeColor(primary).rect(qrX - mm(0.8), qrY - mm(0.8), qrSize + mm(1.6), qrSize + mm(1.6)).stroke();
  doc.restore();
  doc.image(qrPngBuffer, qrX, qrY, { width: qrSize, height: qrSize });

  // ---------------------------------------------------------------
  // fields (right of photo/QR column)
  // ---------------------------------------------------------------
  const fieldsX = photoX + photoW + mm(3.5);
  const fieldsW = X + cardW - mm(4) - fieldsX;
  let cy = photoY;

  function field(label, value, opts = {}) {
    const labelSize = opts.labelSize || 4.0;
    const valueSize = opts.valueSize || 6.6;
    doc.fillColor('#5b6b7a').font('Helvetica').fontSize(labelSize)
      .text(label.toUpperCase(), fieldsX, cy, { width: fieldsW, lineBreak: false });
    doc.fillColor(opts.color || '#16202a').font(opts.bold === false ? 'Helvetica' : 'Helvetica-Bold').fontSize(valueSize)
      .text(value || '-', fieldsX, cy + mm(1.9), { width: fieldsW, lineBreak: false });
    cy += opts.gap || mm(5.4);
  }

  field('Surname / Apellido', student.surname);
  field('Given Names / Nombre', student.firstName);

  const halfW = fieldsW / 2 - mm(1);
  doc.fillColor('#5b6b7a').font('Helvetica').fontSize(4.0)
    .text('SEX', fieldsX, cy, { width: mm(8), lineBreak: false })
    .text('NATIONALITY', fieldsX + mm(9), cy, { width: halfW, lineBreak: false });
  doc.fillColor('#16202a').font('Helvetica-Bold').fontSize(6.6)
    .text(student.sex || '-', fieldsX, cy + mm(1.9), { width: mm(8), lineBreak: false })
    .text(student.nationality || '-', fieldsX + mm(9), cy + mm(1.9), { width: halfW, lineBreak: false });
  cy += mm(5.4);

  field('Date of Birth', formatDate(student.dateOfBirth));

  doc.fillColor('#5b6b7a').font('Helvetica').fontSize(4.0)
    .text('STUDENT ID', fieldsX, cy, { width: fieldsW, lineBreak: false });
  doc.fillColor(primary).font('Helvetica-Bold').fontSize(8.6)
    .text(student.studentId, fieldsX, cy + mm(1.9), { width: fieldsW, lineBreak: false });
  cy += mm(6.2);

  doc.fillColor('#5b6b7a').font('Helvetica').fontSize(4.0)
    .text('ISSUE DATE', fieldsX, cy, { width: halfW, lineBreak: false })
    .text('EXPIRY DATE', fieldsX + halfW + mm(2), cy, { width: halfW, lineBreak: false });
  doc.fillColor('#16202a').font('Helvetica-Bold').fontSize(6.2)
    .text(formatDate(student.issueDate), fieldsX, cy + mm(1.9), { width: halfW, lineBreak: false })
    .text(formatDate(student.expiryDate), fieldsX + halfW + mm(2), cy + mm(1.9), { width: halfW, lineBreak: false });

  // ---------------------------------------------------------------
  // vertical serial along the right edge
  // ---------------------------------------------------------------
  if (student.serial) {
    doc.save();
    doc.fillColor('#8a97a3').fontSize(4.2).font('Helvetica');
    doc.rotate(-90, { origin: [X + cardW - mm(2.2), Y + cardH - mm(4)] });
    doc.text(student.serial, X + cardW - mm(2.2) - mm(40), Y + cardH - mm(4) - mm(2), {
      width: mm(45), lineBreak: false,
    });
    doc.restore();
  }

  // ---------------------------------------------------------------
  // footer legal text
  // ---------------------------------------------------------------
  doc.fillColor('#8a97a3').font('Helvetica').fontSize(3.2)
    .text(
      branding.legalFooter || 'This card is property of the issuing institution and is non-transferable.',
      X + mm(4), Y + cardH - mm(5.6),
      { width: cardW - mm(8), lineBreak: false }
    );

  // ---------------------------------------------------------------
  // optional decorative MRZ-style strip
  // ---------------------------------------------------------------
  if (options.includeMrz) {
    const clean = (s) => (s || '').toString().toUpperCase().replace(/[^A-Z0-9]/g, '<');
    const pad = (s, len) => (s + '<'.repeat(len)).slice(0, len);
    const mrzLines = [
      pad(`ID<<${clean(student.studentId)}`, 30),
      pad(`${clean(student.surname)}<<${clean(student.firstName)}`, 30),
    ];
    const mrzY = Y + cardH - mm(2.6);
    doc.save();
    doc.opacity(0.9);
    doc.fillColor('#16202a').font('Courier-Bold').fontSize(3.6);
    doc.text(mrzLines.join('  '), X + mm(4), mrzY, { width: cardW - mm(8), characterSpacing: 0.3, lineBreak: false });
    doc.restore();
  }
}

module.exports = { renderFrontCard };
