// whatsapp-academic-server.js - Consolidated WhatsApp + Academic Report + ID Card Server
// QR Codes are ONLY generated when explicitly requested

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

// ==================== ID CARD IMPORTS WITH ERROR HANDLING ====================
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
app.use(express.json({ limit: '80mb' }));
app.use(express.urlencoded({ extended: true, limit: '80mb' }));

// ==================== SUPABASE SETUP ====================
let supabase = null;
let supabase2 = null;

try {
  if (process.env.SUPABASE_URL && process.env.SUPABASE_KEY) {
    supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);
    console.log('✅ Supabase Primary connected');
  }
} catch (error) {
  console.log('⚠️ Supabase Primary not configured');
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
const BASE_AUTH_FOLDER = path.join(__dirname, 'auth_info');
if (!fs.existsSync(BASE_AUTH_FOLDER)) {
  fs.mkdirSync(BASE_AUTH_FOLDER, { recursive: true });
}

// ==================== CLIENT STORE ====================
const clients = new Map();

// ==================== HELPERS ====================
function getInstituteAuthFolder(instituteId) {
  const folder = path.join(BASE_AUTH_FOLDER, instituteId);
  if (!fs.existsSync(folder)) {
    fs.mkdirSync(folder, { recursive: true });
  }
  return folder;
}

async function syncFromSupabase(instituteId) {
  const supabaseClient = getSupabaseClient();
  if (!supabaseClient) return false;
  
  try {
    const authFolder = getInstituteAuthFolder(instituteId);
    const { data, error } = await supabaseClient
      .from('whatsapp_auth_files_custom')
      .select('filename, content')
      .eq('institute_id', instituteId);
    
    if (error) throw error;
    if (data && data.length > 0) {
      for (const file of data) {
        fs.writeFileSync(path.join(authFolder, file.filename), file.content);
      }
      console.log(`✅ Auth restored for institute ${instituteId}`);
      return true;
    }
    return false;
  } catch (error) {
    console.error(`Sync error for ${instituteId}:`, error.message);
    return false;
  }
}

async function syncToSupabase(instituteId) {
  const supabaseClient = getSupabaseClient();
  if (!supabaseClient) return;
  
  try {
    const authFolder = getInstituteAuthFolder(instituteId);
    const files = fs.readdirSync(authFolder);
    for (const filename of files) {
      const filePath = path.join(authFolder, filename);
      const content = fs.readFileSync(filePath, 'utf-8');
      
      const { error } = await supabaseClient
        .from('whatsapp_auth_files_custom')
        .upsert(
          { 
            institute_id: instituteId, 
            filename, 
            content, 
            updated_at: new Date().toISOString() 
          }, 
          { onConflict: 'institute_id,filename' }
        );
      
      if (error) console.error('Upsert error:', error.message);
    }
    console.log(`✅ Auth synced to Supabase for institute ${instituteId}`);
  } catch (error) {
    console.error(`Sync error for ${instituteId}:`, error.message);
  }
}

async function clearAuthData(instituteId) {
  console.log(`🗑️ Clearing auth data for institute ${instituteId}...`);
  
  if (clients.has(instituteId)) {
    const client = clients.get(instituteId);
    if (client.sock) {
      try {
        await client.sock.logout();
        client.sock.end();
      } catch(e) {}
    }
    clients.delete(instituteId);
  }
  
  const authFolder = getInstituteAuthFolder(instituteId);
  if (fs.existsSync(authFolder)) {
    fs.rmSync(authFolder, { recursive: true, force: true });
    fs.mkdirSync(authFolder, { recursive: true });
  }
  
  const supabaseClient = getSupabaseClient();
  if (supabaseClient) {
    try {
      await supabaseClient
        .from('whatsapp_auth_files_custom')
        .delete()
        .eq('institute_id', instituteId);
    } catch(e) {
      console.error('Error deleting auth from Supabase:', e.message);
    }
  }
}

async function storeMessage(instituteId, phoneNumber, message, messageType = 'text', status = 'sent') {
  const supabaseClient = getSupabaseClient();
  if (!supabaseClient) return;
  
  try {
    await supabaseClient
      .from('whatsapp_messages_custom')
      .insert([{
        institute_id: instituteId,
        phone_number: phoneNumber,
        message: message,
        message_type: messageType,
        status: status,
        sent_at: new Date().toISOString()
      }]);
  } catch(e) {
    console.error('Error storing message:', e.message);
  }
}

// ==================== CONNECT TO WHATSAPP (QR ONLY ON REQUEST) ====================
async function connectToWhatsApp(instituteId, forceQR = false) {
  console.log(`🔄 Connecting to WhatsApp for institute ${instituteId}...`);
  
  // If we already have a client for this institute, clean it up
  if (clients.has(instituteId)) {
    const existing = clients.get(instituteId);
    if (existing.sock) {
      try { await existing.sock.logout(); existing.sock.end(); } catch(e) {}
    }
    clients.delete(instituteId);
  }
  
  const client = {
    sock: null,
    qr: null,
    isReady: false,
    reconnectAttempts: 0,
    qrRequested: forceQR || false,  // Only generate QR if explicitly requested
    isConnecting: false
  };
  clients.set(instituteId, client);
  
  try {
    const authFolder = getInstituteAuthFolder(instituteId);
    await syncFromSupabase(instituteId);
    
    const { state, saveCreds } = await useMultiFileAuthState(authFolder);
    const { version } = await fetchLatestBaileysVersion();
    
    const sock = makeWASocket({
      version,
      auth: state,
      logger: P({ level: 'silent' }),
      browser: ['Lunserk ERP WhatsApp', 'Chrome', '1.0.0'],
      connectTimeoutMs: 60000,
      defaultQueryTimeoutMs: 60000,
      keepAliveIntervalMs: 10000
    });
    
    client.sock = sock;
    client.isConnecting = true;
    
    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;
      
      // QR Code handling - ONLY emit if explicitly requested
      if (qr) {
        client.qr = qr;
        
        // Only emit QR if it was explicitly requested
        if (client.qrRequested) {
          console.log(`📱 QR Code generated for institute ${instituteId} (requested)`);
          try {
            const qrImage = await qrcode.toDataURL(qr, { scale: 8 });
            io.to(`institute_${instituteId}`).emit('qr', qrImage);
            console.log(`✅ QR sent to institute room: institute_${instituteId}`);
          } catch(err) {
            console.error('QR generation error:', err);
            io.to(`institute_${instituteId}`).emit('qr', qr);
          }
          // Reset the flag so we don't keep sending QR codes
          client.qrRequested = false;
        } else {
          console.log(`📱 QR Code available for institute ${instituteId} (waiting for request)`);
        }
        client.reconnectAttempts = 0;
      }
      
      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
        console.log(`❌ Connection closed for institute ${instituteId}`);
        client.isReady = false;
        client.isConnecting = false;
        
        if (shouldReconnect && client.reconnectAttempts < 5) {
          client.reconnectAttempts++;
          const delay = Math.min(5000 * client.reconnectAttempts, 30000);
          console.log(`🔄 Reconnecting institute ${instituteId} in ${delay/1000}s... (Attempt ${client.reconnectAttempts})`);
          setTimeout(() => connectToWhatsApp(instituteId, false), delay);
        } else if (statusCode === DisconnectReason.loggedOut) {
          client.isReady = false;
          io.to(`institute_${instituteId}`).emit('disconnected', 'Logged out');
          await clearAuthData(instituteId);
        }
      } else if (connection === 'open') {
        console.log(`✅ WhatsApp connected for institute ${instituteId}!`);
        client.isReady = true;
        client.isConnecting = false;
        client.reconnectAttempts = 0;
        client.qr = null; // Clear QR after successful connection
        io.to(`institute_${instituteId}`).emit('ready', 'WhatsApp client is ready!');
        io.emit('ready_' + instituteId, 'WhatsApp client is ready!');
      }
    });
    
    sock.ev.on('creds.update', async () => {
      await saveCreds();
      await syncToSupabase(instituteId);
    });
    
    sock.ev.on('error', (err) => {
      console.error(`Socket error for institute ${instituteId}:`, err.message);
    });
    
  } catch (error) {
    console.error(`❌ Connection error for institute ${instituteId}:`, error.message);
    client.isConnecting = false;
    setTimeout(() => connectToWhatsApp(instituteId, forceQR), 10000);
  }
}

// ==================== REPORT CARD HELPERS ====================

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
    const { 
      school, 
      term, 
      assessments, 
      weightedColumns, 
      gradeScale, 
      keyTerms, 
      resultDefinitions 
    } = req.body;

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

// ==================== API ROUTES - WHATSAPP ====================

app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    clients: clients.size,
    supabase: !!getSupabaseClient(),
    idCardModules: idCardModulesAvailable
  });
});

app.get('/api/status/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  const supabaseClient = getSupabaseClient();
  
  if (supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from('whatsapp_settings_custom')
        .select('is_enabled')
        .eq('institute_id', instituteId)
        .single();
      
      if (error || !data || !data.is_enabled) {
        return res.json({ 
          ready: false, 
          qrCode: null,
          message: 'WhatsApp is disabled for this institute'
        });
      }
    } catch(e) {}
  }
  
  const client = clients.get(instituteId);
  if (!client) {
    return res.json({ 
      ready: false, 
      qrCode: null,
      message: 'Not connected'
    });
  }
  
  res.json({
    ready: client.isReady,
    qrCode: client.qr || null,
    reconnectAttempts: client.reconnectAttempts,
    qrRequested: client.qrRequested,
    isConnecting: client.isConnecting || false
  });
});

app.post('/api/request-qr/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  const supabaseClient = getSupabaseClient();
  
  if (supabaseClient) {
    try {
      const { data, error } = await supabaseClient
        .from('whatsapp_settings_custom')
        .select('is_enabled')
        .eq('institute_id', instituteId)
        .single();
      
      if (error || !data || !data.is_enabled) {
        return res.status(400).json({ 
          success: false, 
          message: 'WhatsApp is disabled for this institute' 
        });
      }
    } catch(e) {}
  }
  
  // Clear old auth data to force new QR
  await clearAuthData(instituteId);
  
  // Connect with forceQR=true to generate QR immediately
  setTimeout(() => connectToWhatsApp(instituteId, true), 1000);
  
  res.json({ success: true, message: 'QR code requested. QR will be generated and sent via socket.' });
});

app.post('/api/logout/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  await clearAuthData(instituteId);
  io.to(`institute_${instituteId}`).emit('disconnected', 'Logged out');
  res.json({ success: true, message: 'Logged out successfully' });
});

app.post('/api/send', async (req, res) => {
  const { number, message, instituteId } = req.body;
  
  if (!instituteId) {
    return res.status(400).json({ error: 'Institute ID is required' });
  }
  
  const client = clients.get(instituteId);
  if (!client || !client.isReady || !client.sock) {
    return res.status(400).json({ error: 'WhatsApp not ready for this institute' });
  }
  
  try {
    const formattedNumber = number.includes('@') ? number : `${number}@s.whatsapp.net`;
    
    const sendPromise = client.sock.sendMessage(formattedNumber, { text: message });
    const timeoutPromise = new Promise((_, reject) => 
      setTimeout(() => reject(new Error('Send timeout')), 30000)
    );
    
    await Promise.race([sendPromise, timeoutPromise]);
    
    await storeMessage(instituteId, number, message, 'text', 'sent');
    res.json({ success: true, message: 'Message sent successfully' });
  } catch (error) {
    console.error(`Send error for institute ${instituteId}:`, error.message);
    await storeMessage(instituteId, number, message, 'text', 'failed');
    res.status(500).json({ error: error.message || 'Failed to send message' });
  }
});

app.post('/api/send-pdf', async (req, res) => {
  const { number, pdfBuffer, filename, instituteId } = req.body;
  
  if (!instituteId) {
    return res.status(400).json({ error: 'Institute ID is required' });
  }
  
  const client = clients.get(instituteId);
  if (!client || !client.isReady || !client.sock) {
    return res.status(400).json({ error: 'WhatsApp not ready for this institute' });
  }
  
  try {
    const formattedNumber = number.includes('@') ? number : `${number}@s.whatsapp.net`;
    const buffer = Buffer.from(pdfBuffer, 'base64');
    
    const sendPromise = client.sock.sendMessage(formattedNumber, {
      document: buffer,
      mimetype: 'application/pdf',
      fileName: filename || 'document.pdf'
    });
    const timeoutPromise = new Promise((_, reject) => 
      setTimeout(() => reject(new Error('Send timeout')), 60000)
    );
    
    await Promise.race([sendPromise, timeoutPromise]);
    
    await storeMessage(instituteId, number, filename || 'document.pdf', 'pdf', 'sent');
    res.json({ success: true, message: 'PDF sent successfully' });
  } catch (error) {
    console.error(`Send PDF error for institute ${instituteId}:`, error.message);
    await storeMessage(instituteId, number, filename || 'document.pdf', 'pdf', 'failed');
    res.status(500).json({ error: error.message || 'Failed to send PDF' });
  }
});

app.get('/api/messages/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  const limit = parseInt(req.query.limit) || 50;
  const supabaseClient = getSupabaseClient();
  
  if (!supabaseClient) {
    return res.status(500).json({ error: 'Supabase not configured' });
  }
  
  try {
    const { data, error } = await supabaseClient
      .from('whatsapp_messages_custom')
      .select('*')
      .eq('institute_id', instituteId)
      .order('sent_at', { ascending: false })
      .limit(limit);
    
    if (error) throw error;
    res.json({ success: true, messages: data });
  } catch (error) {
    console.error('Error fetching messages:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// ==================== API ROUTES - ACADEMIC REPORTS ====================

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

// ==================== API ROUTES - STUDENT ID CARDS ====================

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
    
    const client = clients.get(instituteId);
    if (client) {
      if (client.isReady) {
        socket.emit('ready', 'WhatsApp client is ready!');
        console.log(`✅ Sent ready to ${socket.id}`);
      } else if (client.qr && client.qrRequested) {
        // Only send QR if it was requested
        qrcode.toDataURL(client.qr, { scale: 8 }).then(qrImage => {
          socket.emit('qr', qrImage);
          console.log(`✅ Sent QR to ${socket.id}`);
        }).catch(() => {
          socket.emit('qr', client.qr);
        });
        client.qrRequested = false; // Reset after sending
      } else if (client.qr) {
        socket.emit('qr_available', 'QR code is available. Request it via /api/request-qr');
        console.log(`ℹ️ QR available but not requested for ${instituteId}`);
      }
    }
  });
  
  socket.on('request_qr', async (instituteId) => {
    console.log(`📱 QR requested via socket for institute ${instituteId}`);
    const supabaseClient = getSupabaseClient();
    
    if (supabaseClient) {
      try {
        const { data, error } = await supabaseClient
          .from('whatsapp_settings_custom')
          .select('is_enabled')
          .eq('institute_id', instituteId)
          .single();
        
        if (error || !data || !data.is_enabled) {
          socket.emit('error', 'WhatsApp is disabled for this institute');
          return;
        }
      } catch(e) {}
    }
    
    await clearAuthData(instituteId);
    setTimeout(() => connectToWhatsApp(instituteId, true), 1000);
    socket.emit('qr_requested', 'QR code requested. Please wait for QR generation.');
  });
  
  socket.on('disconnect', () => {
    console.log('🔴 Client disconnected:', socket.id);
  });
});

// ==================== START SERVER ====================
const PORT = process.env.PORT || 4000;

// IMPORTANT: Do NOT auto-start WhatsApp connections on server startup
// Only start the server and wait for QR requests
server.listen(PORT, async () => {
  console.log(`\n🚀 WhatsApp + Academic Reports + ID Card Server: http://localhost:${PORT}`);
  console.log(`💾 Auth: ${getSupabaseClient() ? 'Supabase' : 'Local'}`);
  console.log(`📱 WhatsApp API ready (QR codes generated ONLY on request)`);
  console.log(`📄 Report Card API ready:`);
  console.log(`   - POST /generate-report-cards (bulk standard)`);
  console.log(`   - POST /generate-report-card (single standard)`);
  console.log(`   - POST /generate-competency-report-cards (bulk CBC)`);
  console.log(`   - POST /generate-competency-report-card (single CBC)`);
  console.log(`   - POST /generate (auto-detect bulk)`);
  console.log(`   - POST /generate-single (auto-detect single)`);
  if (idCardModulesAvailable) {
    console.log(`🪪 ID Card API ready:`);
    console.log(`   - POST /api/id-cards (single)`);
    console.log(`   - POST /api/id-cards/batch (batch)`);
  } else {
    console.log(`⚠️ ID Card API not available (modules missing)`);
  }
  console.log(`\n📱 QR codes are generated ONLY when requested via:`);
  console.log(`   POST /api/request-qr/:instituteId`);
  console.log(`   or socket 'request_qr' event`);
  console.log(`\n✅ Server ready\n`);
});

// Graceful shutdown - DON'T clear auth data on shutdown
process.on('SIGINT', async () => {
  console.log('\n🛑 Shutting down gracefully...');
  for (const [instituteId, client] of clients) {
    if (client.sock) {
      try {
        client.sock.end();
      } catch(e) {
        console.log(`Error closing connection for ${instituteId}:`, e.message);
      }
    }
  }
  console.log('✅ Shutdown complete. Sessions preserved.');
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.log('\n🛑 Shutting down gracefully...');
  for (const [instituteId, client] of clients) {
    if (client.sock) {
      try {
        client.sock.end();
      } catch(e) {}
    }
  }
  console.log('✅ Shutdown complete. Sessions preserved.');
  process.exit(0);
});

module.exports = { app, server, io };