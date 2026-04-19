# ==========================================
# AI CARBON EMISSION PREDICTION MODEL
# Improved Version - Better accuracy & variety
# ==========================================

import pandas as pd
import numpy as np
import mysql.connector
from sklearn.model_selection import train_test_split, cross_val_score, TimeSeriesSplit
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import joblib
import warnings
import os
warnings.filterwarnings('ignore')

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'nothinghere',
    'database': 'carbon_credit_db'
}

# ==========================================
# 1. DATABASE CONNECTION & DATA LOADING
# ==========================================

def load_emission_data_from_db():
    """Load emission data from MySQL database"""
    print("📊 Loading data from database...")
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        query = """
            SELECT 
                emission_id,
                timestamp,
                co2_value,
                co2_ppm,
                temperature,
                humidity,
                sensor_id
            FROM Emission_Data
            ORDER BY timestamp ASC
        """
        df = pd.read_sql(query, connection)
        connection.close()
        print(f"✅ Loaded {len(df)} records from database\n")
        return df
    except Exception as e:
        # Fallback without co2_ppm if column doesn't exist
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            query = """
                SELECT emission_id, timestamp, co2_value,
                       temperature, humidity, sensor_id
                FROM Emission_Data ORDER BY timestamp ASC
            """
            df = pd.read_sql(query, connection)
            connection.close()
            df['co2_ppm'] = None
            print(f"✅ Loaded {len(df)} records (no co2_ppm column)\n")
            return df
        except Exception as e2:
            print(f"❌ Error loading data: {e2}")
            return None

# ==========================================
# 2. FEATURE ENGINEERING (IMPROVED)
# ==========================================

def engineer_features(df):
    """Create rich features for machine learning"""
    print("🔧 Engineering features...")

    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)

    # Remove duplicates
    df = df.drop_duplicates(subset='timestamp').reset_index(drop=True)

    # ---- Time features ----
    df['hour']         = df['timestamp'].dt.hour
    df['minute']       = df['timestamp'].dt.minute
    df['day_of_week']  = df['timestamp'].dt.dayofweek
    df['day_of_month'] = df['timestamp'].dt.day
    df['month']        = df['timestamp'].dt.month
    df['is_weekend']   = df['day_of_week'].isin([5, 6]).astype(int)

    # Cyclical encoding — prevents model treating hour 23 as far from hour 0
    df['hour_sin']        = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos']        = np.cos(2 * np.pi * df['hour'] / 24)
    df['day_of_week_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['day_of_week_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)

    # ---- Lag features (past readings) ----
    for lag in [1, 2, 3, 6, 12]:
        df[f'co2_lag_{lag}'] = df['co2_value'].shift(lag)

    # ---- Rolling statistics ----
    for window in [3, 6, 12, 24]:
        df[f'co2_rolling_mean_{window}'] = df['co2_value'].rolling(window=window, min_periods=1).mean()
        df[f'co2_rolling_std_{window}']  = df['co2_value'].rolling(window=window, min_periods=1).std().fillna(0)

    df['co2_rolling_min_6']  = df['co2_value'].rolling(window=6,  min_periods=1).min()
    df['co2_rolling_max_6']  = df['co2_value'].rolling(window=6,  min_periods=1).max()
    df['co2_rolling_min_24'] = df['co2_value'].rolling(window=24, min_periods=1).min()
    df['co2_rolling_max_24'] = df['co2_value'].rolling(window=24, min_periods=1).max()

    # ---- Rate of change ----
    df['co2_diff_1'] = df['co2_value'].diff(1).fillna(0)
    df['co2_diff_3'] = df['co2_value'].diff(3).fillna(0)

    # ---- Environmental features ----
    df['temperature']            = df['temperature'].fillna(df['temperature'].median())
    df['humidity']               = df['humidity'].fillna(df['humidity'].median())
    df['temp_humidity_interact'] = df['temperature'] * df['humidity']
    df['temp_squared']           = df['temperature'] ** 2

    # ---- Time trend ----
    df['hours_since_start'] = (df['timestamp'] - df['timestamp'].min()).dt.total_seconds() / 3600

    # ---- co2_ppm features (if available) ----
    if 'co2_ppm' in df.columns and df['co2_ppm'].notna().sum() > 10:
        df['co2_ppm'] = df['co2_ppm'].fillna(df['co2_ppm'].median())
        df['ppm_lag_1'] = df['co2_ppm'].shift(1)
        df['ppm_rolling_mean_6'] = df['co2_ppm'].rolling(window=6, min_periods=1).mean()

    df = df.dropna()

    print(f"✅ Created {len(df.columns)} features")
    print(f"📊 Dataset shape after feature engineering: {df.shape}\n")
    return df

# ==========================================
# 3. MODEL TRAINING (IMPROVED)
# ==========================================

def train_prediction_model(df):
    """Train and evaluate ML models with proper time-series validation"""
    print("🤖 Training AI prediction models...\n")

    base_feature_columns = [
        'hour_sin', 'hour_cos', 'day_of_week_sin', 'day_of_week_cos',
        'day_of_month', 'month', 'is_weekend',
        'temperature', 'humidity', 'temp_humidity_interact', 'temp_squared',
        'co2_lag_1', 'co2_lag_2', 'co2_lag_3', 'co2_lag_6', 'co2_lag_12',
        'co2_rolling_mean_3', 'co2_rolling_mean_6', 'co2_rolling_mean_12', 'co2_rolling_mean_24',
        'co2_rolling_std_3', 'co2_rolling_std_6',
        'co2_rolling_min_6', 'co2_rolling_max_6',
        'co2_rolling_min_24', 'co2_rolling_max_24',
        'co2_diff_1', 'co2_diff_3',
        'hours_since_start'
    ]

    # Add ppm features if available
    ppm_cols = [c for c in ['ppm_lag_1', 'ppm_rolling_mean_6'] if c in df.columns]
    feature_columns = base_feature_columns + ppm_cols

    # Only keep columns that exist
    feature_columns = [c for c in feature_columns if c in df.columns]

    X = df[feature_columns]
    y = df['co2_value']

    # Time-series split — no data leakage (no shuffle)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"   Training samples : {len(X_train)}")
    print(f"   Test samples     : {len(X_test)}")
    print(f"   Features used    : {len(feature_columns)}\n")

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    models = {
        'Ridge Regression': Ridge(alpha=1.0),
        'Random Forest':    RandomForestRegressor(
                                n_estimators=200,
                                max_depth=10,
                                min_samples_leaf=5,
                                random_state=42,
                                n_jobs=-1
                            ),
        'Gradient Boosting': GradientBoostingRegressor(
                                n_estimators=200,
                                max_depth=4,
                                learning_rate=0.05,
                                subsample=0.8,
                                random_state=42
                            ),
    }

    results = {}
    tscv = TimeSeriesSplit(n_splits=5)

    for name, model in models.items():
        print(f"Training {name}...")
        model.fit(X_train_scaled, y_train)
        y_pred = model.predict(X_test_scaled)

        mae  = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2   = r2_score(y_test, y_pred)

        # Cross-validation with time-series splits
        cv_scores = cross_val_score(
            model, X_train_scaled, y_train,
            cv=tscv, scoring='neg_root_mean_squared_error', n_jobs=-1
        )
        cv_rmse_mean = -cv_scores.mean()
        cv_rmse_std  = cv_scores.std()

        results[name] = {
            'model':       model,
            'mae':         mae,
            'rmse':        rmse,
            'r2':          r2,
            'cv_rmse':     cv_rmse_mean,
            'cv_rmse_std': cv_rmse_std,
            'predictions': y_pred
        }

        print(f"  Test  → MAE: {mae:.4f}  RMSE: {rmse:.4f}  R²: {r2:.4f}")
        print(f"  CV(5) → RMSE: {cv_rmse_mean:.4f} ± {cv_rmse_std:.4f}\n")

    # Choose best model by CV RMSE (more honest than test RMSE)
    best_model_name = min(results.keys(), key=lambda k: results[k]['cv_rmse'])
    best_model = results[best_model_name]['model']

    print(f"🏆 Best Model (by CV RMSE): {best_model_name}")
    print(f"   Test RMSE : {results[best_model_name]['rmse']:.4f}")
    print(f"   Test R²   : {results[best_model_name]['r2']:.4f}")
    print(f"   CV RMSE   : {results[best_model_name]['cv_rmse']:.4f} ± {results[best_model_name]['cv_rmse_std']:.4f}\n")

    # Feature importance (for tree models)
    if hasattr(best_model, 'feature_importances_'):
        importances = pd.Series(best_model.feature_importances_, index=feature_columns)
        top10 = importances.nlargest(10)
        print("📌 Top 10 most important features:")
        for feat, imp in top10.items():
            bar = '█' * int(imp * 100)
            print(f"   {feat:<35} {bar} {imp:.4f}")
        print()

    os.makedirs('models', exist_ok=True)
    joblib.dump(best_model, 'models/emission_predictor.pkl')
    joblib.dump(scaler,     'models/scaler.pkl')
    joblib.dump(feature_columns, 'models/feature_columns.pkl')
    print("✅ Models saved to 'models/' directory\n")

    return best_model, scaler, feature_columns, results, X_test, y_test

# ==========================================
# 4. FUTURE PREDICTIONS (IMPROVED)
# ==========================================

def predict_future_emissions(model, scaler, feature_columns, df, hours_ahead=24):
    """Predict emissions for next N hours with realistic variation"""
    print(f"🔮 Predicting emissions for next {hours_ahead} hours...\n")

    predictions   = []
    recent_values = list(df['co2_value'].tail(24))  # keep a rolling window
    last_row      = df.iloc[-1].copy()
    last_time     = last_row['timestamp']

    # Calculate recent stats for realistic bounds
    recent_mean  = np.mean(recent_values)
    recent_std   = max(np.std(recent_values), 0.005)  # floor std so predictions vary
    recent_trend = np.polyfit(range(len(recent_values)), recent_values, 1)[0]

    for i in range(hours_ahead):
        future_time = last_time + timedelta(hours=i + 1)

        # Time features
        hour        = future_time.hour
        dow         = future_time.dayofweek
        hour_sin    = np.sin(2 * np.pi * hour / 24)
        hour_cos    = np.cos(2 * np.pi * hour / 24)
        dow_sin     = np.sin(2 * np.pi * dow / 7)
        dow_cos     = np.cos(2 * np.pi * dow / 7)
        is_weekend  = int(dow in [5, 6])
        dom         = future_time.day
        month       = future_time.month

        # Environmental (carry forward from last real reading)
        temperature = last_row['temperature']
        humidity    = last_row['humidity']

        # Lag values from rolling window of predictions + real history
        window = recent_values[-24:]
        co2_lag_1  = window[-1]  if len(window) >= 1  else recent_mean
        co2_lag_2  = window[-2]  if len(window) >= 2  else recent_mean
        co2_lag_3  = window[-3]  if len(window) >= 3  else recent_mean
        co2_lag_6  = window[-6]  if len(window) >= 6  else recent_mean
        co2_lag_12 = window[-12] if len(window) >= 12 else recent_mean

        # Rolling stats on expanding window
        co2_rolling_mean_3  = np.mean(window[-3:])  if len(window) >= 3  else recent_mean
        co2_rolling_mean_6  = np.mean(window[-6:])  if len(window) >= 6  else recent_mean
        co2_rolling_mean_12 = np.mean(window[-12:]) if len(window) >= 12 else recent_mean
        co2_rolling_mean_24 = np.mean(window[-24:]) if len(window) >= 24 else recent_mean
        co2_rolling_std_3   = np.std(window[-3:])   if len(window) >= 3  else recent_std
        co2_rolling_std_6   = np.std(window[-6:])   if len(window) >= 6  else recent_std
        co2_rolling_min_6   = np.min(window[-6:])   if len(window) >= 6  else recent_mean
        co2_rolling_max_6   = np.max(window[-6:])   if len(window) >= 6  else recent_mean
        co2_rolling_min_24  = np.min(window[-24:])  if len(window) >= 24 else recent_mean
        co2_rolling_max_24  = np.max(window[-24:])  if len(window) >= 24 else recent_mean
        co2_diff_1 = (window[-1] - window[-2]) if len(window) >= 2 else 0
        co2_diff_3 = (window[-1] - window[-4]) if len(window) >= 4 else 0

        hours_since_start = last_row['hours_since_start'] + i + 1

        feature_map = {
            'hour_sin':             hour_sin,
            'hour_cos':             hour_cos,
            'day_of_week_sin':      dow_sin,
            'day_of_week_cos':      dow_cos,
            'day_of_month':         dom,
            'month':                month,
            'is_weekend':           is_weekend,
            'temperature':          temperature,
            'humidity':             humidity,
            'temp_humidity_interact': temperature * humidity,
            'temp_squared':         temperature ** 2,
            'co2_lag_1':            co2_lag_1,
            'co2_lag_2':            co2_lag_2,
            'co2_lag_3':            co2_lag_3,
            'co2_lag_6':            co2_lag_6,
            'co2_lag_12':           co2_lag_12,
            'co2_rolling_mean_3':   co2_rolling_mean_3,
            'co2_rolling_mean_6':   co2_rolling_mean_6,
            'co2_rolling_mean_12':  co2_rolling_mean_12,
            'co2_rolling_mean_24':  co2_rolling_mean_24,
            'co2_rolling_std_3':    co2_rolling_std_3,
            'co2_rolling_std_6':    co2_rolling_std_6,
            'co2_rolling_min_6':    co2_rolling_min_6,
            'co2_rolling_max_6':    co2_rolling_max_6,
            'co2_rolling_min_24':   co2_rolling_min_24,
            'co2_rolling_max_24':   co2_rolling_max_24,
            'co2_diff_1':           co2_diff_1,
            'co2_diff_3':           co2_diff_3,
            'hours_since_start':    hours_since_start,
            'ppm_lag_1':            co2_lag_1 / 0.00184 if 'ppm_lag_1' in feature_columns else 0,
            'ppm_rolling_mean_6':   co2_rolling_mean_6 / 0.00184 if 'ppm_rolling_mean_6' in feature_columns else 0,
        }

        features_arr = np.array([[feature_map.get(c, 0) for c in feature_columns]])
        features_scaled = scaler.transform(features_arr)
        predicted_co2 = model.predict(features_scaled)[0]

        # Ensure prediction stays physically reasonable
        predicted_co2 = max(0, predicted_co2)

        # Update rolling window with this prediction
        recent_values.append(predicted_co2)

        predictions.append({
            'timestamp':    future_time.strftime('%Y-%m-%d %H:%M:%S'),
            'hour':         hour,
            'day':          future_time.strftime('%Y-%m-%d'),
            'predicted_co2': round(predicted_co2, 4),
            'confidence':   'high' if i < 6 else 'medium' if i < 12 else 'low'
        })

    return pd.DataFrame(predictions)

# ==========================================
# 5. SAVE TO DATABASE
# ==========================================

def save_predictions_to_db(predictions_df):
    """Save predictions to database"""
    print("💾 Saving predictions to database...")
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Emission_Predictions (
                prediction_id VARCHAR(100) PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                predicted_co2 FLOAT NOT NULL,
                confidence VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_timestamp (timestamp)
            )
        """)
        cursor.execute("DELETE FROM Emission_Predictions")
        for _, row in predictions_df.iterrows():
            ts  = pd.to_datetime(row['timestamp'])
            pid = f"PRED_{int(ts.timestamp() * 1000)}"
            cursor.execute(
                "INSERT INTO Emission_Predictions (prediction_id, timestamp, predicted_co2, confidence) VALUES (%s, %s, %s, %s)",
                (pid, row['timestamp'], row['predicted_co2'], row['confidence'])
            )
        connection.commit()
        cursor.close()
        connection.close()
        print(f"✅ Saved {len(predictions_df)} predictions to database\n")
    except Exception as e:
        print(f"❌ Error saving predictions: {e}\n")

# ==========================================
# 6. CALCULATE PREDICTION STATISTICS
# ==========================================

def calculate_prediction_stats(predictions_df):
    vals = predictions_df['predicted_co2']
    return {
        'total_hours':            len(predictions_df),
        'avg_predicted':          float(vals.mean()),
        'max_predicted':          float(vals.max()),
        'min_predicted':          float(vals.min()),
        'std_predicted':          float(vals.std()),
        'high_confidence_hours':  len(predictions_df[predictions_df['confidence'] == 'high']),
        'medium_confidence_hours':len(predictions_df[predictions_df['confidence'] == 'medium']),
        'low_confidence_hours':   len(predictions_df[predictions_df['confidence'] == 'low']),
        'hours_over_1000':        len(predictions_df[predictions_df['predicted_co2'] > 1000]),
        'forecast_start':         predictions_df['timestamp'].iloc[0],
        'forecast_end':           predictions_df['timestamp'].iloc[-1],
    }

# ==========================================
# 7. SAVE STATISTICS TO DATABASE
# ==========================================

def save_prediction_stats_to_db(stats):
    print("💾 Saving prediction statistics...")
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Prediction_Statistics (
                stat_id INT PRIMARY KEY AUTO_INCREMENT,
                total_hours INT, avg_predicted FLOAT, max_predicted FLOAT,
                min_predicted FLOAT, std_predicted FLOAT,
                high_confidence_hours INT, medium_confidence_hours INT,
                low_confidence_hours INT, hours_over_1000 INT,
                forecast_start DATETIME, forecast_end DATETIME,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("DELETE FROM Prediction_Statistics")
        cursor.execute("""
            INSERT INTO Prediction_Statistics
            (total_hours, avg_predicted, max_predicted, min_predicted, std_predicted,
             high_confidence_hours, medium_confidence_hours, low_confidence_hours,
             hours_over_1000, forecast_start, forecast_end)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            stats['total_hours'], stats['avg_predicted'], stats['max_predicted'],
            stats['min_predicted'], stats['std_predicted'],
            stats['high_confidence_hours'], stats['medium_confidence_hours'],
            stats['low_confidence_hours'], stats['hours_over_1000'],
            stats['forecast_start'], stats['forecast_end']
        ))
        connection.commit()
        cursor.close()
        connection.close()
        print("✅ Statistics saved to database\n")
    except Exception as e:
        print(f"❌ Error saving statistics: {e}\n")

# ==========================================
# 8. VISUALIZATION (IMPROVED)
# ==========================================

def visualize_predictions(df, predictions_df, results, y_test):
    print("📊 Creating visualizations...\n")

    predictions_df = predictions_df.copy()
    predictions_df['timestamp_dt'] = pd.to_datetime(predictions_df['timestamp'])

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle('Carbon Emission Prediction Analysis', fontsize=16, fontweight='bold')

    # 1. Historical vs Predicted
    ax1 = axes[0, 0]
    recent = df.tail(48)
    ax1.plot(recent['timestamp'], recent['co2_value'],
             label='Historical (last 48)', linewidth=2, color='steelblue')
    colors_conf = {'high': 'green', 'medium': 'orange', 'low': 'red'}
    for conf, color in colors_conf.items():
        subset = predictions_df[predictions_df['confidence'] == conf]
        ax1.plot(subset['timestamp_dt'], subset['predicted_co2'],
                 marker='o', markersize=4, linewidth=2,
                 linestyle='--', color=color, label=f'Predicted ({conf})')
    ax1.axhline(y=1000, color='red', linestyle=':', label='Emission Limit', alpha=0.6)
    ax1.set_xlabel('Time')
    ax1.set_ylabel('CO₂ (kg/hour)')
    ax1.set_title('Historical vs 24h Forecast')
    ax1.legend(fontsize=7)
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)

    # 2. Model comparison bar chart
    ax2 = axes[0, 1]
    model_names = list(results.keys())
    rmse_vals   = [results[m]['rmse']    for m in model_names]
    r2_vals     = [results[m]['r2']      for m in model_names]
    cv_vals     = [results[m]['cv_rmse'] for m in model_names]
    x = np.arange(len(model_names))
    w = 0.25
    ax2.bar(x - w, rmse_vals, w, label='Test RMSE',  color='steelblue', alpha=0.8)
    ax2.bar(x,     cv_vals,   w, label='CV RMSE',    color='darkorange', alpha=0.8)
    ax2.bar(x + w, r2_vals,   w, label='R² Score',   color='seagreen',  alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels([m.replace(' ', '\n') for m in model_names], fontsize=8)
    ax2.set_title('Model Performance Comparison')
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3, axis='y')

    # 3. Actual vs Predicted scatter (best model)
    best_name = min(results.keys(), key=lambda k: results[k]['cv_rmse'])
    y_pred_best = results[best_name]['predictions']
    ax3 = axes[0, 2]
    ax3.scatter(y_test, y_pred_best, alpha=0.4, s=20, color='steelblue')
    mn, mx = min(y_test.min(), y_pred_best.min()), max(y_test.max(), y_pred_best.max())
    ax3.plot([mn, mx], [mn, mx], 'r--', lw=2, label='Perfect fit')
    ax3.set_xlabel('Actual CO₂ (kg/hr)')
    ax3.set_ylabel('Predicted CO₂ (kg/hr)')
    ax3.set_title(f'Actual vs Predicted\n({best_name})')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    # 4. Residuals
    ax4 = axes[1, 0]
    residuals = np.array(y_test) - y_pred_best
    ax4.scatter(y_pred_best, residuals, alpha=0.4, s=20, color='darkorange')
    ax4.axhline(0, color='red', linestyle='--', lw=2)
    ax4.set_xlabel('Predicted CO₂ (kg/hr)')
    ax4.set_ylabel('Residual (Actual − Predicted)')
    ax4.set_title('Residual Plot')
    ax4.grid(True, alpha=0.3)

    # 5. Error distribution
    ax5 = axes[1, 1]
    ax5.hist(residuals, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
    ax5.axvline(0,             color='red',    linestyle='--', lw=2, label='Zero error')
    ax5.axvline(residuals.mean(), color='orange', linestyle='--', lw=2, label=f'Mean={residuals.mean():.4f}')
    ax5.set_xlabel('Prediction Error')
    ax5.set_ylabel('Frequency')
    ax5.set_title('Error Distribution')
    ax5.legend(fontsize=8)
    ax5.grid(True, alpha=0.3)

    # 6. 24h forecast line with confidence shading
    ax6 = axes[1, 2]
    ts   = predictions_df['timestamp_dt']
    vals = predictions_df['predicted_co2']
    std_val = vals.std() if vals.std() > 0 else 0.005

    for conf, color, label, width in [('high','green','High (±1σ)',1),
                                       ('medium','orange','Medium (±2σ)',2),
                                       ('low','red','Low (±3σ)',3)]:
        sub = predictions_df[predictions_df['confidence'] == conf]
        if sub.empty: continue
        ax6.plot(sub['timestamp_dt'], sub['predicted_co2'], color=color, linewidth=2, label=label)
        ax6.fill_between(sub['timestamp_dt'],
                         sub['predicted_co2'] - width * std_val,
                         sub['predicted_co2'] + width * std_val,
                         color=color, alpha=0.12)

    ax6.axhline(y=1000, color='red', linestyle=':', alpha=0.6, label='Limit 1000')
    ax6.set_xlabel('Time')
    ax6.set_ylabel('Predicted CO₂ (kg/hr)')
    ax6.set_title('24-Hour Forecast with Confidence Bands')
    ax6.legend(fontsize=7)
    ax6.grid(True, alpha=0.3)
    ax6.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig('emission_predictions.png', dpi=300, bbox_inches='tight')
    print("✅ Visualization saved as 'emission_predictions.png'\n")
    return fig

# ==========================================
# 9. GENERATE REPORT
# ==========================================

def generate_prediction_report(predictions_df, stats, results):
    print("=" * 60)
    print("📋 EMISSION PREDICTION REPORT")
    print("=" * 60)
    print(f"\n📅 Forecast: {stats['forecast_start']}  →  {stats['forecast_end']}")
    print(f"⏱️  Hours   : {stats['total_hours']}")
    print(f"\n📊 PREDICTIONS SUMMARY:")
    print(f"   Average : {stats['avg_predicted']:.4f} kg/hour")
    print(f"   Maximum : {stats['max_predicted']:.4f} kg/hour")
    print(f"   Minimum : {stats['min_predicted']:.4f} kg/hour")
    print(f"   Std Dev : {stats['std_predicted']:.4f}")
    print(f"\n📈 MODEL PERFORMANCE:")
    for name, r in results.items():
        print(f"   {name:<22} RMSE={r['rmse']:.4f}  R²={r['r2']:.4f}  CV-RMSE={r['cv_rmse']:.4f}")
    print(f"\n⚠️  ALERT FORECAST:")
    if stats['hours_over_1000'] > 0:
        print(f"   🚨 {stats['hours_over_1000']} hours predicted to EXCEED limit (1000 kg/hour)")
    else:
        print(f"   ✅ All predictions within safe limits")
    print(f"\n🎯 CONFIDENCE BREAKDOWN:")
    print(f"   High   (0–6h)  : {stats['high_confidence_hours']} hours")
    print(f"   Medium (6–12h) : {stats['medium_confidence_hours']} hours")
    print(f"   Low    (12–24h): {stats['low_confidence_hours']} hours")
    print("\n" + "=" * 60 + "\n")

# ==========================================
# 10. MAIN EXECUTION
# ==========================================

def main():
    print("\n" + "=" * 60)
    print("🤖 AI CARBON EMISSION PREDICTION SYSTEM")
    print("=" * 60 + "\n")

    df = load_emission_data_from_db()
    if df is None or len(df) < 30:
        print("❌ Not enough data. Need at least 30 records.")
        print("💡 Keep running serial-bridge.js to collect more data.")
        return

    df = engineer_features(df)
    best_model, scaler, feature_columns, results, X_test, y_test = train_prediction_model(df)
    predictions_df = predict_future_emissions(best_model, scaler, feature_columns, df, hours_ahead=24)
    stats = calculate_prediction_stats(predictions_df)
    generate_prediction_report(predictions_df, stats, results)
    visualize_predictions(df, predictions_df, results, y_test)
    save_predictions_to_db(predictions_df)
    save_prediction_stats_to_db(stats)

    predictions_export = predictions_df.drop('timestamp_dt', axis=1, errors='ignore')
    predictions_export.to_csv('future_predictions.csv', index=False)
    print("✅ Predictions exported to 'future_predictions.csv'")

    print("\n🎉 PREDICTION COMPLETE!")
    print("\n📌 Next Steps:")
    print("   1. Check 'emission_predictions.png' for visualizations")
    print("   2. View 'future_predictions.csv' for detailed forecast")
    print("   3. Predictions saved to database for dashboard display")
    print("   4. Refresh your dashboard to see AI predictions\n")

if __name__ == "__main__":
    main()