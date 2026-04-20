require('dotenv').config();
const express = require('express');
const mysql = require('mysql2/promise');
const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(cors());

// ==========================================
// DATABASE POOL
// ==========================================
const pool = mysql.createPool({
    host:             process.env.DB_HOST,
    user:             process.env.DB_USER,
    password:         process.env.DB_PASSWORD,
    database:         process.env.DB_NAME,
    waitForConnections: true,
    connectionLimit:  10
});

pool.getConnection()
    .then(c => { console.log('✅ Database connected'); c.release(); })
    .catch(e => console.error('❌ Database connection failed:', e.message));

// ==========================================
// AUTH MIDDLEWARE
// ==========================================
const authenticateToken = (req, res, next) => {
    const token = (req.headers['authorization'] || '').split(' ')[1];
    if (!token) return res.status(401).json({ error: 'Access token required' });
    jwt.verify(token, process.env.JWT_SECRET, (err, user) => {
        if (err) return res.status(403).json({ error: 'Invalid or expired token' });
        req.user = user;
        next();
    });
};

// ==========================================
// ADMIN MIDDLEWARE
// ==========================================
const requireAdmin = (req, res, next) => {
    if (req.user.role !== 'admin')
        return res.status(403).json({ error: 'Admin access required' });
    next();
};

// ==========================================
// HELPER: get sensor_id for a user
// ==========================================
async function getUserSensorId(user_id) {
    const [rows] = await pool.query(
        'SELECT sensor_id FROM Sensor WHERE user_id = ? AND status = "active" LIMIT 1',
        [user_id]
    );
    return rows.length > 0 ? rows[0].sensor_id : null;
}

// ==========================================
// AUTH ROUTES
// ==========================================

// Register — always assigns role 'user', auto-creates a sensor row
app.post('/api/auth/register', async (req, res) => {
    try {
        const { name, email, password } = req.body;

        if (!name || !email || !password)
            return res.status(400).json({ error: 'All fields required' });

        const [existing] = await pool.query(
            'SELECT user_id FROM User WHERE email = ?', [email]
        );
        if (existing.length > 0)
            return res.status(409).json({ error: 'Email already registered' });

        const password_hash = await bcrypt.hash(password, 10);

        // Insert user — role is always 'user'
        let result;
        try {
            [result] = await pool.query(
                'INSERT INTO User (name, email, role, password_hash) VALUES (?, ?, ?, ?)',
                [name, email, 'user', password_hash]
            );
        } catch (userErr) {
            console.error('❌ User insert failed:', userErr.message);
            if (userErr.message.includes('Data truncated') || userErr.message.includes('ER_BAD_FIELD_ERROR')) {
                return res.status(500).json({
                    error: 'Database role column not updated. Run this SQL: ALTER TABLE User MODIFY COLUMN role ENUM(\'user\',\'admin\') NOT NULL DEFAULT \'user\';'
                });
            }
            return res.status(500).json({ error: 'Failed to create user: ' + userErr.message });
        }

        const user_id   = result.insertId;
        const sensor_id = `SENSOR_${String(user_id).padStart(4, '0')}`;

        // Auto-create sensor — INSERT IGNORE prevents crash on duplicate
        try {
            await pool.query(
                `INSERT IGNORE INTO Sensor (sensor_id, sensor_type, model, installation_date, status, location, user_id)
                 VALUES (?, 'CO2', 'MH-Z19D', CURDATE(), 'active', 'Main Location', ?)`,
                [sensor_id, user_id]
            );
        } catch (sensorErr) {
            console.warn('⚠️ Sensor auto-create failed (user still registered):', sensorErr.message);
        }

        console.log(`✅ Registered: ${email} (user_id=${user_id}) → sensor: ${sensor_id}`);
        res.status(201).json({ message: 'Registration successful', user_id, sensor_id });

    } catch (error) {
        console.error('❌ Registration error:', error.message);
        res.status(500).json({ error: 'Registration failed: ' + error.message });
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
        if (users.length === 0)
            return res.status(401).json({ error: 'Invalid credentials' });

        const user = users[0];
        if (!await bcrypt.compare(password, user.password_hash))
            return res.status(401).json({ error: 'Invalid credentials' });

        const sensor_id = await getUserSensorId(user.user_id);
        const token = jwt.sign(
            { user_id: user.user_id, email: user.email, role: user.role },
            process.env.JWT_SECRET,
            { expiresIn: '24h' }
        );

        res.json({
            message: 'Login successful',
            token,
            user: { user_id: user.user_id, name: user.name, email: user.email, role: user.role, sensor_id }
        });
    } catch (error) {
        console.error('Login error:', error);
        res.status(500).json({ error: 'Login failed' });
    }
});

// Verify token
app.get('/api/auth/verify', authenticateToken, (req, res) => {
    res.json({ valid: true, user: req.user });
});

// Refresh token
app.post('/api/auth/refresh', authenticateToken, async (req, res) => {
    try {
        const [users] = await pool.query(
            'SELECT user_id, name, email, role FROM User WHERE user_id = ?',
            [req.user.user_id]
        );
        if (users.length === 0)
            return res.status(404).json({ error: 'User not found' });

        const user      = users[0];
        const sensor_id = await getUserSensorId(user.user_id);
        const newToken  = jwt.sign(
            { user_id: user.user_id, email: user.email, role: user.role },
            process.env.JWT_SECRET,
            { expiresIn: '24h' }
        );

        console.log(`🔄 Token refreshed for: ${user.email}`);
        res.json({ message: 'Token refreshed', token: newToken, user: { ...user, sensor_id } });
    } catch (error) {
        res.status(500).json({ error: 'Failed to refresh token' });
    }
});

// ==========================================
// SENSOR ROUTES
// ==========================================

app.get('/api/sensor', authenticateToken, async (req, res) => {
    try {
        const [rows] = await pool.query(
            'SELECT * FROM Sensor WHERE user_id = ?', [req.user.user_id]
        );
        res.json(rows[0] || null);
    } catch (error) {
        res.status(500).json({ error: 'Failed to fetch sensor' });
    }
});

app.patch('/api/sensor', authenticateToken, async (req, res) => {
    try {
        const { location } = req.body;
        await pool.query(
            'UPDATE Sensor SET location = ? WHERE user_id = ?',
            [location, req.user.user_id]
        );
        res.json({ message: 'Sensor location updated' });
    } catch (error) {
        res.status(500).json({ error: 'Failed to update sensor' });
    }
});

// ==========================================
// EMISSION ROUTES
// ==========================================

// POST — PUBLIC, called by serial-bridge.js (no auth token needed)
// Also saves carbon credit and triggers alert if threshold exceeded
app.post('/api/emissions', async (req, res) => {
    try {
        const { sensor_id, co2_value, co2_ppm, temperature, humidity } = req.body;

        // Validate sensor exists
        const [sensors] = await pool.query(
            'SELECT sensor_id, user_id FROM Sensor s JOIN User u ON s.user_id = u.user_id WHERE s.sensor_id = ? AND s.status = "active"',
            [sensor_id]
        );
        if (sensors.length === 0)
            return res.status(404).json({ error: `Sensor "${sensor_id}" not found. Check SENSOR_ID in Arduino code.` });

        const user_id = sensors[0].user_id;
        const ts      = Date.now();
        const rand    = Math.floor(Math.random() * 1000);
        const emission_id = `EM_${ts}_${rand}`;

        // 1. Save emission record
        await pool.query(
            `INSERT INTO Emission_Data
             (emission_id, timestamp, co2_value, co2_ppm, temperature, humidity, sensor_id)
             VALUES (?, NOW(), ?, ?, ?, ?, ?)`,
            [emission_id, co2_value, co2_ppm || null, temperature, humidity, sensor_id]
        );

        // 2. Calculate and save carbon credit (daily basis)
        try {
            const DAILY_LIMIT = 333.33; // kg/day (10000 kg/month ÷ 30)
            const today = new Date().toISOString().split('T')[0];

            // Sum today's emissions for this sensor
            const [[dailyTotal]] = await pool.query(
                `SELECT COALESCE(SUM(co2_value), 0) as total
                 FROM Emission_Data
                 WHERE sensor_id = ? AND DATE(timestamp) = ?`,
                [sensor_id, today]
            );

            const todayTotal  = parseFloat(dailyTotal.total);
            const difference  = DAILY_LIMIT - todayTotal;
            const status      = difference > 0 ? 'earned' : difference < 0 ? 'deficit' : 'neutral';
            const creditAmt   = Math.abs(difference);
            const credit_id   = `CC_${today.replace(/-/g, '')}_${sensor_id}`;
            const map_id      = `MAP_${credit_id}_${rand}`;

            // Upsert carbon credit for today (replace if already exists for this sensor+date)
            await pool.query(
                `INSERT INTO Carbon_Credit
                 (credit_id, calculated_date, emission_value, allowed_limit, credit_amount, status)
                 VALUES (?, ?, ?, ?, ?, ?)
                 ON DUPLICATE KEY UPDATE
                   emission_value = VALUES(emission_value),
                   credit_amount  = VALUES(credit_amount),
                   status         = VALUES(status)`,
                [credit_id, today, todayTotal, DAILY_LIMIT, creditAmt, status]
            );

            // Link emission to credit (INSERT IGNORE avoids duplicate map entries)
            await pool.query(
                `INSERT IGNORE INTO Credit_Emission_Map (map_id, credit_id, emission_id)
                 VALUES (?, ?, ?)`,
                [map_id, credit_id, emission_id]
            );

            console.log(`💳 Credit | ${today} | ${status} | ${creditAmt.toFixed(4)} CC | total today: ${todayTotal.toFixed(4)} kg`);
        } catch (creditErr) {
            // Credit calc failure must not block the emission save
            console.warn('⚠️ Credit calculation failed (emission still saved):', creditErr.message);
        }

        // 3. Create alert if current reading exceeds hourly threshold
        try {
            const HOURLY_LIMIT = 1000; // kg/hr
            if (parseFloat(co2_value) > HOURLY_LIMIT) {
                const alert_id = `ALERT_${ts}_${rand}`;
                const severity = co2_value > HOURLY_LIMIT * 1.2 ? 'critical'
                               : co2_value > HOURLY_LIMIT * 1.1 ? 'high'
                               : 'medium';
                await pool.query(
                    `INSERT INTO Alert (alert_id, alert_type, threshold_value, alert_message, user_id, severity)
                     VALUES (?, 'threshold_exceeded', ?, ?, ?, ?)`,
                    [alert_id, HOURLY_LIMIT,
                     `CO2 emission exceeded threshold: ${parseFloat(co2_value).toFixed(4)} kg/hr (Limit: ${HOURLY_LIMIT} kg/hr)`,
                     user_id, severity]
                );
                console.log(`🚨 Alert created: ${severity} | ${co2_value} kg/hr`);
            }
        } catch (alertErr) {
            console.warn('⚠️ Alert creation failed (emission still saved):', alertErr.message);
        }

        res.status(201).json({ message: 'Emission recorded', emission_id });
    } catch (error) {
        console.error('Emission insert error:', error);
        res.status(500).json({ error: 'Failed to record emission' });
    }
});

// GET — PUBLIC, returns all organisation emissions (shared single-device access)
app.get('/api/emissions/all', async (req, res) => {
    try {
        const [emissions] = await pool.query(
            `SELECT
                ed.emission_id,
                ed.timestamp,
                ed.co2_value,
                ed.co2_ppm,
                ed.temperature,
                ed.humidity,
                ed.sensor_id
             FROM Emission_Data ed
             ORDER BY ed.timestamp DESC
             LIMIT 10000`
        );
        console.log(`📊 Fetched ${emissions.length} emission records`);
        res.json(emissions);
    } catch (error) {
        console.error('❌ Fetch all emissions error:', error);
        res.status(500).json({ error: 'Failed to fetch emissions' });
    }
});

// ==========================================
// AI PREDICTION ROUTES
// ==========================================

// PUBLIC — predictions loaded by predict_emissions.py script
app.get('/api/predictions', async (req, res) => {
    try {
        const [predictions] = await pool.query(
            `SELECT prediction_id, timestamp, predicted_co2, confidence, created_at
             FROM Emission_Predictions
             ORDER BY timestamp ASC
             LIMIT 24`
        );
        if (predictions.length === 0) return res.json([]);

        const enriched = predictions.map(p => ({
            ...p,
            hour:          new Date(p.timestamp).getHours(),
            day:           new Date(p.timestamp).toISOString().split('T')[0],
            predicted_co2: parseFloat(p.predicted_co2)
        }));

        console.log(`🔮 Served ${enriched.length} predictions`);
        res.json(enriched);
    } catch (error) {
        console.error('❌ Fetch predictions error:', error);
        res.status(500).json({ error: 'Failed to fetch predictions' });
    }
});

// PUBLIC — prediction statistics
app.get('/api/predictions/stats', async (req, res) => {
    try {
        const [stats] = await pool.query(
            'SELECT * FROM Prediction_Statistics ORDER BY created_at DESC LIMIT 1'
        );
        res.json(stats[0] || null);
    } catch (error) {
        res.status(500).json({ error: 'Failed to fetch prediction stats' });
    }
});

// ==========================================
// CARBON CREDIT ROUTES
// ==========================================

app.get('/api/credits', async (req, res) => {
    try {
        // Public — returns all org credits ordered by date, deduplicated by credit_id
        const [rows] = await pool.query(
            `SELECT DISTINCT
                cc.credit_id,
                cc.calculated_date,
                cc.emission_value,
                cc.allowed_limit,
                cc.credit_amount,
                cc.status
             FROM Carbon_Credit cc
             ORDER BY cc.calculated_date DESC
             LIMIT 100`
        );
        res.json(rows);
    } catch (error) {
        console.error('Fetch credits error:', error);
        res.status(500).json({ error: 'Failed to fetch credits' });
    }
});

// ==========================================
// ALERT ROUTES
// ==========================================

app.get('/api/alerts', authenticateToken, async (req, res) => {
    try {
        const [alerts] = await pool.query(
            'SELECT * FROM Alert WHERE user_id = ? ORDER BY created_at DESC LIMIT 50',
            [req.user.user_id]
        );
        res.json(alerts);
    } catch (error) {
        res.status(500).json({ error: 'Failed to fetch alerts' });
    }
});

app.patch('/api/alerts/:alert_id/read', authenticateToken, async (req, res) => {
    try {
        await pool.query(
            'UPDATE Alert SET is_read = TRUE WHERE alert_id = ? AND user_id = ?',
            [req.params.alert_id, req.user.user_id]
        );
        res.json({ message: 'Alert marked as read' });
    } catch (error) {
        res.status(500).json({ error: 'Failed to update alert' });
    }
});

// ==========================================
// DASHBOARD STATS
// ==========================================

app.get('/api/dashboard/stats', authenticateToken, async (req, res) => {
    try {
        const [[latest]] = await pool.query(
            `SELECT ed.co2_value, ed.co2_ppm, ed.temperature, ed.humidity, ed.timestamp
             FROM Emission_Data ed
             JOIN Sensor s ON ed.sensor_id = s.sensor_id
             WHERE s.user_id = ?
             ORDER BY ed.timestamp DESC LIMIT 1`,
            [req.user.user_id]
        );

        const [[credits]] = await pool.query(
            `SELECT COALESCE(SUM(cc.credit_amount), 0) as total
             FROM Carbon_Credit cc
             JOIN Credit_Emission_Map cem ON cc.credit_id    = cem.credit_id
             JOIN Emission_Data ed        ON cem.emission_id = ed.emission_id
             JOIN Sensor s                ON ed.sensor_id    = s.sensor_id
             WHERE s.user_id = ?`,
            [req.user.user_id]
        );

        const [[unread]] = await pool.query(
            'SELECT COUNT(*) as count FROM Alert WHERE user_id = ? AND is_read = FALSE',
            [req.user.user_id]
        );

        const sensor_id = await getUserSensorId(req.user.user_id);

        res.json({
            current_emission: latest?.co2_value  || 0,
            current_ppm:      latest?.co2_ppm    || 0,
            temperature:      latest?.temperature || 0,
            humidity:         latest?.humidity   || 0,
            last_reading:     latest?.timestamp  || null,
            total_credits:    credits?.total     || 0,
            unread_alerts:    unread?.count      || 0,
            sensor_id
        });
    } catch (error) {
        console.error('Dashboard stats error:', error);
        res.status(500).json({ error: 'Failed to fetch dashboard stats' });
    }
});

// ==========================================
// ADMIN — USER MANAGEMENT ROUTES
// ==========================================

// GET all users
app.get('/api/admin/users', authenticateToken, requireAdmin, async (req, res) => {
    try {
        const [users] = await pool.query(
            `SELECT user_id, name, email, role, is_active, created_at
             FROM User ORDER BY created_at DESC`
        );
        res.json(users);
    } catch (error) {
        console.error('Fetch users error:', error);
        res.status(500).json({ error: 'Failed to fetch users' });
    }
});

// PATCH — change a user's role
app.patch('/api/admin/users/:user_id/role', authenticateToken, requireAdmin, async (req, res) => {
    try {
        const { role } = req.body;
        const { user_id } = req.params;

        if (!['user', 'admin'].includes(role))
            return res.status(400).json({ error: 'Invalid role. Must be: user or admin' });

        if (parseInt(user_id) === req.user.user_id)
            return res.status(400).json({ error: 'You cannot change your own role' });

        await pool.query('UPDATE User SET role = ? WHERE user_id = ?', [role, user_id]);
        console.log(`👤 Admin ${req.user.email} changed user ${user_id} → ${role}`);
        res.json({ message: `User role updated to ${role}` });
    } catch (error) {
        console.error('Update role error:', error);
        res.status(500).json({ error: 'Failed to update role' });
    }
});

// PATCH — activate/deactivate a user
app.patch('/api/admin/users/:user_id/status', authenticateToken, requireAdmin, async (req, res) => {
    try {
        const { is_active } = req.body;
        const { user_id } = req.params;

        if (parseInt(user_id) === req.user.user_id)
            return res.status(400).json({ error: 'You cannot deactivate your own account' });

        await pool.query('UPDATE User SET is_active = ? WHERE user_id = ?', [is_active ? 1 : 0, user_id]);
        res.json({ message: `User ${is_active ? 'activated' : 'deactivated'}` });
    } catch (error) {
        res.status(500).json({ error: 'Failed to update user status' });
    }
});

// ==========================================
// START SERVER
// ==========================================
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`
╔═══════════════════════════════════════════╗
║  🌱 Carbon Credit API Server             ║
║  📡 Port  : ${PORT}                          ║
║  🔗 URL   : http://localhost:${PORT}         ║
║  🔐 Auth  : JWT 24h tokens               ║
║  👤 Roles : user / admin                 ║
║  📊 Data  : user-scoped isolation ON     ║
╚═══════════════════════════════════════════╝
    `);
});