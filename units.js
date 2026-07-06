// 1 mm = 2.834645669 PDF points (72 pt / 25.4 mm)
const PT_PER_MM = 72 / 25.4;

function mm(v) {
  return v * PT_PER_MM;
}

// Standard CR80 card size (the size of a credit/ID card): 85.6 x 54 mm
const CARD_W_MM = 85.6;
const CARD_H_MM = 54;

module.exports = {
  mm,
  PT_PER_MM,
  CARD_W_MM,
  CARD_H_MM,
};
