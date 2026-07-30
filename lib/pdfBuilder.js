const PDFDocument = require('pdfkit');
const { fetchAndResizeImage } = require('./imageHelper');

// ---------------------------------------------------------------------------
// Design tokens — tweak these to re-skin the whole report card consistently.
// ---------------------------------------------------------------------------
const COLORS = {
  ink: '#1c2333',          // primary text
  navy: '#16213e',         // deep navy for bands/borders
  gold: '#b8893f',         // premium accent
  rule: '#9aa3b2',         // table borders
  ruleLight: '#d8dce3',
  zebra: '#f4f6fa',        // alternating row tint
  headerBand: '#16213e',
  headerBandText: '#ffffff',
  subtle: '#5b6472',
  white: '#ffffff',
};

const PAGE = { width: 595.28, height: 841.89 }; // A4 portrait, points
const MARGIN = 36;
const CONTENT_WIDTH = PAGE.width - MARGIN * 2;

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/**
 * Builds a single PDF buffer containing one (or more, if content overflows)
 * report-card page per student.
 *
 * @param {{school:object, term:object, exams:string[], students:object[]}} data
 * @returns {Promise<Buffer>}
 */
async function buildReportCardsPdf({ school, term, exams, students }) {
  const doc = new PDFDocument({
    size: 'A4',
    margins: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN },
    bufferPages: true,
    info: {
      Title: `${school.name || 'School'} - Report Cards`,
      Author: school.name || 'Report Card System',
    },
  });

  const chunks = [];
  doc.on('data', (c) => chunks.push(c));
  const done = new Promise((resolve, reject) => {
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);
  });

  // Fetch + resize the school logo once; reused on every page.
  const logoBuffer = await fetchAndResizeImage(school.logoUrl, { width: 140, height: 140, fit: 'contain' });

  for (let i = 0; i < students.length; i++) {
    const student = students[i];
    if (i > 0) doc.addPage();

    // Per-student photo, fetched fresh (different URL per student).
    const photoBuffer = await fetchAndResizeImage(student.photoUrl, { width: 220, height: 260, fit: 'cover' });

    await renderReportCard(doc, { school, term, exams, student, logoBuffer, photoBuffer });
  }

  doc.end();
  return done;
}

// ---------------------------------------------------------------------------
// Page renderer for a single student (handles internal pagination if the
// subject table is too long to fit on one page).
// ---------------------------------------------------------------------------

async function renderReportCard(doc, ctx) {
  const { school, term, exams, student } = ctx;

  drawPageFrame(doc);
  let y = drawHeader(doc, ctx);
  y = drawInfoGrid(doc, ctx, y);
  y = drawTitle(doc, ctx, y);

  const subjects = Array.isArray(student.subjects) ? student.subjects : [];
  y = drawSubjectsTable(doc, ctx, y, subjects);

  // Reserve space for footer blocks; if not enough room, start a fresh page
  // (frame redrawn) and continue there so nothing gets visually cramped.
  const FOOTER_BLOCK_HEIGHT = 230;
  if (y + FOOTER_BLOCK_HEIGHT > PAGE.height - MARGIN - 20) {
    doc.addPage();
    drawPageFrame(doc);
    y = MARGIN + 20;
    doc.fontSize(9).fillColor(COLORS.subtle)
      .text(`${student.name || ''} — continued`, MARGIN, y, { width: CONTENT_WIDTH, align: 'right' });
    y += 18;
  }

  y = drawComments(doc, ctx, y);
  y = drawRequirements(doc, ctx, y);
  drawFooter(doc, ctx, y);
}

// ---------------------------------------------------------------------------
// Section: thin decorative outer frame (premium touch)
// ---------------------------------------------------------------------------
function drawPageFrame(doc) {
  doc.save();
  doc.lineWidth(1.4).strokeColor(COLORS.navy)
    .rect(14, 14, PAGE.width - 28, PAGE.height - 28).stroke();
  doc.lineWidth(0.6).strokeColor(COLORS.gold)
    .rect(18, 18, PAGE.width - 36, PAGE.height - 36).stroke();
  doc.restore();
}

// ---------------------------------------------------------------------------
// Section: header — logo, school identity block, student photo
// ---------------------------------------------------------------------------
function drawHeader(doc, ctx) {
  const { school, logoBuffer, photoBuffer } = ctx;
  let y = MARGIN + 6;

  const logoSize = 64;
  const photoW = 78;
  const photoH = 92;

  // Logo (top-left)
  if (logoBuffer) {
    try {
      doc.image(logoBuffer, MARGIN, y, { width: logoSize, height: logoSize });
    } catch (e) { /* ignore broken image buffers */ }
  } else {
    doc.save().lineWidth(0.8).strokeColor(COLORS.ruleLight)
      .rect(MARGIN, y, logoSize, logoSize).stroke();
    doc.fontSize(7).fillColor(COLORS.subtle)
      .text('LOGO', MARGIN, y + logoSize / 2 - 4, { width: logoSize, align: 'center' });
    doc.restore();
  }

  // Student photo (top-right)
  const photoX = PAGE.width - MARGIN - photoW;
  if (photoBuffer) {
    try {
      doc.image(photoBuffer, photoX, y, { width: photoW, height: photoH });
      doc.save().lineWidth(1).strokeColor(COLORS.navy)
        .rect(photoX, y, photoW, photoH).stroke().restore();
    } catch (e) { /* ignore */ }
  } else {
    doc.save().lineWidth(0.8).strokeColor(COLORS.ruleLight)
      .rect(photoX, y, photoW, photoH).stroke();
    doc.fontSize(7).fillColor(COLORS.subtle)
      .text('STUDENT\nPHOTO', photoX, y + photoH / 2 - 12, { width: photoW, align: 'center' });
    doc.restore();
  }

  // School identity block (center)
  const textX = MARGIN + logoSize + 10;
  const textW = CONTENT_WIDTH - logoSize * 2 - 20;

  let ty = y + 2;
  doc.fontSize(18).fillColor(COLORS.navy).font('Helvetica-Bold')
    .text((school.name || 'SCHOOL NAME').toUpperCase(), textX, ty, { width: textW, align: 'center' });
  ty = doc.y + 2;

  if (school.tagline) {
    doc.fontSize(11).fillColor(COLORS.ink).font('Helvetica-Bold')
      .text(school.tagline.toUpperCase(), textX, ty, { width: textW, align: 'center' });
    ty = doc.y + 1;
  }
  if (school.address) {
    doc.fontSize(9.5).fillColor(COLORS.subtle).font('Helvetica')
      .text(school.address, textX, ty, { width: textW, align: 'center' });
    ty = doc.y + 1;
  }
  if (school.phone) {
    doc.fontSize(9.5).fillColor(COLORS.subtle).font('Helvetica')
      .text(`Tel: ${school.phone}`, textX, ty, { width: textW, align: 'center' });
    ty = doc.y + 1;
  }

  const headerBottom = Math.max(y + logoSize, y + photoH, ty + 4);

  // Gold rule under header
  doc.save().moveTo(MARGIN, headerBottom + 6).lineTo(PAGE.width - MARGIN, headerBottom + 6)
    .lineWidth(1.4).strokeColor(COLORS.gold).stroke().restore();

  return headerBottom + 16;
}

// ---------------------------------------------------------------------------
// Section: 2-column student info grid (Name/ID, Class/Gender, Term/Position, Division/Aggregates)
// ---------------------------------------------------------------------------
function drawInfoGrid(doc, ctx, startY) {
  const { term, student } = ctx;
  const rows = [
    ['STUDENT NAME', student.name || '-', 'STUDENT ID', student.studentId || '-'],
    ['CLASS', student.class || '-', 'GENDER', student.gender || '-'],
    ['TERM/YEAR', term.termYear || '-', 'POSITION', formatPosition(student)],
    ['DIVISION', student.division || '-', 'AGGREGATES', student.aggregates || '-'],
  ];

  const colW = CONTENT_WIDTH / 4; // label, value, label, value
  const rowH = 20;
  let y = startY;

  doc.lineWidth(0.8).strokeColor(COLORS.rule);
  rows.forEach((row) => {
    let x = MARGIN;
    row.forEach((cell, idx) => {
      const isLabel = idx % 2 === 0;
      doc.rect(x, y, colW, rowH).stroke();
      doc.fontSize(8.5)
        .font(isLabel ? 'Helvetica-Bold' : 'Helvetica')
        .fillColor(isLabel ? COLORS.navy : COLORS.ink)
        .text(String(cell || '-').toUpperCase(), x + 5, y + 6, { width: colW - 10, ellipsis: true });
      x += colW;
    });
    y += rowH;
  });

  return y + 18;
}

function formatPosition(student) {
  if (student.position == null) return '-';
  const outOf = student.outOf != null ? ` / ${student.outOf}` : '';
  return `${ordinal(student.position)}${outOf}`;
}

function ordinal(n) {
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  const s = ['th', 'st', 'nd', 'rd'];
  const v = num % 100;
  return num + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ---------------------------------------------------------------------------
// Section: title banner
// ---------------------------------------------------------------------------
function drawTitle(doc, ctx, startY) {
  const { term } = ctx;
  const title = term.reportTitle || 'STUDENT PROGRESSIVE REPORT CARD';
  const bandH = 22;

  doc.save();
  doc.rect(MARGIN, startY, CONTENT_WIDTH, bandH).fill(COLORS.headerBand);
  doc.fontSize(11).font('Helvetica-Bold').fillColor(COLORS.headerBandText)
    .text(title.toUpperCase(), MARGIN, startY + 6, { width: CONTENT_WIDTH, align: 'center', characterSpacing: 0.6 });
  doc.restore();

  return startY + bandH + 14;
}

// ---------------------------------------------------------------------------
// Section: subjects table — dynamic columns based on number of exams
// ---------------------------------------------------------------------------
function drawSubjectsTable(doc, ctx, startY, subjects) {
  const { exams, student } = ctx;

  // Column layout: SUBJECT | exam1 | exam2 | ... | [AVG(%)] | GRADE | REMARKS
  // AVG(%) is only meaningful (and only shown) when there's more than one
  // exam — with a single exam, the average just duplicates that one score.
  const showAvg = exams.length > 1;

  const subjectColW = 120;
  const remarksColW = 150;
  const gradeColW = 60;
  const avgColW = showAvg ? 50 : 0;
  const fixedW = subjectColW + remarksColW + gradeColW + avgColW;
  const examColW = (CONTENT_WIDTH - fixedW) / Math.max(exams.length, 1);

  const headers = ['SUBJECT', ...exams, ...(showAvg ? ['AVG(%)'] : []), 'GRADE', 'REMARKS'];
  const colWidths = [subjectColW, ...exams.map(() => examColW), ...(showAvg ? [avgColW] : []), gradeColW, remarksColW];

  let y = startY;
  const HEADER_H = 20;

  // Estimate row height needed (fits ~30 subjects/page comfortably);
  // shrink slightly if there are many subjects so everything fits on one page.
  const available = PAGE.height - MARGIN - 230 - y; // reserve footer blocks
  const rowsNeeded = subjects.length + 1; // +1 totals row
  let rowH = 19;
  if (rowsNeeded > 0) {
    const fitRowH = Math.floor((available - HEADER_H) / rowsNeeded);
    rowH = Math.max(14, Math.min(19, fitRowH));
  }

  const drawHeaderRow = (yy) => {
    doc.save();
    doc.rect(MARGIN, yy, CONTENT_WIDTH, HEADER_H).fill(COLORS.navy);
    let x = MARGIN;
    doc.font('Helvetica-Bold').fontSize(8.5).fillColor(COLORS.white);
    headers.forEach((h, i) => {
      doc.text(h.toUpperCase(), x + 4, yy + 6, { width: colWidths[i] - 8, align: i === 0 || i === headers.length - 1 ? 'left' : 'center' });
      x += colWidths[i];
    });
    doc.restore();
    // vertical separators on header
    x = MARGIN;
    doc.save().lineWidth(0.6).strokeColor('#2b3a63');
    headers.forEach((h, i) => {
      doc.moveTo(x, yy).lineTo(x, yy + HEADER_H).stroke();
      x += colWidths[i];
    });
    doc.moveTo(x, yy).lineTo(x, yy + HEADER_H).stroke();
    doc.restore();
    return yy + HEADER_H;
  };

  y = drawHeaderRow(y);

  doc.font('Helvetica').fontSize(8.5);
  subjects.forEach((subj, idx) => {
    // pagination guard: if a row would overflow the page, start a new page
    if (y + rowH > PAGE.height - MARGIN - 40) {
      doc.addPage();
      drawPageFrame(doc);
      y = MARGIN + 20;
      y = drawHeaderRow(y);
    }

    if (idx % 2 === 1) {
      doc.save().rect(MARGIN, y, CONTENT_WIDTH, rowH).fill(COLORS.zebra).restore();
    }

    let x = MARGIN;
    const rowValues = [
      subj.name || '-',
      ...(ctx.exams.map((examKey) => {
        const v = subj.scores ? subj.scores[examKey] : undefined;
        return v != null ? String(v) : '-';
      })),
      ...(showAvg ? [subj.avg != null ? Number(subj.avg).toFixed(1) : '-'] : []),
      subj.grade || '-',
      subj.remarks || '-',
    ];

    rowValues.forEach((val, i) => {
      const isSubject = i === 0;
      doc.fillColor(COLORS.ink).font(isSubject ? 'Helvetica-Bold' : 'Helvetica')
        .text(String(val).toUpperCase(), x + 4, y + (rowH - 9) / 2, {
          width: colWidths[i] - 8,
          align: isSubject || i === rowValues.length - 1 ? 'left' : 'center',
          ellipsis: true,
        });
      x += colWidths[i];
    });

    // row border
    doc.save().lineWidth(0.5).strokeColor(COLORS.rule)
      .rect(MARGIN, y, CONTENT_WIDTH, rowH).stroke();
    x = MARGIN;
    colWidths.forEach((w) => {
      doc.moveTo(x, y).lineTo(x, y + rowH).stroke();
      x += w;
    });
    doc.moveTo(x, y).lineTo(x, y + rowH).stroke();
    doc.restore();

    y += rowH;
  });

  // TOTALS row
  if (y + rowH > PAGE.height - MARGIN - 40) {
    doc.addPage();
    drawPageFrame(doc);
    y = MARGIN + 20;
    y = drawHeaderRow(y);
  }
  const totals = student.totals || {};
  doc.save().rect(MARGIN, y, CONTENT_WIDTH, rowH).fill('#e9edf5').restore();
  let x = MARGIN;
  const totalsValues = [
    'TOTALS',
    ...(ctx.exams.map((examKey) => (totals[examKey] != null ? String(totals[examKey]) : '-'))),
    ...(showAvg ? [totals.avg != null ? Number(totals.avg).toFixed(1) : '-'] : []),
    totals.grade || '-',
    '',
  ];
  totalsValues.forEach((val, i) => {
    doc.font('Helvetica-Bold').fontSize(8.5).fillColor(COLORS.navy)
      .text(String(val).toUpperCase(), x + 4, y + (rowH - 9) / 2, {
        width: colWidths[i] - 8,
        align: i === 0 || i === totalsValues.length - 1 ? 'left' : 'center',
      });
    x += colWidths[i];
  });
  doc.save().lineWidth(0.8).strokeColor(COLORS.navy).rect(MARGIN, y, CONTENT_WIDTH, rowH).stroke();
  x = MARGIN;
  colWidths.forEach((w) => {
    doc.moveTo(x, y).lineTo(x, y + rowH).stroke();
    x += w;
  });
  doc.moveTo(x, y).lineTo(x, y + rowH).stroke();
  doc.restore();
  y += rowH;

  // outer table border (crisp finishing line)
  doc.save().lineWidth(1).strokeColor(COLORS.navy)
    .rect(MARGIN, startY, CONTENT_WIDTH, y - startY).stroke().restore();

  return y + 16;
}

// ---------------------------------------------------------------------------
// Section: comments (class teacher / head teacher)
// ---------------------------------------------------------------------------
function drawComments(doc, ctx, startY) {
  const { student } = ctx;
  const boxH = 50;
  const labelW = 150;
  let y = startY;

  const block = (label, text) => {
    doc.save().lineWidth(0.8).strokeColor(COLORS.rule).rect(MARGIN, y, CONTENT_WIDTH, boxH).stroke();
    doc.moveTo(MARGIN + labelW, y).lineTo(MARGIN + labelW, y + boxH).stroke();
    doc.restore();
    doc.font('Helvetica-Bold').fontSize(8.5).fillColor(COLORS.navy)
      .text(label.toUpperCase(), MARGIN + 6, y + 7, { width: labelW - 12 });
    doc.font('Helvetica-Oblique').fontSize(9).fillColor(COLORS.ink)
      .text(text || '-', MARGIN + labelW + 8, y + 7, { width: CONTENT_WIDTH - labelW - 16, height: boxH - 14, ellipsis: true });
    y += boxH;
  };

  block('Class Teacher\'s Comment', student.classTeacherComment);
  block('Head Teacher\'s Comment', student.headTeacherComment);

  return y + 16;
}

// ---------------------------------------------------------------------------
// Section: requirements box
// ---------------------------------------------------------------------------
function drawRequirements(doc, ctx, startY) {
  const { student } = ctx;
  const boxH = 64;
  let y = startY;

  doc.font('Helvetica-Bold').fontSize(9.5).fillColor(COLORS.navy)
    .text('REQUIREMENTS', MARGIN, y);
  y += 14;

  doc.save().lineWidth(0.8).strokeColor(COLORS.rule).rect(MARGIN, y, CONTENT_WIDTH, boxH).stroke().restore();
  doc.font('Helvetica').fontSize(9).fillColor(COLORS.ink)
    .text(student.requirements || '-', MARGIN + 8, y + 8, { width: CONTENT_WIDTH - 16, height: boxH - 16 });

  return y + boxH + 16;
}

// ---------------------------------------------------------------------------
// Section: footer (next term + motto + signature lines)
// ---------------------------------------------------------------------------
function drawFooter(doc, ctx, startY) {
  const { school, term } = ctx;
  let y = startY;

  doc.font('Helvetica').fontSize(9).fillColor(COLORS.ink)
    .text(`Next term begins: ${term.nextTermBegins || '________________________'}`, MARGIN, y);

  // signature lines
  const sigW = 160;
  const sigY = y + 28;
  doc.save().lineWidth(0.7).strokeColor(COLORS.rule);
  doc.moveTo(MARGIN, sigY).lineTo(MARGIN + sigW, sigY).stroke();
  doc.moveTo(PAGE.width - MARGIN - sigW, sigY).lineTo(PAGE.width - MARGIN, sigY).stroke();
  doc.restore();
  doc.fontSize(8).fillColor(COLORS.subtle)
    .text('Class Teacher\'s Signature', MARGIN, sigY + 3, { width: sigW, align: 'center' });
  doc.text('Head Teacher\'s Signature', PAGE.width - MARGIN - sigW, sigY + 3, { width: sigW, align: 'center' });

  if (school.motto) {
    doc.font('Helvetica-Oblique').fontSize(9).fillColor(COLORS.gold)
      .text(`"${school.motto}"`, MARGIN, PAGE.height - MARGIN - 30, { width: CONTENT_WIDTH, align: 'center' });
  }

  return PAGE.height - MARGIN;
}

module.exports = {
  buildReportCardsPdf,
  // Shared primitives + design tokens, re-used by competencyPdfBuilder.js
  // so both report styles share one visual system.
  COLORS,
  PAGE,
  MARGIN,
  CONTENT_WIDTH,
  drawPageFrame,
  drawHeader,
  drawInfoGrid,
  drawTitle,
};