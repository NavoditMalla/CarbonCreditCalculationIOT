# ==========================================
# AI CARBON EMISSION PREDICTION MODEL
# Updated with Dashboard Integration
# ==========================================

import pandas as pd
import numpy as np
import mysql.connector
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import joblib
import warnings
import json
warnings.filterwarnings('ignore')

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'nothinghere',  # ← UPDATE THIS
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
        print(f"❌ Error loading data: {e}")
        return None

# ==========================================
# 2. FEATURE ENGINEERING
# ==========================================

def engineer_features(df):
    """Create features for machine learning model"""
    
    print("🔧 Engineering features...")
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Extract time-based features
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    df['day_of_month'] = df['timestamp'].dt.day
    df['month'] = df['timestamp'].dt.month
    df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
    
    # Create lag features
    df['co2_lag_1'] = df['co2_value'].shift(1)
    df['co2_lag_2'] = df['co2_value'].shift(2)
    df['co2_lag_3'] = df['co2_value'].shift(3)
    
    # Rolling statistics
    df['co2_rolling_mean_3'] = df['co2_value'].rolling(window=3).mean()
    df['co2_rolling_mean_6'] = df['co2_value'].rolling(window=6).mean()
    df['co2_rolling_std_3'] = df['co2_value'].rolling(window=3).std()
    
    # Environmental features
    df['temp_humidity_interaction'] = df['temperature'] * df['humidity']
    
    # Time trend
    df['hours_since_start'] = (df['timestamp'] - df['timestamp'].min()).dt.total_seconds() / 3600
    
    df = df.dropna()
    
    print(f"✅ Created {len(df.columns)} features")
    print(f"📊 Dataset shape: {df.shape}\n")
    
    return df

# ==========================================
# 3. MODEL TRAINING
# ==========================================

def train_prediction_model(df):
    """Train machine learning models"""
    
    print("🤖 Training AI prediction models...\n")
    
    feature_columns = [
        'hour', 'day_of_week', 'day_of_month', 'month', 'is_weekend',
        'temperature', 'humidity', 'temp_humidity_interaction',
        'co2_lag_1', 'co2_lag_2', 'co2_lag_3',
        'co2_rolling_mean_3', 'co2_rolling_mean_6', 'co2_rolling_std_3',
        'hours_since_start'
    ]
    
    X = df[feature_columns]
    y = df['co2_value']
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=False
    )
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    models = {
        'Linear Regression': LinearRegression(),
        'Random Forest': RandomForestRegressor(n_estimators=100, random_state=42),
        'Gradient Boosting': GradientBoostingRegressor(n_estimators=100, random_state=42)
    }
    
    results = {}
    
    for name, model in models.items():
        print(f"Training {name}...")
        model.fit(X_train_scaled, y_train)
        y_pred = model.predict(X_test_scaled)
        
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)
        
        results[name] = {
            'model': model,
            'mae': mae,
            'rmse': rmse,
            'r2': r2,
            'predictions': y_pred
        }
        
        print(f"  MAE: {mae:.2f}")
        print(f"  RMSE: {rmse:.2f}")
        print(f"  R²: {r2:.3f}\n")
    
    best_model_name = min(results.keys(), key=lambda k: results[k]['rmse'])
    best_model = results[best_model_name]['model']
    
    print(f"🏆 Best Model: {best_model_name}")
    print(f"   RMSE: {results[best_model_name]['rmse']:.2f}")
    print(f"   R²: {results[best_model_name]['r2']:.3f}\n")
    
    # Save model
    import os
    os.makedirs('models', exist_ok=True)
    joblib.dump(best_model, 'models/emission_predictor.pkl')
    joblib.dump(scaler, 'models/scaler.pkl')
    
    print("✅ Models saved to 'models/' directory\n")
    
    return best_model, scaler, results, X_test, y_test

# ==========================================
# 4. FUTURE PREDICTIONS
# ==========================================

def predict_future_emissions(model, scaler, df, hours_ahead=24):
    """Predict emissions for next N hours"""
    
    print(f"🔮 Predicting emissions for next {hours_ahead} hours...\n")
    
    predictions = []
    last_data = df.iloc[-1].copy()
    
    for i in range(hours_ahead):
        future_time = last_data['timestamp'] + timedelta(hours=i+1)
        
        hour = future_time.hour
        day_of_week = future_time.dayofweek
        day_of_month = future_time.day
        month = future_time.month
        is_weekend = int(day_of_week in [5, 6])
        
        temperature = last_data['temperature']
        humidity = last_data['humidity']
        temp_humidity = temperature * humidity
        
        co2_lag_1 = last_data['co2_value'] if i == 0 else predictions[-1]['predicted_co2']
        co2_lag_2 = last_data['co2_lag_1'] if i == 0 else (predictions[-2]['predicted_co2'] if i > 1 else last_data['co2_value'])
        co2_lag_3 = last_data['co2_lag_2'] if i == 0 else (predictions[-3]['predicted_co2'] if i > 2 else last_data['co2_value'])
        
        recent_co2 = [last_data['co2_value']] + [p['predicted_co2'] for p in predictions[-5:]]
        co2_rolling_mean_3 = np.mean(recent_co2[-3:])
        co2_rolling_mean_6 = np.mean(recent_co2[-6:]) if len(recent_co2) >= 6 else np.mean(recent_co2)
        co2_rolling_std_3 = np.std(recent_co2[-3:])
        
        hours_since_start = last_data['hours_since_start'] + i + 1
        
        features = np.array([[
            hour, day_of_week, day_of_month, month, is_weekend,
            temperature, humidity, temp_humidity,
            co2_lag_1, co2_lag_2, co2_lag_3,
            co2_rolling_mean_3, co2_rolling_mean_6, co2_rolling_std_3,
            hours_since_start
        ]])
        
        features_scaled = scaler.transform(features)
        predicted_co2 = model.predict(features_scaled)[0]
        
        predictions.append({
            'timestamp': future_time.strftime('%Y-%m-%d %H:%M:%S'),
            'hour': hour,
            'day': future_time.strftime('%Y-%m-%d'),
            'predicted_co2': round(predicted_co2, 2),
            'confidence': 'high' if i < 6 else 'medium' if i < 12 else 'low'
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
        
        # Create table
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
        
        # Clear old predictions
        cursor.execute("DELETE FROM Emission_Predictions")
        
        # Insert new predictions
        for _, row in predictions_df.iterrows():
            timestamp_obj = pd.to_datetime(row['timestamp'])
            prediction_id = f"PRED_{int(timestamp_obj.timestamp() * 1000)}"
            
            cursor.execute("""
                INSERT INTO Emission_Predictions 
                (prediction_id, timestamp, predicted_co2, confidence)
                VALUES (%s, %s, %s, %s)
            """, (prediction_id, row['timestamp'], row['predicted_co2'], row['confidence']))
        
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
    """Calculate statistics for predictions"""
    
    stats = {
        'total_hours': len(predictions_df),
        'avg_predicted': float(predictions_df['predicted_co2'].mean()),
        'max_predicted': float(predictions_df['predicted_co2'].max()),
        'min_predicted': float(predictions_df['predicted_co2'].min()),
        'std_predicted': float(predictions_df['predicted_co2'].std()),
        'high_confidence_hours': len(predictions_df[predictions_df['confidence'] == 'high']),
        'medium_confidence_hours': len(predictions_df[predictions_df['confidence'] == 'medium']),
        'low_confidence_hours': len(predictions_df[predictions_df['confidence'] == 'low']),
        'hours_over_1000': len(predictions_df[predictions_df['predicted_co2'] > 1000]),
        'forecast_start': predictions_df['timestamp'].iloc[0],
        'forecast_end': predictions_df['timestamp'].iloc[-1],
    }
    
    return stats

# ==========================================
# 7. SAVE STATISTICS TO DATABASE
# ==========================================

def save_prediction_stats_to_db(stats):
    """Save prediction statistics to database"""
    
    print("💾 Saving prediction statistics...")
    
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()
        
        # Create stats table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Prediction_Statistics (
                stat_id INT PRIMARY KEY AUTO_INCREMENT,
                total_hours INT,
                avg_predicted FLOAT,
                max_predicted FLOAT,
                min_predicted FLOAT,
                std_predicted FLOAT,
                high_confidence_hours INT,
                medium_confidence_hours INT,
                low_confidence_hours INT,
                hours_over_1000 INT,
                forecast_start DATETIME,
                forecast_end DATETIME,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Clear old stats
        cursor.execute("DELETE FROM Prediction_Statistics")
        
        # Insert new stats
        cursor.execute("""
            INSERT INTO Prediction_Statistics 
            (total_hours, avg_predicted, max_predicted, min_predicted, std_predicted,
             high_confidence_hours, medium_confidence_hours, low_confidence_hours,
             hours_over_1000, forecast_start, forecast_end)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            stats['total_hours'], stats['avg_predicted'], stats['max_predicted'],
            stats['min_predicted'], stats['std_predicted'], stats['high_confidence_hours'],
            stats['medium_confidence_hours'], stats['low_confidence_hours'],
            stats['hours_over_1000'], stats['forecast_start'], stats['forecast_end']
        ))
        
        connection.commit()
        cursor.close()
        connection.close()
        
        print("✅ Statistics saved to database\n")
        
    except Exception as e:
        print(f"❌ Error saving statistics: {e}\n")

# ==========================================
# 8. VISUALIZATION
# ==========================================

def visualize_predictions(df, predictions_df, y_test, y_pred):
    """Create visualizations"""
    
    print("📊 Creating visualizations...\n")
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle('Carbon Emission Prediction Analysis', fontsize=16, fontweight='bold')
    
    # Convert predictions timestamp to datetime for plotting
    predictions_df['timestamp_dt'] = pd.to_datetime(predictions_df['timestamp'])
    
    # 1. Historical vs Predicted
    ax1 = axes[0, 0]
    recent_data = df.tail(50)
    ax1.plot(recent_data['timestamp'], recent_data['co2_value'], 
             label='Historical', marker='o', markersize=4, linewidth=2)
    ax1.plot(predictions_df['timestamp_dt'], predictions_df['predicted_co2'], 
             label='Predicted', marker='s', markersize=4, linewidth=2, linestyle='--', color='red')
    ax1.axhline(y=1000, color='orange', linestyle='--', label='Emission Limit')
    ax1.set_xlabel('Time')
    ax1.set_ylabel('CO₂ (kg/hour)')
    ax1.set_title('Historical vs Predicted Emissions')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)
    
    # 2. Actual vs Predicted
    ax2 = axes[0, 1]
    ax2.scatter(y_test, y_pred, alpha=0.5)
    ax2.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 
             'r--', lw=2, label='Perfect Prediction')
    ax2.set_xlabel('Actual CO₂')
    ax2.set_ylabel('Predicted CO₂')
    ax2.set_title('Model Accuracy: Actual vs Predicted')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. Error Distribution
    ax3 = axes[1, 0]
    errors = y_test - y_pred
    ax3.hist(errors, bins=30, edgecolor='black', alpha=0.7)
    ax3.axvline(x=0, color='red', linestyle='--', linewidth=2)
    ax3.set_xlabel('Prediction Error')
    ax3.set_ylabel('Frequency')
    ax3.set_title('Prediction Error Distribution')
    ax3.grid(True, alpha=0.3)
    
    # 4. Confidence Levels
    ax4 = axes[1, 1]
    colors = {'high': 'green', 'medium': 'orange', 'low': 'red'}
    for conf in ['high', 'medium', 'low']:
        subset = predictions_df[predictions_df['confidence'] == conf]
        ax4.plot(subset['hour'], subset['predicted_co2'], 
                marker='o', label=f'{conf.capitalize()} Confidence', 
                color=colors[conf], linewidth=2)
    ax4.axhline(y=1000, color='red', linestyle='--', label='Limit', linewidth=2)
    ax4.set_xlabel('Hour of Day')
    ax4.set_ylabel('Predicted CO₂ (kg/hour)')
    ax4.set_title('24-Hour Forecast with Confidence Levels')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('emission_predictions.png', dpi=300, bbox_inches='tight')
    print("✅ Visualization saved as 'emission_predictions.png'\n")
    
    return fig

# ==========================================
# 9. GENERATE REPORT
# ==========================================

def generate_prediction_report(predictions_df, stats):
    """Generate report"""
    
    print("=" * 60)
    print("📋 EMISSION PREDICTION REPORT")
    print("=" * 60)
    
    print(f"\n📅 Forecast Period: {stats['forecast_start']} to {stats['forecast_end']}")
    print(f"⏱️  Total Hours: {stats['total_hours']}")
    
    print(f"\n📊 PREDICTIONS SUMMARY:")
    print(f"   Average Predicted CO₂: {stats['avg_predicted']:.2f} kg/hour")
    print(f"   Maximum Predicted CO₂: {stats['max_predicted']:.2f} kg/hour")
    print(f"   Minimum Predicted CO₂: {stats['min_predicted']:.2f} kg/hour")
    print(f"   Standard Deviation: {stats['std_predicted']:.2f}")
    
    print(f"\n⚠️  ALERT FORECAST:")
    if stats['hours_over_1000'] > 0:
        print(f"   🚨 {stats['hours_over_1000']} hours predicted to EXCEED limit (1000 kg/hour)")
    else:
        print(f"   ✅ All predictions within safe limits")
    
    print(f"\n🎯 CONFIDENCE BREAKDOWN:")
    print(f"   High: {stats['high_confidence_hours']} hours")
    print(f"   Medium: {stats['medium_confidence_hours']} hours")
    print(f"   Low: {stats['low_confidence_hours']} hours")
    
    print("\n" + "=" * 60 + "\n")

# ==========================================
# 10. MAIN EXECUTION
# ==========================================

def main():
    """Main function"""
    
    print("\n" + "=" * 60)
    print("🤖 AI CARBON EMISSION PREDICTION SYSTEM")
    print("=" * 60 + "\n")
    
    # Load data
    df = load_emission_data_from_db()
    if df is None or len(df) < 20:
        print("❌ Not enough data for prediction. Need at least 20 records.")
        print("💡 Keep running serial-bridge.js to collect more data.")
        return
    
    # Engineer features
    df = engineer_features(df)
    
    # Train model
    best_model, scaler, results, X_test, y_test = train_prediction_model(df)
    
    # Make predictions
    predictions_df = predict_future_emissions(best_model, scaler, df, hours_ahead=24)
    
    # Calculate statistics
    stats = calculate_prediction_stats(predictions_df)
    
    # Generate report
    generate_prediction_report(predictions_df, stats)
    
    # Visualize
    best_pred = results[min(results.keys(), key=lambda k: results[k]['rmse'])]['predictions']
    visualize_predictions(df, predictions_df, y_test, best_pred)
    
    # Save to database
    save_predictions_to_db(predictions_df)
    save_prediction_stats_to_db(stats)
    
    # Export to CSV
    predictions_df_export = predictions_df.copy()
    predictions_df_export = predictions_df_export.drop('timestamp_dt', axis=1, errors='ignore')
    predictions_df_export.to_csv('future_predictions.csv', index=False)
    print("✅ Predictions exported to 'future_predictions.csv'")
    
    print("\n🎉 PREDICTION COMPLETE!")
    print("\n📌 Next Steps:")
    print("   1. Check 'emission_predictions.png' for visualizations")
    print("   2. View 'future_predictions.csv' for detailed forecast")
    print("   3. Predictions saved to database for dashboard display")
    print("   4. Refresh your dashboard to see AI predictions\n")

if __name__ == "__main__":
    main()