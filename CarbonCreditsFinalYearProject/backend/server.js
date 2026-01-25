require('dotenv').config();
const express = require('express');
const mysql = require('mysql2/promise');
const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const cors = require('cors');

const app = express();

// Middleware
app.use(express.json());
app.use(cors());

// Database Connection Pool
const pool = mysql.createPool({
    host: process.env.DB_HOST,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME,
    waitForConnections: true,
    connectionLimit: 10
});

// Test database connection
pool.getConnection()
    .then(connection => {
        console.log('✅ Database connected successfully');
        connection.release();
    })
    .catch(err => {
        console.error('❌ Database connection failed:', err.message);
    });

// ==========================================
// AUTHENTICATION MIDDLEWARE
// ==========================================
const authenticateToken = (req, res, next) => {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];

    if (!token) {
        return res.status(401).json({ error: 'Access token required' });
    }

    jwt.verify(token, process.env.JWT_SECRET, (err, user) => {
        if (err) return res.status(403).json({ error: 'Invalid token' });
        req.user = user;
        next();
    });
};

// ==========================================
// ROUTES - AUTHENTICATION
// ==========================================

// Register
app.post('/api/auth/register', async (req, res) => {
    try {
        const { name, email, password, role } = req.body;

        if (!name || !email || !password) {
            return res.status(400).json({ error: 'All fields required' });
        }

        // Check if user exists
        const [existing] = await pool.query(
            'SELECT user_id FROM User WHERE email = ?',
            [email]
        );

        if (existing.length > 0) {
            return res.status(409).json({ error: 'Email already registered' });
        }

        // Hash password
        const password_hash = await bcrypt.hash(password, 10);

        // Insert user
        const [result] = await pool.query(
            'INSERT INTO User (name, email, role, password_hash) VALUES (?, ?, ?, ?)',
            [name, email, role || 'operator', password_hash]
        );

        res.status(201).json({
            message: 'Registration successful',
            user_id: result.insertId
        });
    } catch (error) {
        console.error('Registration error:', error);
        res.status(500).json({ error: 'Registration failed' });
    }
});

// Login
app.post('/api/auth/login', async (req, res) => {
    try {
        const { email, password } = req.body;

        const [users] = await pool.query(
            'SELECT user_id, name, email, role, password_hash FROM User WHERE email = ?',
            [email]
        );

        if (users.length === 0) {
            return res.status(401).json({ error: 'Invalid credentials' });
        }

        const user = users[0];
        const validPassword = await bcrypt.compare(password, user.password_hash);

        if (!validPassword) {
            return res.status(401).json({ error: 'Invalid credentials' });
        }

        const token = jwt.sign(
            { user_id: user.user_id, email: user.email, role: user.role },
            process.env.JWT_SECRET,
            { expiresIn: '24h' }
        );

        res.json({
            message: 'Login successful',
            token,
            user: {
                user_id: user.user_id,
                name: user.name,
                email: user.email,
                role: user.role
            }
        });
    } catch (error) {
        console.error('Login error:', error);
        res.status(500).json({ error: 'Login failed' });
    }
});

// ==========================================
// ROUTES - EMISSIONS
// ==========================================

// Insert emission data
app.post('/api/emissions', authenticateToken, async (req, res) => {
    try {
        const { sensor_id, co2_value, pm25_value, temperature, humidity } = req.body;
        const emission_id = `EM_${Date.now()}_${Math.floor(Math.random() * 1000)}`;

        await pool.query(
            `INSERT INTO Emission_Data 
            (emission_id, timestamp, co2_value, pm25_value, temperature, humidity, sensor_id) 
            VALUES (?, NOW(), ?, ?, ?, ?, ?)`,
            [emission_id, co2_value, pm25_value, temperature, humidity, sensor_id]
        );

        res.status(201).json({
            message: 'Emission data recorded',
            emission_id
        });
    } catch (error) {
        console.error('Emission insert error:', error);
        res.status(500).json({ error: 'Failed to record emission' });
    }
});

// Get recent emissions
app.get('/api/emissions/recent', authenticateToken, async (req, res) => {
    try {
        const [emissions] = await pool.query(
            `SELECT ed.*, s.location, s.sensor_type
            FROM Emission_Data ed
            JOIN Sensor s ON ed.sensor_id = s.sensor_id
            WHERE s.user_id = ?
            ORDER BY ed.timestamp DESC
            LIMIT 50`,
            [req.user.user_id]
        );

        res.json(emissions);
    } catch (error) {
        console.error('Fetch emissions error:', error);
        res.status(500).json({ error: 'Failed to fetch emissions' });
    }
});

// ==========================================
// ROUTES - DASHBOARD
// ==========================================

app.get('/api/dashboard/stats', authenticateToken, async (req, res) => {
    try {
        // Current emission
        const [[currentEmission]] = await pool.query(
            `SELECT co2_value 
            FROM Emission_Data ed
            JOIN Sensor s ON ed.sensor_id = s.sensor_id
            WHERE s.user_id = ?
            ORDER BY ed.timestamp DESC LIMIT 1`,
            [req.user.user_id]
        );

        // Total credits
        const [[totalCredits]] = await pool.query(
            `SELECT COALESCE(SUM(credit_amount), 0) as total
            FROM Carbon_Credit cc
            JOIN Credit_Emission_Map cem ON cc.credit_id = cem.credit_id
            JOIN Emission_Data ed ON cem.emission_id = ed.emission_id
            JOIN Sensor s ON ed.sensor_id = s.sensor_id
            WHERE s.user_id = ?`,
            [req.user.user_id]
        );

        // Active sensors
        const [[activeSensors]] = await pool.query(
            'SELECT COUNT(*) as count FROM Sensor WHERE user_id = ? AND status = "active"',
            [req.user.user_id]
        );

        // Unread alerts
        const [[unreadAlerts]] = await pool.query(
            'SELECT COUNT(*) as count FROM Alert WHERE user_id = ? AND is_read = FALSE',
            [req.user.user_id]
        );

        res.json({
            current_emission: currentEmission?.co2_value || 0,
            total_credits: totalCredits?.total || 0,
            active_sensors: activeSensors?.count || 0,
            unread_alerts: unreadAlerts?.count || 0
        });
    } catch (error) {
        console.error('Dashboard stats error:', error);
        res.status(500).json({ error: 'Failed to fetch dashboard stats' });
    }
});

// ==========================================
// ROUTES - ALERTS
// ==========================================

app.get('/api/alerts', authenticateToken, async (req, res) => {
    try {
        const [alerts] = await pool.query(
            `SELECT * FROM Alert 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 50`,
            [req.user.user_id]
        );

        res.json(alerts);
    } catch (error) {
        console.error('Fetch alerts error:', error);
        res.status(500).json({ error: 'Failed to fetch alerts' });
    }
});

// ==========================================
// START SERVER
// ==========================================

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
    console.log(`
╔═══════════════════════════════════════╗
║  🌱 Carbon Credit API Server         ║
║  📡 Running on port ${PORT}              ║
║  🔗 http://localhost:${PORT}             ║
║  📊 Database: ${process.env.DB_NAME}  ║
╚═══════════════════════════════════════╝
    `);
});