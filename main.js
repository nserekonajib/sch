// whatsapp-server.js - Fixed with better timeout handling and no auth clearing on shutdown
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
require('dotenv').config();

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
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// ==================== SUPABASE SETUP ====================
let supabase = null;
try {
  if (process.env.SUPABASE_URL && process.env.SUPABASE_KEY) {
    supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_KEY);
    console.log('✅ Supabase connected');
  }
} catch (error) {
  console.log('⚠️ Supabase not configured');
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
  if (!supabase) return false;
  try {
    const authFolder = getInstituteAuthFolder(instituteId);
    const { data, error } = await supabase
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
  if (!supabase) return;
  try {
    const authFolder = getInstituteAuthFolder(instituteId);
    const files = fs.readdirSync(authFolder);
    for (const filename of files) {
      const filePath = path.join(authFolder, filename);
      const content = fs.readFileSync(filePath, 'utf-8');
      
      const { error } = await supabase
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
  
  if (supabase) {
    try {
      await supabase
        .from('whatsapp_auth_files_custom')
        .delete()
        .eq('institute_id', instituteId);
    } catch(e) {
      console.error('Error deleting auth from Supabase:', e.message);
    }
  }
}

async function storeMessage(instituteId, phoneNumber, message, messageType = 'text', status = 'sent') {
  if (!supabase) return;
  try {
    await supabase
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

// ==================== CONNECT TO WHATSAPP ====================
async function connectToWhatsApp(instituteId) {
  console.log(`🔄 Connecting to WhatsApp for institute ${instituteId}...`);
  
  // Remove existing client if any
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
    reconnectAttempts: 0
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
    
    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;
      
      if (qr) {
        console.log(`📱 QR Code generated for institute ${instituteId}`);
        client.qr = qr;
        
        try {
          const qrImage = await qrcode.toDataURL(qr, { scale: 8 });
          io.to(`institute_${instituteId}`).emit('qr', qrImage);
          console.log(`✅ QR sent to institute room: institute_${instituteId}`);
        } catch(err) {
          console.error('QR generation error:', err);
          io.to(`institute_${instituteId}`).emit('qr', qr);
        }
        client.reconnectAttempts = 0;
      }
      
      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
        console.log(`❌ Connection closed for institute ${instituteId}`);
        client.isReady = false;
        
        if (shouldReconnect && client.reconnectAttempts < 5) {
          client.reconnectAttempts++;
          const delay = Math.min(5000 * client.reconnectAttempts, 30000);
          console.log(`🔄 Reconnecting institute ${instituteId} in ${delay/1000}s... (Attempt ${client.reconnectAttempts})`);
          setTimeout(() => connectToWhatsApp(instituteId), delay);
        } else if (statusCode === DisconnectReason.loggedOut) {
          client.isReady = false;
          io.to(`institute_${instituteId}`).emit('disconnected', 'Logged out');
          await clearAuthData(instituteId);
        }
      } else if (connection === 'open') {
        console.log(`✅ WhatsApp connected for institute ${instituteId}!`);
        client.isReady = true;
        client.reconnectAttempts = 0;
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
    setTimeout(() => connectToWhatsApp(instituteId), 10000);
  }
}

// ==================== API ROUTES ====================

// Health check
app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    clients: clients.size
  });
});

// Get status for an institute
app.get('/api/status/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  
  if (supabase) {
    try {
      const { data, error } = await supabase
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
    qrCode: client.qr,
    reconnectAttempts: client.reconnectAttempts
  });
});

// Request QR code
app.post('/api/request-qr/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  
  if (supabase) {
    try {
      const { data, error } = await supabase
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
  
  await clearAuthData(instituteId);
  setTimeout(() => connectToWhatsApp(instituteId), 1000);
  
  res.json({ success: true, message: 'QR code requested' });
});

// Logout / Disconnect
app.post('/api/logout/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  await clearAuthData(instituteId);
  io.to(`institute_${instituteId}`).emit('disconnected', 'Logged out');
  res.json({ success: true, message: 'Logged out successfully' });
});

// Send text message with increased timeout
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
    
    // Use a timeout promise to handle long sends
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

// Send PDF file with increased timeout
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
    
    // Use a timeout promise to handle long sends
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

// Get messages for an institute
app.get('/api/messages/:instituteId', async (req, res) => {
  const { instituteId } = req.params;
  const limit = parseInt(req.query.limit) || 50;
  
  if (!supabase) {
    return res.status(500).json({ error: 'Supabase not configured' });
  }
  
  try {
    const { data, error } = await supabase
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
      } else if (client.qr) {
        qrcode.toDataURL(client.qr, { scale: 8 }).then(qrImage => {
          socket.emit('qr', qrImage);
          console.log(`✅ Sent QR to ${socket.id}`);
        }).catch(() => {
          socket.emit('qr', client.qr);
        });
      }
    }
  });
  
  socket.on('disconnect', () => {
    console.log('🔴 Client disconnected:', socket.id);
  });
});

// ==================== START SERVER ====================
const PORT = process.env.PORT || 3000;

async function startInstitutes() {
  if (!supabase) {
    console.log('⚠️ Supabase not configured. Starting without multi-institute support.');
    return;
  }
  
  try {
    const { data, error } = await supabase
      .from('whatsapp_settings_custom')
      .select('institute_id')
      .eq('is_enabled', true);
    
    if (error) throw error;
    
    if (data && data.length > 0) {
      console.log(`📱 Starting WhatsApp for ${data.length} institute(s)...`);
      for (const setting of data) {
        await connectToWhatsApp(setting.institute_id);
      }
    } else {
      console.log('ℹ️ No institutes with WhatsApp enabled found.');
    }
  } catch (error) {
    console.error('Error starting institutes:', error.message);
  }
}

server.listen(PORT, async () => {
  console.log(`\n🚀 WhatsApp API Server: http://localhost:${PORT}`);
  console.log(`💾 Auth: ${supabase ? 'Supabase' : 'Local'}`);
  console.log(`📱 Server ready\n`);
  
  await startInstitutes();
});

// Graceful shutdown - DON'T clear auth data on shutdown
process.on('SIGINT', async () => {
  console.log('\n🛑 Shutting down gracefully...');
  // Just close connections without clearing auth
  for (const [instituteId, client] of clients) {
    if (client.sock) {
      try {
        // Just end the connection without logout to preserve session
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