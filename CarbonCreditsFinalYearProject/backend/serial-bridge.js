require('dotenv').config();
const { SerialPort } = require('serialport');
const { ReadlineParser } = require('@serialport/parser-readline');
const mysql = require('mysql2/promise');
const axios = require('axios');

// ==========================================
// CONFIGURATION
// ==========================================

// Find your Arduino COM port
// Windows: COM3, COM4, etc.
// Mac: /dev/tty.usbmodem14201
// Linux: /dev/ttyACM0, /dev/ttyUSB0

const ARDUINO_PORT = 'COM7';  // ← CHANGE THIS to your port!
const BAUD_RATE = 9600;

// API Configuration
const API_URL = 'http://localhost:3000/api/emissions';
const AUTH_TOKEN = 'your-auth-token-here'; // Get from login

// Database Configuration (direct connection)
const dbConfig = {
    host: process.env.DB_HOST || 'localhost',
    user: process.env.DB_USER || 'root',
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME || 'carbon_credit_db'
};

// ==========================================
// SETUP SERIAL PORT
// ==========================================

console.log('🔌 Connecting to Arduino on port:', ARDUINO_PORT);

const port = new SerialPort({
    path: ARDUINO_PORT,
    baudRate: BAUD_RATE
});

const parser = port.pipe(new ReadlineParser({ delimiter: '\n' }));

// ==========================================
// DATABASE CONNECTION
// ==========================================

let dbConnection;

async function connectDatabase() {
    try {
        dbConnection = await mysql.createConnection(dbConfig);
        console.log('✅ Database connected');
    } catch (error) {
        console.error('❌ Database connection failed:', error.message);
        process.exit(1);
    }
}

// ==========================================
// SAVE DATA TO DATABASE
// ==========================================

async function saveToDatabase(data) {
    try {
        const emission_id = `EM_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
        
        const query = `
            INSERT INTO Emission_Data 
            (emission_id, timestamp, co2_value, temperature, humidity, sensor_id) 
            VALUES (?, NOW(), ?, ?, ?, ?)
        `;
        
        await dbConnection.execute(query, [
            emission_id,
            data.co2_value,
            data.temperature,
            data.humidity,
            data.sensor_id
        ]);
        
        console.log('💾 Data saved to database:', emission_id);
        return true;
    } catch (error) {
        console.error('❌ Database save error:', error.message);
        return false;
    }
}

// ==========================================
// PROCESS INCOMING DATA
// ==========================================

parser.on('data', async (line) => {
    try {
        // Try to parse as JSON
        const data = JSON.parse(line);
        
        console.log('📊 Received data from Arduino:');
        console.log(`   Sensor: ${data.sensor_id}`);
        console.log(`   CO2: ${data.co2_value} kg/hour`);
        console.log(`   Temperature: ${data.temperature}°C`);
        console.log(`   Humidity: ${data.humidity}%`);
        console.log('');
        
        // Save to database
        await saveToDatabase(data);
        
    } catch (error) {
        // Not JSON, just debug output from Arduino
        console.log('Arduino:', line);
    }
});

// ==========================================
// ERROR HANDLING
// ==========================================

port.on('error', (err) => {
    console.error('❌ Serial port error:', err.message);
    if (err.message.includes('cannot open')) {
        console.log('\n💡 Tips:');
        console.log('1. Check if Arduino is connected via USB');
        console.log('2. Close Arduino IDE Serial Monitor');
        console.log('3. Try different COM port (COM3, COM4, etc.)');
        console.log('4. Run: node list-ports.js to see available ports\n');
    }
});

port.on('open', () => {
    console.log('✅ Serial port opened successfully');
    console.log('📡 Listening for Arduino data...\n');
});

// ==========================================
// STARTUP
// ==========================================

(async () => {
    await connectDatabase();
})();

// Keep process running
process.on('SIGINT', async () => {
    console.log('\n👋 Closing connections...');
    if (dbConnection) await dbConnection.end();
    port.close();
    process.exit(0);
});