// whatsapp-academic-server.js - QR CODE VERSION (Working)

const { default: makeWASocket, DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const qrcode = require('qrcode');
const express = require('express');
const cors = require('cors');
const http = require('http');
const socketIO = require('socket.io');
const { createClient } = require('@supabase/supabase-js');
const P = require('pino');
const fs = require('fs');
const path = require('path');
const { buildReportCardsPdf } = require('./lib/pdfBuilder');
const { buildCompetencyReportCardsPdf } = require('./lib/competencyPdfBuilder');
require('dotenv').config();

// ==================== ID CARD IMPORTS ====================
let validateRequest, validateBatchRequest, ValidationError, generateCardPdf, generateBatchPdf;
let idCardModulesAvailable = false;

try {
  const validateModule = require('./validate');
  validateRequest = validateModule.validateRequest;
  validateBatchRequest = validateModule.validateBatchRequest;
  ValidationError = validateModule.ValidationError;
  console.log('✅ ID Card validation module loaded');
} catch (error) {
  console.warn('⚠️ ID Card validation module not found:', error.message);
  validateRequest = () => {};
  validateBatchRequest = (body) => body.cards || [];
  ValidationError = class ValidationError extends Error {};
}

try {
  const cardGenerator = require('./cardGenerator');
  generateCardPdf = cardGenerator.generateCardPdf;
  generateBatchPdf = cardGenerator.generateBatchPdf;
  idCardModulesAvailable = true;
  console.log('✅ ID Card generator module loaded');
} catch (error) {
  console.warn('⚠️ ID Card generator module not found:', error.message);
  generateCardPdf = async () => Buffer.from('PDF generation not available');
  generateBatchPdf = async () => Buffer.from('PDF generation not available');
  idCardModulesAvailable = false;
}

// ==================== CONFIGURATION ====================
const app = express();
const server = http.createServer(app);
const io = socketIO(server, {
  cors: { origin: "*", methods: ["GET", "POST"] },
  pingTimeout: 60000,
  pingInterval: 25000,
  transports: ['websocket', 'polling']
});

app.use(cors());
app.use(express.json({ limit: '200mb' }));
app.use(express.urlencoded({ extended: true, limit: '200mb' }));

// ==================== SUPABASE SETUP ====================
let supabase = null;
let supabase2 = null;

try {
    const SUPABASE_URL =
        process.env.SUPABASE_URL ||
        "https://qddnezmtskwclzzzfbun.supabase.co/";

    const SUPABASE_KEY =
        process.env.SUPABASE_KEY ||
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFkZG5lem10c2t3Y2x6enpmYnVuIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTc1ODU4MywiZXhwIjoyMTAxMzM0NTgzfQ.I3wJRLCB-bL0UStwPYjePfbEIV7LveodBJvzZFaDcYQ";

    supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

    console.log("✅ Supabase connected");
} catch (error) {
    console.error("⚠️ Failed to initialize Supabase:", error.message);
}

try {
  if (process.env.SUPABASE_URL2 && process.env.SUPABASE_KEY2) {
    supabase2 = createClient(process.env.SUPABASE_URL2, process.env.SUPABASE_KEY2);
    console.log('✅ Supabase Secondary connected');
  }
} catch (error) {
  console.log('⚠️ Supabase Secondary not configured');
}

function getSupabaseClient() {
  if (supabase) return supabase;
  if (supabase2) return supabase2;
  return null;
}

// ==================== AUTH FOLDER SETUP ====================
const GLOBAL_AUTH_FOLDER = path.join(__dirname, 'auth_info_global');
if (!fs.existsSync(GLOBAL_AUTH_FOLDER)) {
  fs.mkdirSync(GLOBAL_AUTH_FOLDER, { recursive: true });
}

// ==================== GLOBAL CLIENT ====================
let globalClient = {
  sock: null,
  isReady: false,
  reconnectAttempts: 0,
  isConnecting: false,
  masterConnected: false,
  masterInstituteId: null,
  connectionInProgress: false,
  qrCode: null,
  connectionStatus: 'disconnected'
};

// ==================== BATCH SYNC FUNCTIONS ====================

async function syncFromSupabase() {
  const supabaseClient = getSupabaseClient();
  if (!supabaseClient) return false;
  
  try {
    const { data, error } = await supabaseClient
      .from('whatsapp_auth_files_global')
      .select('filename, content');
    
    if (error) throw error;
    
    if (data && data.length > 0) {
      const writePromises = data.map(file => 
        fs.promises.writeFile(path.join(GLOBAL_AUTH_FOLDER, file.filename), file.content)
      );
      await Promise.all(writePromises);
      console.log(`✅ Global auth restored (${data.length} files)`);
      return true;
    }
    return false;
  } catch (error) {
    console.error(`Global sync error:`, error.message);
    return false;
  }
}

async function syncToSupabase() {
  const supabaseClient = getSupabaseClient();
  if (!supabaseClient) return;
  
  try {
    const files = fs.readdirSync(GLOBAL_AUTH_FOLDER);
    if (files.length === 0) return;
    
    await supabaseClient.from('whatsapp_auth_files_global').delete();
    
    const records = files.map(filename => {
      const filePath = path.join(GLOBAL_AUTH_FOLDER, filename);
      const content = fs.readFileSync(filePath, 'utf-8');
      return { filename, content, updated_at: new Date().toISOString() };
    });
    
    const { error } = await supabaseClient.from('whatsapp_auth_files_global').insert(records);
    if (error) throw error;
    console.log(`✅ Global auth synced to Supabase (${files.length} files)`);
  } catch (error) {
    console.error(`Global sync error:`, error.message);
  }
}

async function clearGlobalAuthData() {
  console.log(`🗑️ Clearing global auth data...`);
  
  if (globalClient.sock) {
    try {
      await globalClient.sock.logout();
      globalClient.sock.end();
    } catch(e) {}
  }
  
  globalClient = {
    sock: null,
    isReady: false,
    reconnectAttempts: 0,
    isConnecting: false,
    masterConnected: false,
    masterInstituteId: null,
    connectionInProgress: false,
    qrCode: null,
    connectionStatus: 'disconnected'
  };
  
  if (fs.existsSync(GLOBAL_AUTH_FOLDER)) {
    try {
      fs.rmSync(GLOBAL_AUTH_FOLDER, { recursive: true, force: true });
      fs.mkdirSync(GLOBAL_AUTH_FOLDER, { recursive: true });
    } catch(e) {
      console.error('Error clearing auth folder:', e.message);
    }
  }
  
  const supabaseClient = getSupabaseClient();
  if (supabaseClient) {
    try {
      await supabaseClient.from('whatsapp_auth_files_global').delete();
      console.log('✅ Global auth cleared from Supabase');
    } catch(e) {
      console.error('Error deleting global auth:', e.message);
    }
  }
}

// ==================== GLOBAL WHATSAPP CONNECTION WITH QR ====================
async function connectGlobalWhatsApp(forceQR = false) {
  if (globalClient.connectionInProgress) {
    console.log('⏳ Connection already in progress, skipping...');
    return;
  }
  
  console.log(`🔄 Connecting Global WhatsApp... (forceQR: ${forceQR})`);
  globalClient.connectionInProgress = true;
  globalClient.isConnecting = true;
  globalClient.connectionStatus = 'connecting';
  
  try {
    // Try to restore auth from Supabase
    await syncFromSupabase();
    
    const { state, saveCreds } = await useMultiFileAuthState(GLOBAL_AUTH_FOLDER);
    const { version } = await fetchLatestBaileysVersion();
    
    const sock = makeWASocket({
      version,
      auth: state,
      logger: P({ level: 'silent' }),
      browser: ['Lunserk ERP WhatsApp Global', 'Chrome', '1.0.0'],
      connectTimeoutMs: 60000,
      defaultQueryTimeoutMs: 60000,
      keepAliveIntervalMs: 10000,
      printQRInTerminal: false
    });
    
    globalClient.sock = sock;
    globalClient.qrCode = null;
    
    // Handle connection updates
    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;
      
      // Handle QR code
      if (qr) {
        globalClient.qrCode = qr;
        console.log(`📱 QR Code generated`);
        
        try {
          const qrImage = await qrcode.toDataURL(qr, { scale: 8 });
          io.emit('global_qr', qrImage);
          console.log(`✅ QR sent to all connected clients`);
        } catch(err) {
          console.error('QR generation error:', err);
          io.emit('global_qr', qr);
        }
        
        globalClient.connectionInProgress = false;
        globalClient.connectionStatus = 'scanning';
      }
      
      // Connection open
      if (connection === 'open') {
        console.log(`✅ Global WhatsApp connected!`);
        globalClient.isReady = true;
        globalClient.isConnecting = false;
        globalClient.connectionInProgress = false;
        globalClient.reconnectAttempts = 0;
        globalClient.qrCode = null;
        globalClient.masterConnected = true;
        globalClient.connectionStatus = 'connected';
        io.emit('global_ready', 'WhatsApp is ready for all institutes!');
        console.log('✅ WhatsApp fully connected and ready!');
      }
      
      // Connection closed
      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
        console.log(`❌ Global connection closed (code: ${statusCode})`);
        globalClient.isReady = false;
        globalClient.isConnecting = false;
        globalClient.connectionInProgress = false;
        globalClient.connectionStatus = 'disconnected';
        
        if (statusCode === 401 || statusCode === 403) {
          console.log('🔑 Authentication failed - clearing invalid auth...');
          await clearGlobalAuthData();
          io.emit('pairing_error', 'Authentication failed. Please try again.');
        } else if (shouldReconnect && globalClient.reconnectAttempts < 10) {
          globalClient.reconnectAttempts++;
          const delay = Math.min(3000 * globalClient.reconnectAttempts, 30000);
          console.log(`🔄 Reconnecting in ${delay/1000}s... (Attempt ${globalClient.reconnectAttempts})`);
          setTimeout(() => {
            globalClient.connectionInProgress = false;
            connectGlobalWhatsApp(false);
          }, delay);
        } else if (statusCode === DisconnectReason.loggedOut) {
          console.log(`🔴 Logged out, clearing auth...`);
          globalClient.isReady = false;
          globalClient.masterConnected = false;
          io.emit('global_disconnected', 'Logged out');
          await clearGlobalAuthData();
        }
      }
    });
    
    sock.ev.on('creds.update', async () => {
      await saveCreds();
      await syncToSupabase();
    });
    
    sock.ev.on('error', (err) => {
      console.error(`Global socket error:`, err.message);
      globalClient.connectionInProgress = false;
    });
    
    // If forceQR is true, we need to trigger QR generation
    if (forceQR) {
      console.log('📱 Force QR mode - waiting for QR to be generated...');
      // QR will be handled in the connection.update event above
    }
    
  } catch (error) {
    console.error(`❌ Global connection error:`, error.message);
    globalClient.isConnecting = false;
    globalClient.connectionInProgress = false;
    globalClient.connectionStatus = 'disconnected';
    setTimeout(() => {
      globalClient.connectionInProgress = false;
      connectGlobalWhatsApp(forceQR);
    }, 10000);
  }
}

// ==================== WHATSAPP API ROUTES ====================

app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    globalReady: globalClient.isReady,
    masterConnected: globalClient.masterConnected,
    connectionStatus: globalClient.connectionStatus,
    supabase: !!getSupabaseClient(),
    idCardModules: idCardModulesAvailable
  });
});

app.get('/api/status/:instituteId', async (req, res) => {
  res.json({
    ready: globalClient.isReady,
    master_connected: globalClient.masterConnected,
    isConnecting: globalClient.isConnecting || false,
    connectionInProgress: globalClient.connectionInProgress || false,
    connectionStatus: globalClient.connectionStatus || 'disconnected',
    qrCode: globalClient.qrCode || null,
    message: globalClient.isReady ? 'WhatsApp is connected and ready' : 
             globalClient.qrCode ? 'QR code available - scan with WhatsApp' :
             globalClient.isConnecting ? 'Connecting to WhatsApp...' :
             'WhatsApp is not connected'
  });
});

app.post('/api/request-qr/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  console.log(`📱 QR requested for institute: ${instituteId}`);
  
  if (globalClient.isReady) {
    return res.json({ success: true, message: 'WhatsApp is already connected!' });
  }
  
  if (globalClient.connectionInProgress || globalClient.isConnecting) {
    return res.json({ success: true, message: 'Connection already in progress...' });
  }
  
  // Clear old auth and start fresh with QR
  await clearGlobalAuthData();
  
  // Start connection with forceQR
  setTimeout(() => connectGlobalWhatsApp(true), 1000);
  
  res.json({ 
    success: true, 
    message: 'QR code requested. Please scan with WhatsApp mobile app.' 
  });
});

app.post('/api/mark-master-connected', async (req, res) => {
  const { instituteId } = req.body;
  if (!instituteId) {
    return res.status(400).json({ success: false, message: 'Institute ID required' });
  }
  globalClient.masterConnected = true;
  globalClient.masterInstituteId = instituteId;
  res.json({ success: true, message: 'WhatsApp connection marked as permanent' });
});

app.post('/api/logout/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  console.log(`📱 Logout requested for institute: ${instituteId}`);
  await clearGlobalAuthData();
  io.emit('global_disconnected', 'WhatsApp disconnected globally');
  res.json({ success: true, message: 'Logged out successfully' });
});

// ==================== SEND MESSAGES ====================

app.post('/api/send', async (req, res) => {
  const { number, message, instituteId } = req.body;
  
  if (!globalClient.isReady || !globalClient.sock) {
    return res.status(400).json({ error: 'WhatsApp is not ready. Please try again later.' });
  }
  
  try {
    const formattedNumber = number.includes('@') ? number : `${number}@s.whatsapp.net`;
    await globalClient.sock.sendMessage(formattedNumber, { text: message });
    res.json({ success: true, message: 'Message sent successfully' });
  } catch (error) {
    console.error(`Send error:`, error.message);
    res.status(500).json({ error: error.message || 'Failed to send message' });
  }
});

app.post('/api/send-pdf', async (req, res) => {
  const { number, pdfBuffer, filename, instituteId } = req.body;
  
  if (!globalClient.isReady || !globalClient.sock) {
    return res.status(400).json({ error: 'WhatsApp is not ready. Please try again later.' });
  }
  
  try {
    const formattedNumber = number.includes('@') ? number : `${number}@s.whatsapp.net`;
    const buffer = Buffer.from(pdfBuffer, 'base64');
    
    await globalClient.sock.sendMessage(formattedNumber, {
      document: buffer,
      mimetype: 'application/pdf',
      fileName: filename || 'document.pdf'
    });
    
    res.json({ success: true, message: 'PDF sent successfully' });
  } catch (error) {
    console.error(`Send PDF error:`, error.message);
    res.status(500).json({ error: error.message || 'Failed to send PDF' });
  }
});

// ==================== REPORT CARD ROUTES ====================

function detectReportType(body) {
  if (body.assessments && Array.isArray(body.assessments) && body.assessments.length > 0) {
    return 'competency';
  }
  return 'standard';
}

async function handleGenerateStandard(req, res, students) {
  try {
    const { school, term, exams } = req.body;

    if (!school || !school.name) {
      return res.status(400).json({ error: 'Missing required field: school.name' });
    }
    if (!Array.isArray(students) || students.length === 0) {
      return res.status(400).json({ error: 'No student data provided' });
    }

    const pdfBuffer = await buildReportCardsPdf({
      school,
      term: term || {},
      exams: Array.isArray(exams) && exams.length ? exams : ['EXAM'],
      students,
    });

    res.set({
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="report-cards-${Date.now()}.pdf"`,
      'Content-Length': pdfBuffer.length,
    });
    res.status(200).send(pdfBuffer);
  } catch (err) {
    console.error('Failed to generate standard report card PDF:', err);
    res.status(500).json({ error: 'Failed to generate report card PDF', detail: err.message });
  }
}

async function handleGenerateCompetency(req, res, students) {
  try {
    const { school, term, assessments, weightedColumns, gradeScale, keyTerms, resultDefinitions } = req.body;

    if (!school || !school.name) {
      return res.status(400).json({ error: 'Missing required field: school.name' });
    }
    if (!Array.isArray(students) || students.length === 0) {
      return res.status(400).json({ error: 'No student data provided' });
    }
    if (!Array.isArray(assessments) || assessments.length === 0) {
      return res.status(400).json({ error: 'Missing required field: assessments' });
    }

    const pdfBuffer = await buildCompetencyReportCardsPdf({
      school,
      term: term || {},
      assessments,
      weightedColumns: weightedColumns || [],
      gradeScale: gradeScale || [],
      keyTerms: keyTerms || [],
      resultDefinitions: resultDefinitions || [],
      students,
    });

    res.set({
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="competency-report-cards-${Date.now()}.pdf"`,
      'Content-Length': pdfBuffer.length,
    });
    res.status(200).send(pdfBuffer);
  } catch (err) {
    console.error('Failed to generate competency report card PDF:', err);
    res.status(500).json({ error: 'Failed to generate competency report card PDF', detail: err.message });
  }
}

app.post('/generate-report-cards', (req, res) => {
  handleGenerateStandard(req, res, req.body.students);
});

app.post('/generate-report-card', (req, res) => {
  const student = req.body.student;
  handleGenerateStandard(req, res, student ? [student] : []);
});

app.post('/generate-competency-report-cards', (req, res) => {
  handleGenerateCompetency(req, res, req.body.students);
});

app.post('/generate-competency-report-card', (req, res) => {
  const student = req.body.student;
  handleGenerateCompetency(req, res, student ? [student] : []);
});

app.post('/generate', (req, res) => {
  const reportType = detectReportType(req.body);
  if (reportType === 'competency') {
    handleGenerateCompetency(req, res, req.body.students || []);
  } else {
    handleGenerateStandard(req, res, req.body.students || []);
  }
});

app.post('/generate-single', (req, res) => {
  const reportType = detectReportType(req.body);
  const student = req.body.student;
  if (!student) {
    return res.status(400).json({ error: 'Missing required field: student' });
  }
  if (reportType === 'competency') {
    handleGenerateCompetency(req, res, [student]);
  } else {
    handleGenerateStandard(req, res, [student]);
  }
});

// ==================== ID CARD ROUTES ====================

app.post('/api/id-cards', async (req, res) => {
  try {
    if (!idCardModulesAvailable) {
      return res.status(503).json({ error: 'ID Card generation module not available' });
    }

    validateRequest(req.body);
    const pdfBuffer = await generateCardPdf(req.body);

    const studentId = req.body.student?.studentId || 'card';
    const filename = `student-id-${String(studentId).replace(/[^a-zA-Z0-9_-]/g, '')}.pdf`;

    res.status(200);
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', `inline; filename="${filename}"`);
    res.setHeader('Content-Length', pdfBuffer.length);
    res.end(pdfBuffer);
  } catch (err) {
    if (err instanceof ValidationError) {
      return res.status(400).json({ error: err.message });
    }
    console.error('ID Card generation error:', err);
    return res.status(500).json({ error: 'Internal server error while generating the ID card PDF.' });
  }
});

app.post('/api/id-cards/batch', async (req, res) => {
  try {
    if (!idCardModulesAvailable) {
      return res.status(503).json({ error: 'ID Card generation module not available' });
    }

    const mergedCards = validateBatchRequest(req.body);
    const pdfBuffer = await generateBatchPdf(mergedCards);

    res.status(200);
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', `inline; filename="student-id-batch-${mergedCards.length}.pdf"`);
    res.setHeader('Content-Length', pdfBuffer.length);
    res.end(pdfBuffer);
  } catch (err) {
    if (err instanceof ValidationError) {
      return res.status(400).json({ error: err.message });
    }
    console.error('Batch ID Card generation error:', err);
    return res.status(500).json({ error: 'Internal server error while generating the batch PDF.' });
  }
});

// ==================== SOCKET.IO ====================
io.on('connection', (socket) => {
  console.log('🟢 Client connected:', socket.id);
  
  socket.on('join_institute', (instituteId) => {
    socket.join(`institute_${instituteId}`);
    console.log(`📌 Client ${socket.id} joined institute: ${instituteId}`);
    
    if (globalClient.isReady) {
      socket.emit('global_ready', 'WhatsApp is ready for all institutes!');
      console.log(`✅ Sent global ready to ${socket.id}`);
    } else if (globalClient.qrCode) {
      qrcode.toDataURL(globalClient.qrCode, { scale: 8 }).then(qrImage => {
        socket.emit('global_qr', qrImage);
        console.log(`✅ Sent QR to ${socket.id}`);
      }).catch(() => {
        socket.emit('global_qr', globalClient.qrCode);
      });
    } else if (globalClient.isConnecting || globalClient.connectionInProgress) {
      socket.emit('connecting', 'Connecting to WhatsApp...');
    } else {
      socket.emit('global_disconnected', 'WhatsApp is not connected');
    }
  });
  
  socket.on('request_qr', async (instituteId) => {
    console.log(`📱 QR requested via socket for institute ${instituteId}`);
    
    if (globalClient.isReady) {
      socket.emit('global_ready', 'WhatsApp is already connected!');
      return;
    }
    
    await clearGlobalAuthData();
    setTimeout(() => connectGlobalWhatsApp(true), 1000);
    socket.emit('qr_requested', 'QR code requested. Please wait.');
  });
  
  socket.on('disconnect', () => {
    console.log('🔴 Client disconnected:', socket.id);
  });
});

// ==================== START SERVER ====================
const PORT = process.env.PORT || 4000;

server.listen(PORT, async () => {
  console.log(`\n🚀 WhatsApp + Academic Reports + ID Card Server: http://localhost:${PORT}`);
  console.log(`🌍 WhatsApp Mode: GLOBAL - ONE connection for ALL institutes`);
  console.log(`📱 Connection Mode: QR CODE SCANNING`);
  console.log(`💾 Auth: ${getSupabaseClient() ? 'Supabase' : 'Local'}`);
  
  // Try to connect with existing auth
  const hasAuth = await syncFromSupabase();
  if (hasAuth) {
    console.log(`📱 Found existing auth, attempting to connect...`);
    setTimeout(() => connectGlobalWhatsApp(false), 2000);
  } else {
    console.log(`📱 No existing auth found. Use POST /api/request-qr/:instituteId to generate QR.`);
  }
  
  console.log(`\n📄 Report Card API ready:`);
  console.log(`   POST /generate-report-cards (bulk standard)`);
  console.log(`   POST /generate-report-card (single standard)`);
  console.log(`   POST /generate-competency-report-cards (bulk CBC)`);
  console.log(`   POST /generate-competency-report-card (single CBC)`);
  console.log(`   POST /generate (auto-detect bulk)`);
  console.log(`   POST /generate-single (auto-detect single)`);
  
  if (idCardModulesAvailable) {
    console.log(`🪪 ID Card API ready:`);
    console.log(`   POST /api/id-cards (single)`);
    console.log(`   POST /api/id-cards/batch (batch)`);
  }
  
  console.log(`\n🌍 GLOBAL MODE: Once the master connects, ALL institutes can send messages!`);
  console.log(`📱 Scan QR code with WhatsApp on your phone`);
  console.log(`   POST /api/request-qr/:instituteId to generate QR`);
  console.log(`\n✅ Server ready\n`);
});

// Graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n🛑 Shutting down gracefully...');
  if (globalClient.sock) {
    try {
      await globalClient.sock.logout();
      globalClient.sock.end();
    } catch(e) {}
  }
  console.log('✅ Shutdown complete.');
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.log('\n🛑 Shutting down gracefully...');
  if (globalClient.sock) {
    try {
      await globalClient.sock.logout();
      globalClient.sock.end();
    } catch(e) {}
  }
  console.log('✅ Shutdown complete.');
  process.exit(0);
});

module.exports = { app, server, io };