require('dotenv').config();
const { SerialPort } = require('serialport');
const { ReadlineParser } = require('@serialport/parser-readline');
const mysql = require('mysql2/promise');

// ==========================================
// CONFIGURATION
// ==========================================

const ARDUINO_PORT = 'COM7';   // ← Run: node list-ports.js to find yours
const BAUD_RATE = 9600;

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

const port = new SerialPort({ path: ARDUINO_PORT, baudRate: BAUD_RATE });
const parser = port.pipe(new ReadlineParser({ delimiter: '\n' }));

// ==========================================
// DATABASE CONNECTION
// ==========================================

let dbConnection;

async function connectDatabase() {
    try {
        dbConnection = await mysql.createConnection(dbConfig);
        console.log('✅ Database connected');

        // Add co2_ppm column if it doesn't exist yet
        await dbConnection.execute(`
            ALTER TABLE Emission_Data
            ADD COLUMN IF NOT EXISTS co2_ppm INT DEFAULT NULL
        `).catch(() => {
            // Column may already exist — ignore the error
        });

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

        await dbConnection.execute(`
            INSERT INTO Emission_Data
            (emission_id, timestamp, co2_value, co2_ppm, temperature, humidity, sensor_id)
            VALUES (?, NOW(), ?, ?, ?, ?, ?)
        `, [
            emission_id,
            data.co2_value,       // kg/hour (converted value)
            data.co2_ppm || null, // raw ppm from sensor
            data.temperature,
            data.humidity,
            data.sensor_id
        ]);

        console.log(`💾 Saved | ${emission_id} | ${data.co2_ppm} ppm | ${parseFloat(data.co2_value).toFixed(4)} kg/hr`);
        return true;
    } catch (error) {
        console.error('❌ Database save error:', error.message);
        return false;
    }
}

// ==========================================
// PROCESS INCOMING SERIAL DATA
// ==========================================

parser.on('data', async (line) => {
    line = line.trim();
    if (!line.startsWith('{')) {
        // Debug/status message from Arduino — just print it
        console.log('Arduino:', line);
        return;
    }

    try {
        const data = JSON.parse(line);

        console.log('\n📊 Received from MH-Z19D:');
        console.log(`   Sensor ID  : ${data.sensor_id}`);
        console.log(`   CO2 (ppm)  : ${data.co2_ppm} ppm`);
        console.log(`   CO2 (kg/hr): ${parseFloat(data.co2_value).toFixed(4)} kg/hr`);
        console.log(`   Temperature: ${data.temperature}°C`);
        console.log(`   Humidity   : ${data.humidity}%`);

        await saveToDatabase(data);

    } catch (err) {
        console.log('Arduino (raw):', line);
    }
});

// ==========================================
// ERROR HANDLING
// ==========================================

port.on('error', (err) => {
    console.error('❌ Serial port error:', err.message);
    if (err.message.includes('cannot open')) {
        console.log('\n💡 Tips:');
        console.log('   1. Run: node list-ports.js to find the correct COM port');
        console.log('   2. Close Arduino IDE Serial Monitor if open');
        console.log('   3. Unplug and replug the Arduino USB cable');
        console.log('   4. Update ARDUINO_PORT at the top of this file\n');
    }
});

port.on('open', () => {
    console.log('✅ Serial port opened on', ARDUINO_PORT);
    console.log('📡 Waiting for MH-Z19D warm-up (~60 seconds)...\n');
});

// ==========================================
// STARTUP
// ==========================================

(async () => {
    await connectDatabase();
})();

process.on('SIGINT', async () => {
    console.log('\n👋 Shutting down...');
    if (dbConnection) await dbConnection.end();
    port.close();
    process.exit(0);
});