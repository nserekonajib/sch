const PDFDocument = require('pdfkit');
const { mm, CARD_W_MM, CARD_H_MM } = require('./units');
const { renderFrontCard } = require('./render/frontCard');

/**
 * Generates a print-ready, single-page PDF for one student ID card
 * (front face only — this is the whole card) and returns it as a Buffer.
 *
 * @param {object} data - validated request body: { branding, student, qrData, options }
 * @returns {Promise<Buffer>}
 */
async function generateCardPdf(data) {
  return generateBatchPdf([data]);
}

/**
 * Generates a single PDF containing one page per entry in `dataList`
 * (each page is one complete card). Every entry may have its own bleed
 * setting; each page is sized individually.
 *
 * @param {object[]} dataList - array of validated card payloads
 * @returns {Promise<Buffer>}
 */
async function generateBatchPdf(dataList) {
  if (!Array.isArray(dataList) || dataList.length === 0) {
    throw new Error('generateBatchPdf requires a non-empty array of card payloads');
  }

  const doc = new PDFDocument({
    autoFirstPage: false,
    info: {
      Title:
        dataList.length === 1
          ? `Student ID Card - ${dataList[0].student.studentId}`
          : `Student ID Cards (${dataList.length})`,
      Subject: 'Student Identity Card',
      Creator: 'student-id-card-api',
    },
  });

  const chunks = [];
  doc.on('data', (c) => chunks.push(c));
  const done = new Promise((resolve, reject) => {
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);
  });

  for (const data of dataList) {
    const options = data.options || {};
    const bleedMm = typeof options.bleedMm === 'number' ? options.bleedMm : 0;

    const cardW = mm(CARD_W_MM);
    const cardH = mm(CARD_H_MM);
    const bleed = mm(bleedMm);

    const pageW = cardW + bleed * 2;
    const pageH = cardH + bleed * 2;
    const frame = { originX: bleed, originY: bleed, cardW, cardH };

    doc.addPage({ size: [pageW, pageH], margin: 0 });
    if (bleed > 0) {
      doc.save();
      doc.rect(0, 0, pageW, pageH).fill('#f7fbff');
      doc.restore();
    }
    await renderFrontCard(doc, frame, data);
    if (bleed > 0) drawTrimMarks(doc, { pageW, pageH, bleed, cardW, cardH });
  }

  doc.end();
  return done;
}

/** Thin corner trim marks just outside the card's trim box, standard for print shops. */
function drawTrimMarks(doc, { pageW, pageH, bleed, cardW, cardH }) {
  const len = mm(3);
  const gap = mm(1);
  doc.save();
  doc.lineWidth(0.5).strokeColor('#999999');

  const corners = [
    [bleed, bleed, -1, -1],
    [bleed + cardW, bleed, 1, -1],
    [bleed, bleed + cardH, -1, 1],
    [bleed + cardW, bleed + cardH, 1, 1],
  ];

  corners.forEach(([cx, cy, dx, dy]) => {
    doc.moveTo(cx + dx * gap, cy).lineTo(cx + dx * (gap + len), cy).stroke();
    doc.moveTo(cx, cy + dy * gap).lineTo(cx, cy + dy * (gap + len)).stroke();
  });

  doc.restore();
}

module.exports = { generateCardPdf, generateBatchPdf };
