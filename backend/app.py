"""
Flask API server for Latency Metrics Dashboard
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import date, timedelta
import logging
import os

from evaluate import (
    refresh_ui_metrics,
    get_last_7_days_metrics,
    get_daily_metrics_from_latency_table,
    daily_job,
    check_data_exists_for_date
)

from intent_accuracy import (
    fetch_and_import_intent_accuracy,
    get_intent_accuracy_for_date,
    update_intent_accuracy_last_3_days,
    update_intent_accuracy_for_date,
    get_intent_accuracy_metrics_for_date_range
)

app = Flask(__name__)
# Enable CORS for all routes
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.route('/api/metrics/last-7-days', methods=['GET'])
def get_last_7_days():
    """Get metrics for the last 7 days."""
    bot_id = request.args.get('bot_id', type=int)
    metric_type = request.args.get('type', default='learn', type=str)
    try:
        # Use refresh_ui_metrics to get the full response with date_range
        results = refresh_ui_metrics(bot_id, metric_type=metric_type)
        return jsonify({
            "status": "success",
            "data": results
        }), 200
    except Exception as e:
        logger.error(f"Error getting last 7 days metrics: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/refresh', methods=['POST'])
def refresh_metrics():
    """Refresh and recalculate metrics from database."""
    data = request.get_json() or {}
    bot_id = data.get('bot_id')
    metric_type = data.get('type', 'learn')
    
    try:
        results = refresh_ui_metrics(bot_id, metric_type=metric_type)
        return jsonify({
            "status": "success",
            "data": results
        }), 200
    except Exception as e:
        logger.error(f"Error refreshing metrics: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/daily', methods=['GET'])
def get_daily_metrics():
    """Get daily metrics for a date range."""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    bot_id = request.args.get('bot_id', type=int)
    
    try:
        if start_date_str and end_date_str:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        else:
            # Default to last 7 days
            end_date = date.today()
            start_date = end_date - timedelta(days=6)
        
        metric_type = request.args.get('type', default='learn', type=str)
        metrics = get_daily_metrics_from_latency_table(start_date, end_date, bot_id, metric_type=metric_type)
        
        return jsonify({
            "status": "success",
            "data": metrics
        }), 200
    except Exception as e:
        logger.error(f"Error getting daily metrics: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/fetch-date', methods=['POST'])
def fetch_date_data():
    """Fetch and save data for a specific date."""
    data = request.get_json() or {}
    target_date_str = data.get('date')
    metric_type = data.get('type', 'learn')
    
    if not target_date_str:
        return jsonify({
            "status": "error",
            "message": "Date is required"
        }), 400
    
    try:
        target_date = date.fromisoformat(target_date_str)
        logger.info(f"Fetch request received for date: {target_date_str} (parsed as: {target_date}), type: {metric_type}")
        
        # Check if data already exists
        db_type = "workflow" if metric_type == "learn" else metric_type
        if check_data_exists_for_date(target_date, db_type):
            logger.info(f"Data already exists for {target_date} (type: {db_type})")
            return jsonify({
                "status": "success",
                "message": f"Data already exists for {target_date_str}",
                "data_exists": True
            }), 200
        
        # Fetch and save data for the selected date (tokens are hardcoded in evaluate.py)
        logger.info(f"Starting fetch for date: {target_date} (type: {db_type})")
        daily_job(None, None, target_date, metric_type=db_type)
        
        # Verify data was saved
        if check_data_exists_for_date(target_date, db_type):
            logger.info(f"Successfully fetched and saved data for {target_date}")
            return jsonify({
                "status": "success",
                "message": f"Data fetched and saved for {target_date_str}",
                "data_exists": False,
                "date": target_date_str
            }), 200
        else:
            logger.warning(f"Fetch completed but no data found for {target_date} after save")
            return jsonify({
                "status": "warning",
                "message": f"Fetch completed but no data was saved for {target_date_str}. Check logs for details.",
                "data_exists": False
            }), 200
        
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": f"Invalid date format: {str(e)}"
        }), 400
    except Exception as e:
        logger.error(f"Error fetching date data: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/fetch-intent-accuracy', methods=['POST'])
def fetch_intent_accuracy():
    """Fetch and import intent accuracy data for a specific date."""
    data = request.get_json() or {}
    target_date_str = data.get('date')
    
    if not target_date_str:
        return jsonify({
            "status": "error",
            "message": "Date is required"
        }), 400
    
    try:
        target_date = date.fromisoformat(target_date_str)
        logger.info(f"Fetch intent accuracy request for date: {target_date_str}")
        
        # Fetch and import intent accuracy data
        result = fetch_and_import_intent_accuracy(target_date)
        
        return jsonify({
            "status": "success",
            "message": f"Intent accuracy data imported for {target_date_str}",
            "data": result
        }), 200
        
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": f"Invalid date format: {str(e)}"
        }), 400
    except Exception as e:
        logger.error(f"Error fetching intent accuracy: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/intent-accuracy', methods=['GET'])
def get_intent_accuracy():
    """Get intent accuracy for a specific date."""
    target_date_str = request.args.get('date')
    
    if not target_date_str:
        return jsonify({
            "status": "error",
            "message": "Date is required"
        }), 400
    
    try:
        target_date = date.fromisoformat(target_date_str)
        accuracy = get_intent_accuracy_for_date(target_date)
        
        return jsonify({
            "status": "success",
            "data": {
                "date": target_date_str,
                "intent_accuracy": accuracy
            }
        }), 200
        
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": f"Invalid date format: {str(e)}"
        }), 400
    except Exception as e:
        logger.error(f"Error getting intent accuracy: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/update-intent-accuracy-3days', methods=['POST'])
def update_intent_accuracy_3days():
    """Update intent accuracy data for the last 3 days."""
    try:
        logger.info("Update intent accuracy for last 3 days request received")
        result = update_intent_accuracy_last_3_days()
        
        return jsonify({
            "status": result.get("status", "success"),
            "message": result.get("message", "Update completed"),
            "data": result
        }), 200
        
    except Exception as e:
        logger.error(f"Error updating intent accuracy for last 3 days: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/metrics/intent-accuracy-metrics', methods=['GET'])
def get_intent_accuracy_metrics():
    """Get intent accuracy metrics for a date range."""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    try:
        if start_date_str and end_date_str:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        else:
            # Default to last 7 days
            end_date = date.today()
            start_date = end_date - timedelta(days=6)
        
        metrics = get_intent_accuracy_metrics_for_date_range(start_date, end_date)
        
        return jsonify({
            "status": "success",
            "data": metrics
        }), 200
        
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": f"Invalid date format: {str(e)}"
        }), 400
    except Exception as e:
        logger.error(f"Error getting intent accuracy metrics: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


if __name__ == '__main__':
    # Use port from environment variable or default to 5001
    port = int(os.environ.get('PORT', 5001))
    host = os.environ.get('HOST', '0.0.0.0')
    
    print("Starting API server on http://{}:{}".format(host, port))
    print("Endpoints:")
    print("  GET  /api/metrics/last-7-days?bot_id=<optional>")
    print("  POST /api/metrics/refresh")
    print("  GET  /api/metrics/daily?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&bot_id=<optional>")
    print("  GET  /health")
    
    app.run(host=host, port=port, debug=False)

