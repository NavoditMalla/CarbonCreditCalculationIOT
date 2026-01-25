-- ========================================
-- CARBON CREDIT MONITORING DATABASE SCHEMA
-- Based on ERD and System Architecture
-- ========================================
SHOW TABLES;
SELECT * FROM User;
-- 1. USER TABLE
CREATE TABLE User (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'operator',
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    INDEX idx_email (email),
    INDEX idx_role (role)
);

-- 2. SENSOR TABLE
USE carbon_credit_db;
SHOW TABLES;
SELECT * FROM User;
CREATE TABLE Sensor (
    sensor_id VARCHAR(50) PRIMARY KEY,
    sensor_type VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    installation_date DATE,
    status VARCHAR(20) DEFAULT 'active',
    location VARCHAR(255),
    user_id INT NOT NULL,
    last_calibration DATE,
    calibration_interval_days INT DEFAULT 90,
    FOREIGN KEY (user_id) REFERENCES User(user_id) ON DELETE CASCADE,
    INDEX idx_user (user_id),
    INDEX idx_status (status)
);

-- 3. EMISSION_DATA TABLE
CREATE TABLE Emission_Data (
    emission_id VARCHAR(100) PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    co2_value FLOAT NOT NULL,
    pm25_value FLOAT,
    temperature FLOAT,
    humidity FLOAT,
    sensor_id VARCHAR(50) NOT NULL,
    alert_id VARCHAR(100),
    FOREIGN KEY (sensor_id) REFERENCES Sensor(sensor_id) ON DELETE CASCADE,
    INDEX idx_sensor_timestamp (sensor_id, timestamp),
    INDEX idx_timestamp (timestamp),
    INDEX idx_alert (alert_id)
);

-- 4. CARBON_CREDIT TABLE
CREATE TABLE Carbon_Credit (
    credit_id VARCHAR(100) PRIMARY KEY,
    report_id VARCHAR(100),
    calculated_date DATE NOT NULL,
    emission_value FLOAT NOT NULL,
    allowed_limit FLOAT NOT NULL,
    credit_amount FLOAT NOT NULL,
    status ENUM('earned', 'deficit', 'neutral') NOT NULL,
    INDEX idx_report (report_id),
    INDEX idx_date (calculated_date),
    INDEX idx_status (status)
);

-- 5. CREDIT_EMISSION_MAP TABLE (Many-to-Many relationship)
CREATE TABLE Credit_Emission_Map (
    map_id VARCHAR(100) PRIMARY KEY,
    credit_id VARCHAR(100) NOT NULL,
    emission_id VARCHAR(100) NOT NULL,
    weight_factor FLOAT DEFAULT 1.0,
    included_flag BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (credit_id) REFERENCES Carbon_Credit(credit_id) ON DELETE CASCADE,
    FOREIGN KEY (emission_id) REFERENCES Emission_Data(emission_id) ON DELETE CASCADE,
    INDEX idx_credit (credit_id),
    INDEX idx_emission (emission_id)
);

-- 6. ALERT TABLE
CREATE TABLE Alert (
    alert_id VARCHAR(100) PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    threshold_value FLOAT NOT NULL,
    alert_message TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE,
    user_id INT NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') DEFAULT 'medium',
    FOREIGN KEY (user_id) REFERENCES User(user_id) ON DELETE CASCADE,
    INDEX idx_user_unread (user_id, is_read),
    INDEX idx_created (created_at),
    INDEX idx_type (alert_type)
);

-- 7. REPORT TABLE
CREATE TABLE Report (
    report_id VARCHAR(100) PRIMARY KEY,
    report_type VARCHAR(50) NOT NULL,
    generated_date DATE NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_emission FLOAT,
    total_credits FLOAT,
    report_file_path VARCHAR(500),
    user_id INT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES User(user_id) ON DELETE CASCADE,
    INDEX idx_user_type (user_id, report_type),
    INDEX idx_dates (period_start, period_end)
);

-- 8. USER_REPORT_ACCESS TABLE (Many-to-Many relationship)
CREATE TABLE User_Report_Access (
    access_id VARCHAR(100) PRIMARY KEY,
    user_id INT NOT NULL,
    report_id VARCHAR(100) NOT NULL,
    view_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    access_type VARCHAR(50) DEFAULT 'view',
    FOREIGN KEY (user_id) REFERENCES User(user_id) ON DELETE CASCADE,
    FOREIGN KEY (report_id) REFERENCES Report(report_id) ON DELETE CASCADE,
    INDEX idx_user (user_id),
    INDEX idx_report (report_id)
);

-- ========================================
-- STORED PROCEDURES (Business Logic)
-- ========================================

-- Procedure: Calculate Carbon Credits
DELIMITER //
CREATE PROCEDURE calculate_carbon_credits(
    IN p_emission_id VARCHAR(100),
    IN p_allowed_limit FLOAT,
    OUT p_credit_amount FLOAT,
    OUT p_status VARCHAR(20)
)
BEGIN
    DECLARE v_emission_value FLOAT;
    DECLARE v_credit_id VARCHAR(100);
    
    -- Get emission value
    SELECT co2_value INTO v_emission_value 
    FROM Emission_Data 
    WHERE emission_id = p_emission_id;
    
    -- Calculate credit (1 credit = 1 ton CO2 reduced)
    SET p_credit_amount = (p_allowed_limit - v_emission_value) / 1000;
    
    -- Determine status
    IF p_credit_amount > 0 THEN
        SET p_status = 'earned';
    ELSEIF p_credit_amount < 0 THEN
        SET p_status = 'deficit';
    ELSE
        SET p_status = 'neutral';
    END IF;
    
    -- Generate credit ID
    SET v_credit_id = CONCAT('CC_', DATE_FORMAT(NOW(), '%Y%m%d'), '_', FLOOR(RAND() * 10000));
    
    -- Insert into Carbon_Credit table
    INSERT INTO Carbon_Credit (
        credit_id, 
        calculated_date, 
        emission_value, 
        allowed_limit, 
        credit_amount, 
        status
    ) VALUES (
        v_credit_id,
        CURDATE(),
        v_emission_value,
        p_allowed_limit,
        p_credit_amount,
        p_status
    );
    
    -- Link emission to credit
    INSERT INTO Credit_Emission_Map (map_id, credit_id, emission_id)
    VALUES (
        CONCAT('MAP_', v_credit_id),
        v_credit_id,
        p_emission_id
    );
END //
DELIMITER ;

-- Procedure: Check Emission Threshold and Trigger Alert
DELIMITER //
CREATE PROCEDURE check_emission_threshold(
    IN p_emission_id VARCHAR(100),
    IN p_threshold FLOAT
)
BEGIN
    DECLARE v_co2_value FLOAT;
    DECLARE v_sensor_id VARCHAR(50);
    DECLARE v_user_id INT;
    DECLARE v_alert_id VARCHAR(100);
    
    -- Get emission details
    SELECT e.co2_value, e.sensor_id, s.user_id
    INTO v_co2_value, v_sensor_id, v_user_id
    FROM Emission_Data e
    JOIN Sensor s ON e.sensor_id = s.sensor_id
    WHERE e.emission_id = p_emission_id;
    
    -- Check if threshold exceeded
    IF v_co2_value > p_threshold THEN
        SET v_alert_id = CONCAT('ALERT_', DATE_FORMAT(NOW(), '%Y%m%d%H%i%s'), '_', FLOOR(RAND() * 1000));
        
        INSERT INTO Alert (
            alert_id,
            alert_type,
            threshold_value,
            alert_message,
            user_id,
            severity
        ) VALUES (
            v_alert_id,
            'threshold_exceeded',
            p_threshold,
            CONCAT('CO2 emission exceeded threshold: ', v_co2_value, ' kg/hour (Limit: ', p_threshold, ' kg/hour)'),
            v_user_id,
            CASE 
                WHEN v_co2_value > p_threshold * 1.2 THEN 'critical'
                WHEN v_co2_value > p_threshold * 1.1 THEN 'high'
                ELSE 'medium'
            END
        );
        
        -- Update emission data with alert reference
        UPDATE Emission_Data 
        SET alert_id = v_alert_id 
        WHERE emission_id = p_emission_id;
    END IF;
END //
DELIMITER ;

-- Procedure: Generate Report
DELIMITER //
CREATE PROCEDURE generate_report(
    IN p_user_id INT,
    IN p_report_type VARCHAR(50),
    IN p_start_date DATE,
    IN p_end_date DATE,
    OUT p_report_id VARCHAR(100)
)
BEGIN
    DECLARE v_total_emission FLOAT;
    DECLARE v_total_credits FLOAT;
    
    -- Generate report ID
    SET p_report_id = CONCAT('RPT_', DATE_FORMAT(NOW(), '%Y%m%d%H%i%s'), '_', p_user_id);
    
    -- Calculate total emissions
    SELECT SUM(ed.co2_value) INTO v_total_emission
    FROM Emission_Data ed
    JOIN Sensor s ON ed.sensor_id = s.sensor_id
    WHERE s.user_id = p_user_id
    AND DATE(ed.timestamp) BETWEEN p_start_date AND p_end_date;
    
    -- Calculate total credits
    SELECT SUM(cc.credit_amount) INTO v_total_credits
    FROM Carbon_Credit cc
    JOIN Credit_Emission_Map cem ON cc.credit_id = cem.credit_id
    JOIN Emission_Data ed ON cem.emission_id = ed.emission_id
    JOIN Sensor s ON ed.sensor_id = s.sensor_id
    WHERE s.user_id = p_user_id
    AND cc.calculated_date BETWEEN p_start_date AND p_end_date;
    
    -- Insert report
    INSERT INTO Report (
        report_id,
        report_type,
        generated_date,
        period_start,
        period_end,
        total_emission,
        total_credits,
        user_id
    ) VALUES (
        p_report_id,
        p_report_type,
        CURDATE(),
        p_start_date,
        p_end_date,
        COALESCE(v_total_emission, 0),
        COALESCE(v_total_credits, 0),
        p_user_id
    );
    
    -- Grant access to user
    INSERT INTO User_Report_Access (access_id, user_id, report_id, access_type)
    VALUES (
        CONCAT('ACCESS_', p_report_id),
        p_user_id,
        p_report_id,
        'owner'
    );
END //
DELIMITER ;

-- ========================================
-- TRIGGERS
-- ========================================

-- Trigger: Auto-calculate credits after emission insert
DELIMITER //
CREATE TRIGGER after_emission_insert
AFTER INSERT ON Emission_Data
FOR EACH ROW
BEGIN
    DECLARE v_threshold FLOAT DEFAULT 1000;
    
    -- Check threshold
    CALL check_emission_threshold(NEW.emission_id, v_threshold);
    
    -- Calculate credits (only if daily limit not exceeded)
    IF NEW.co2_value <= v_threshold THEN
        CALL calculate_carbon_credits(NEW.emission_id, v_threshold, @credit_amt, @status);
    END IF;
END //
DELIMITER ;

-- ========================================
-- VIEWS (For Dashboard Queries)
-- ========================================

-- View: Real-time Emission Summary
CREATE VIEW v_realtime_emissions AS
SELECT 
    s.sensor_id,
    s.sensor_type,
    s.location,
    ed.emission_id,
    ed.timestamp,
    ed.co2_value,
    ed.temperature,
    ed.humidity,
    u.user_id,
    u.name as company_name,
    CASE 
        WHEN ed.co2_value > 1000 THEN 'critical'
        WHEN ed.co2_value > 800 THEN 'warning'
        ELSE 'normal'
    END as emission_status
FROM Emission_Data ed
JOIN Sensor s ON ed.sensor_id = s.sensor_id
JOIN User u ON s.user_id = u.user_id
WHERE ed.timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY ed.timestamp DESC;

-- View: Carbon Credit Summary
CREATE VIEW v_credit_summary AS
SELECT 
    u.user_id,
    u.name as company_name,
    DATE_FORMAT(cc.calculated_date, '%Y-%m') as month,
    SUM(CASE WHEN cc.status = 'earned' THEN cc.credit_amount ELSE 0 END) as credits_earned,
    SUM(CASE WHEN cc.status = 'deficit' THEN ABS(cc.credit_amount) ELSE 0 END) as credits_deficit,
    SUM(cc.credit_amount) as net_credits,
    COUNT(*) as total_calculations
FROM Carbon_Credit cc
JOIN Credit_Emission_Map cem ON cc.credit_id = cem.credit_id
JOIN Emission_Data ed ON cem.emission_id = ed.emission_id
JOIN Sensor s ON ed.sensor_id = s.sensor_id
JOIN User u ON s.user_id = u.user_id
GROUP BY u.user_id, u.name, DATE_FORMAT(cc.calculated_date, '%Y-%m');

-- View: Active Alerts
CREATE VIEW v_active_alerts AS
SELECT 
    a.alert_id,
    a.alert_type,
    a.alert_message,
    a.threshold_value,
    a.severity,
    a.created_at,
    u.user_id,
    u.name as company_name,
    u.email
FROM Alert a
JOIN User u ON a.user_id = u.user_id
WHERE a.is_read = FALSE
ORDER BY a.created_at DESC, a.severity DESC;

-- ========================================
-- SAMPLE DATA INSERTION
-- ========================================

-- Insert Users
INSERT INTO User (name, email, role, password_hash) VALUES
('Demo Industries Ltd.', 'demo@industry.com', 'admin', '$2b$10$demo_hash_placeholder'),
('Green Tech Manufacturing', 'admin@greentech.com', 'admin', '$2b$10$demo_hash_placeholder'),
('EcoFactory Corp', 'operator@ecofactory.com', 'operator', '$2b$10$demo_hash_placeholder');

-- Insert Sensors
INSERT INTO Sensor (sensor_id, sensor_type, model, installation_date, status, location, user_id) VALUES
('SENSOR_001', 'CO2', 'NDIR-CO2-500', '2024-01-15', 'active', 'Main Chimney', 1),
('SENSOR_002', 'CO2', 'NDIR-CO2-500', '2024-01-15', 'active', 'Secondary Vent', 1),
('SENSOR_003', 'CO2', 'NDIR-CO2-Pro', '2024-02-01', 'active', 'Quality Control', 1),
('SENSOR_004', 'CO2', 'NDIR-CO2-500', '2024-01-20', 'active', 'Production Line A', 2);

-- Insert Sample Emission Data
INSERT INTO Emission_Data (emission_id, timestamp, co2_value, pm25_value, temperature, humidity, sensor_id) VALUES
('EM_2024060101', '2024-06-01 08:00:00', 850, 35.2, 28.5, 65.0, 'SENSOR_001'),
('EM_2024060102', '2024-06-01 12:00:00', 920, 42.1, 32.1, 58.3, 'SENSOR_001'),
('EM_2024060103', '2024-06-01 16:00:00', 780, 28.7, 30.2, 60.5, 'SENSOR_001'),
('EM_2024060201', '2024-06-02 08:00:00', 1050, 55.3, 29.8, 62.0, 'SENSOR_001'),
('EM_2024060202', '2024-06-02 12:00:00', 1150, 68.2, 33.5, 55.8, 'SENSOR_001');

-- ========================================
-- INDEXES FOR PERFORMANCE
-- ========================================

CREATE INDEX idx_emission_sensor_time ON Emission_Data(sensor_id, timestamp);
CREATE INDEX idx_credit_status ON Carbon_Credit(status, calculated_date);
CREATE INDEX idx_alert_user_created ON Alert(user_id, created_at);
CREATE INDEX idx_report_user_dates ON Report(user_id, period_start, period_end);