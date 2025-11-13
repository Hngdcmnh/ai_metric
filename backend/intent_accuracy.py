"""
Intent Accuracy Module
Handles fetching, processing, and storing intent accuracy data.
"""
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
import logging

import requests
import psycopg2
from psycopg2.extras import execute_batch

from evaluate import (
    get_db_connection,
    get_conversation_ids,
    AUTH_TOKEN,
    MONITOR_TOKEN
)

logger = logging.getLogger(__name__)


def get_conversation_logs(conversation_id: int, token: str = None) -> Dict[str, Any]:
    """
    Get conversation logs for a conversation ID.
    
    Args:
        conversation_id: The conversation ID
        token: Token for monitor API (optional, uses MONITOR_TOKEN if not provided)
    
    Returns:
        Dictionary containing conversation data
    """
    url = f"https://robot-api.hacknao.edu.vn/robot/api/v1/monitor/conversations/{conversation_id}"
    params = {
        "token": token or MONITOR_TOKEN
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    data = response.json()
    if data.get("status") == 200:
        return data.get("data", {})
    else:
        raise Exception(f"API error: {data.get('message', 'Unknown error')}")


def build_pairs(conversation_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build pairs from conversation list.
    Logic matches JavaScript reference:
    - Merge consecutive BOT_RESPONSE_CONVERSATION messages into context_question
    - When encountering USER, create pair immediately with context_question (from BOT chunks) and user (USER message)
    - intent will be updated from next BOT_RESPONSE_CONVERSATION after USER
    
    Args:
        conversation_list: List of conversation message objects
    
    Returns:
        List of pairs, each pair has context_question (merged BOT content before USER) and user (USER object)
    """
    pairs = []
    pending_bot_chunks = []  # BOT content chunks to merge into context_question
    
    for msg in conversation_list:
        character = msg.get("character", "")
        
        if character == "BOT_RESPONSE_CONVERSATION":
            # Collect BOT content chunks
            if msg.get("content"):
                pending_bot_chunks.append(str(msg.get("content")))
            
            # If there's a pair that was just created (last pair), update its intent from this BOT
            if pairs:
                last_pair = pairs[-1]
                # Only update if intent hasn't been set yet (from previous BOT)
                if "next_bot_intent" not in last_pair or last_pair.get("next_bot_intent") is None:
                    last_pair["next_bot_intent"] = msg.get("intent")
            
            continue
        
        if character == "USER":
            # If we have pending BOT chunks, create a pair immediately
            if pending_bot_chunks:
                context_question = " ".join(pending_bot_chunks)
                pairs.append({
                    "context_question": context_question,
                    "user": msg,
                    "next_bot_intent": None  # Will be updated by next BOT_RESPONSE_CONVERSATION
                })
                # Reset BOT chunks after creating pair
                pending_bot_chunks = []
            continue
        
        # Other character types -> reset BOT chunks if accumulating
        if pending_bot_chunks:
            pending_bot_chunks = []
    
    return pairs


def save_intent_accuracy_to_db(
    pairs_data: List[Dict[str, Any]],
    conversation_data: Dict[str, Any],
    target_date: date
) -> int:
    """
    Save intent accuracy data to intent_acc_metric table.
    
    Args:
        pairs_data: List of pairs from build_pairs
        conversation_data: Conversation metadata (user_id, bot_id, conversation_id, date)
        target_date: Target date for the data
    
    Returns:
        Number of records inserted
    """
    if not pairs_data:
        logger.warning("No pairs data to save")
        return 0
    
    conn = get_db_connection()
    inserted_count = 0
    
    try:
        with conn.cursor() as cur:
            insert_query = """
                INSERT INTO intent_acc_metric 
                (user_id, bot_id, date_time, content, audio, intent, pattern, language,
                 corrected_content, conversation_id, message_id, context_question, corrected_intent, wer)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            user_id = conversation_data.get("user_id", "unknown_user")
            bot_id = conversation_data.get("bot_id", "unknown_bot")
            conversation_id = conversation_data.get("conversation_id", "unknown_conversation")
            date_time = conversation_data.get("date", datetime.now())
            
            # Convert date_time to datetime if it's a string
            if isinstance(date_time, str):
                try:
                    date_time = datetime.fromisoformat(date_time.replace('Z', '+00:00'))
                except:
                    date_time = datetime.combine(target_date, datetime.min.time())
            elif isinstance(date_time, date) and not isinstance(date_time, datetime):
                date_time = datetime.combine(date_time, datetime.min.time())
            
            records = []
            for idx, pair in enumerate(pairs_data):
                user = pair.get("user", {})
                
                # message_id format: conversation_id_user._id or conversation_id_idx
                message_id = f"{conversation_id}_{user.get('_id', idx)}"
                
                # intent comes from next BOT_RESPONSE_CONVERSATION after USER
                # language, corrected_content, etc. come from USER message
                content = user.get("content") or ""
                corrected_content = user.get("corrected_content") or ""
                
                # Calculate WER
                wer = calculate_wer(corrected_content, content)
                
                # Map corrected_intent before saving
                api_corrected_intent = user.get("corrected_intent")
                mapped_corrected_intent = map_corrected_intent(api_corrected_intent) if api_corrected_intent else None
                
                records.append((
                    str(user_id),
                    str(bot_id),
                    date_time,
                    content,  # USER content
                    user.get("audio"),  # USER audio
                    pair.get("next_bot_intent"),  # Intent from NEXT BOT after USER
                    user.get("pattern"),  # Pattern from USER message
                    user.get("language"),  # Language from USER message
                    corrected_content,  # Corrected content from USER message
                    str(conversation_id),
                    message_id,
                    pair.get("context_question"),  # Merged BOT content before USER
                    mapped_corrected_intent,  # Corrected intent from USER message (mapped)
                    wer  # WER value
                ))
            
            if records:
                execute_batch(cur, insert_query, records, page_size=1000)
                inserted_count = len(records)
                conn.commit()
                logger.info(f"Inserted {inserted_count} records into intent_acc_metric table")
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving intent accuracy data to database: {e}")
        raise
    finally:
        conn.close()
    
    return inserted_count


def fetch_and_import_intent_accuracy(target_date: date) -> Dict[str, Any]:
    """
    Fetch and import intent accuracy data for a specific date.
    
    Args:
        target_date: Target date to fetch data for
    
    Returns:
        Dictionary with summary of imported data
    """
    logger.info(f"Starting intent accuracy import for date: {target_date}")
    
    date_str = target_date.strftime("%d/%m/%Y")
    
    try:
        # Reset sequence to max(id) + 1 to avoid gaps after deletions (only once at the start)
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT setval(
                        pg_get_serial_sequence('intent_acc_metric', 'id'),
                        COALESCE((SELECT MAX(id) FROM intent_acc_metric), 0) + 1,
                        false
                    )
                """)
                conn.commit()
                logger.info("Reset intent_acc_metric sequence to max(id) + 1")
        except Exception as seq_error:
            logger.warning(f"Could not reset sequence (may not exist yet): {seq_error}")
            conn.rollback()
        finally:
            conn.close()
        
        # Step 1: Get conversation IDs for the date
        # get_conversation_ids uses fixed_token internally (b1812cb7-2513-408b-bb22-d9f91b099fbd)
        logger.info(f"Fetching conversation IDs for {date_str}...")
        conversation_ids = get_conversation_ids(date_str, date_str)
        logger.info(f"Found {len(conversation_ids)} conversations")
        
        total_pairs = 0
        total_inserted = 0
        failed_conversations = 0
        
        # Step 2: For each conversation, get logs and process
        for idx, conv_id in enumerate(conversation_ids, 1):
            try:
                logger.info(f"Processing conversation {idx}/{len(conversation_ids)}: {conv_id}")
                
                # Get conversation logs
                conversation_data = get_conversation_logs(conv_id, MONITOR_TOKEN)
                
                # Extract conversation list
                conversation_list = conversation_data.get("data", [])
                if not conversation_list:
                    logger.warning(f"No conversation data for {conv_id}")
                    continue
                
                logger.debug(f"Conversation {conv_id}: {len(conversation_list)} messages")
                
                # Build pairs
                pairs = build_pairs(conversation_list)
                logger.debug(f"Conversation {conv_id}: built {len(pairs)} pairs from {len(conversation_list)} messages")
                total_pairs += len(pairs)
                
                # Save to database
                if pairs:
                    inserted = save_intent_accuracy_to_db(
                        pairs,
                        {
                            "user_id": conversation_data.get("user_id", "unknown_user"),
                            "bot_id": conversation_data.get("bot_id", "unknown_bot"),
                            "conversation_id": str(conv_id),
                            "date": conversation_data.get("date", datetime.combine(target_date, datetime.min.time()))
                        },
                        target_date
                    )
                    total_inserted += inserted
                    logger.debug(f"Conversation {conv_id}: inserted {inserted} records")
                else:
                    logger.warning(f"Conversation {conv_id}: no pairs generated")
                
                if idx % 50 == 0:
                    logger.info(f"Processed {idx}/{len(conversation_ids)} conversations... Total pairs: {total_pairs}, Total inserted: {total_inserted}")
                    
            except Exception as e:
                logger.error(f"Error processing conversation {conv_id}: {e}", exc_info=True)
                failed_conversations += 1
                continue
        
        logger.info(f"Intent accuracy import completed: {total_inserted} records inserted from {total_pairs} pairs, {failed_conversations} failed")
        
        return {
            "conversations_processed": len(conversation_ids),
            "total_pairs": total_pairs,
            "total_inserted": total_inserted,
            "failed_conversations": failed_conversations
        }
        
    except Exception as e:
        logger.error(f"Error in intent accuracy import: {e}", exc_info=True)
        raise


def calculate_wer(reference: str, hypothesis: str) -> float:
    """
    Calculate Word Error Rate (WER) between reference and hypothesis text.
    WER = (S + D + I) / N
    where S = substitutions, D = deletions, I = insertions, N = number of words in reference
    
    Args:
        reference: Reference text (corrected_content)
        hypothesis: Hypothesis text (content)
    
    Returns:
        WER as a float (0.0 to 1.0+), or 0.0 if reference is empty
    """
    if not reference or not isinstance(reference, str):
        return 0.0
    
    if not hypothesis or not isinstance(hypothesis, str):
        # If hypothesis is empty but reference is not, WER is 1.0 (all words are errors)
        return 1.0 if reference.strip() else 0.0
    
    # Tokenize into words (split by whitespace)
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()
    
    if len(ref_words) == 0:
        # If reference is empty, WER is 0 if hypothesis is also empty, else 1.0
        return 0.0 if len(hyp_words) == 0 else 1.0
    
    # Use dynamic programming (Levenshtein distance) to calculate edit distance
    # dp[i][j] = minimum edit distance between ref_words[0:i] and hyp_words[0:j]
    n = len(ref_words)
    m = len(hyp_words)
    
    # Initialize DP table
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    
    # Base cases
    for i in range(n + 1):
        dp[i][0] = i  # Deletions
    for j in range(m + 1):
        dp[0][j] = j  # Insertions
    
    # Fill DP table
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1].lower() == hyp_words[j - 1].lower():
                # Match
                dp[i][j] = dp[i - 1][j - 1]
            else:
                # Minimum of substitution, deletion, insertion
                dp[i][j] = 1 + min(
                    dp[i - 1][j - 1],  # Substitution
                    dp[i - 1][j],      # Deletion
                    dp[i][j - 1]       # Insertion
                )
    
    # WER = edit distance / number of words in reference
    wer = dp[n][m] / n
    return round(wer, 4)


def get_message_ids_for_dates(start_date: date, end_date: date) -> List[str]:
    """
    Get all message_ids from intent_acc_metric table for a date range.
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    
    Returns:
        List of message_ids
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT message_id 
                FROM intent_acc_metric 
                WHERE DATE(date_time) BETWEEN %s AND %s
                AND message_id IS NOT NULL
            """, (start_date, end_date))
            rows = cur.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Error getting message_ids: {e}")
        return []
    finally:
        conn.close()


def fetch_message_data_from_api(message_id: str, api_url: str = None, api_token: str = None) -> Optional[Dict[str, Any]]:
    """
    Fetch message data from API using message_id with pika- prefix.
    
    Args:
        message_id: Message ID (will be prefixed with "pika-")
        api_url: API endpoint URL (optional, uses default if not provided)
        api_token: API token (optional, uses AUTH_TOKEN if not provided)
    
    Returns:
        Dictionary containing message data, or None if error
    """
    if not message_id:
        return None
    
    # Add pika- prefix
    prefixed_message_id = f"pika-{message_id}"
    
    # Default API URL - pika-intent labeled endpoint
    if api_url is None:
        api_url = f"http://103.253.20.30:8111/pika-intent/labeled/{prefixed_message_id}"
    
    try:
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        # API returns data directly, not wrapped in status/data structure
        if isinstance(data, dict):
            return data
        else:
            logger.warning(f"Unexpected response format for message_id {prefixed_message_id}")
            return None
            
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.debug(f"Message not found in labeled API: {prefixed_message_id}")
        else:
            logger.warning(f"HTTP error fetching message data for {prefixed_message_id}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching message data for {prefixed_message_id}: {e}")
        return None


def map_corrected_intent(api_intent: str) -> Optional[str]:
    """
    Map corrected_intent from API to database value.
    
    Mapping rules:
    - correct -> intent_true
    - wrong -> intent_false
    - irrelevant -> fallback
    - silent -> silent
    
    Args:
        api_intent: Intent value from API
    
    Returns:
        Mapped intent value, or None if not found
    """
    if not api_intent:
        return None
    
    mapping = {
        "correct": "intent_true",
        "wrong": "intent_false",
        "irrelevant": "fallback",
        "silent": "silent"
    }
    
    # Case-insensitive mapping
    api_intent_lower = api_intent.lower().strip()
    mapped_intent = mapping.get(api_intent_lower)
    
    if mapped_intent:
        logger.debug(f"Mapped intent: {api_intent} -> {mapped_intent}")
        return mapped_intent
    else:
        # If not in mapping, return original value (case preserved)
        logger.debug(f"Intent not in mapping, using original: {api_intent}")
        return api_intent


def update_intent_accuracy_with_wer(message_id: str, message_data: Dict[str, Any]) -> bool:
    """
    Update intent_acc_metric record with WER and data from API.
    
    Args:
        message_id: Message ID (without pika- prefix)
        message_data: Message data from API
    
    Returns:
        True if update successful, False otherwise
    """
    if not message_data:
        return False
    
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Get current record - lấy content gốc từ DB
            cur.execute("""
                SELECT content, corrected_content 
                FROM intent_acc_metric 
                WHERE message_id = %s
                LIMIT 1
            """, (message_id,))
            
            row = cur.fetchone()
            if not row:
                logger.warning(f"Record not found for message_id: {message_id}")
                return False
            
            # Lấy content gốc từ DB (không thay đổi)
            original_content = row[0] or ""
            
            # Extract data from API response
            # API trả về corrected_content và corrected_intent
            api_corrected_content = message_data.get("corrected_content") or ""
            api_corrected_intent = message_data.get("corrected_intent")
            
            # Map corrected_intent before saving to DB
            mapped_corrected_intent = map_corrected_intent(api_corrected_intent) if api_corrected_intent else None
            
            # Calculate WER: so sánh corrected_content (từ API) với content gốc (từ DB)
            wer = calculate_wer(api_corrected_content, original_content)
            
            # Update record
            # Chỉ update corrected_content, corrected_intent (đã map) và wer
            # Không thay đổi content gốc
            update_query = """
                UPDATE intent_acc_metric 
                SET corrected_content = %s,
                    corrected_intent = COALESCE(%s, corrected_intent),
                    wer = %s
                WHERE message_id = %s
            """
            
            cur.execute(update_query, (
                api_corrected_content,
                mapped_corrected_intent,
                wer,
                message_id
            ))
            
            conn.commit()
            logger.debug(f"Updated message_id {message_id} with WER={wer}, corrected_intent={mapped_corrected_intent}")
            return True
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating message_id {message_id}: {e}")
        return False
    finally:
        conn.close()


def update_intent_accuracy_for_date(target_date: date) -> Dict[str, Any]:
    """
    Update intent accuracy data for a specific date.
    Fetches message_ids from DB for the given date, adds pika- prefix, requests API, and updates DB with WER.
    
    Args:
        target_date: The date to update
    
    Returns:
        Dictionary with summary of update operation
    """
    logger.info(f"Starting update intent accuracy for date: {target_date}")
    
    try:
        # Step 1: Get all message_ids for the target date
        logger.info(f"Fetching message_ids for date: {target_date}")
        message_ids = get_message_ids_for_dates(target_date, target_date)
        logger.info(f"Found {len(message_ids)} message_ids")
        
        if not message_ids:
            return {
                "status": "success",
                "message": f"No message_ids found for {target_date}",
                "total_message_ids": 0,
                "updated": 0,
                "failed": 0,
                "date": target_date.isoformat()
            }
        
        # Step 2: For each message_id, fetch from API and update DB
        updated_count = 0
        failed_count = 0
        
        for idx, msg_id in enumerate(message_ids, 1):
            try:
                # Fetch message data from API
                message_data = fetch_message_data_from_api(msg_id)
                
                if message_data:
                    # Update DB with WER
                    if update_intent_accuracy_with_wer(msg_id, message_data):
                        updated_count += 1
                    else:
                        failed_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"Failed to fetch data for message_id: {msg_id}")
                
                if idx % 100 == 0:
                    logger.info(f"Processed {idx}/{len(message_ids)} message_ids... Updated: {updated_count}, Failed: {failed_count}")
                    
            except Exception as e:
                logger.error(f"Error processing message_id {msg_id}: {e}")
                failed_count += 1
                continue
        
        logger.info(f"Update completed for {target_date}: {updated_count} updated, {failed_count} failed out of {len(message_ids)} total")
        
        return {
            "status": "success",
            "message": f"Updated {updated_count} records, {failed_count} failed for {target_date}",
            "total_message_ids": len(message_ids),
            "updated": updated_count,
            "failed": failed_count,
            "date": target_date.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error updating intent accuracy for date {target_date}: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "total_message_ids": 0,
            "updated": 0,
            "failed": 0,
            "date": target_date.isoformat()
        }


def update_intent_accuracy_last_3_days() -> Dict[str, Any]:
    """
    Update intent accuracy data for the last 3 days (today, today-1, today-2).
    Fetches message_ids from DB, adds pika- prefix, requests API, and updates DB with WER.
    
    Returns:
        Dictionary with summary of update operation
    """
    logger.info("Starting update intent accuracy for last 3 days")
    
    today = date.today()
    start_date = today - timedelta(days=2)  # 3 days: today, today-1, today-2
    end_date = today
    
    try:
        # Step 1: Get all message_ids for the last 3 days
        logger.info(f"Fetching message_ids for date range: {start_date} to {end_date}")
        message_ids = get_message_ids_for_dates(start_date, end_date)
        logger.info(f"Found {len(message_ids)} message_ids")
        
        if not message_ids:
            return {
                "status": "success",
                "message": "No message_ids found for the last 3 days",
                "total_message_ids": 0,
                "updated": 0,
                "failed": 0
            }
        
        # Step 2: For each message_id, fetch from API and update DB
        updated_count = 0
        failed_count = 0
        
        for idx, msg_id in enumerate(message_ids, 1):
            try:
                # Fetch message data from API
                message_data = fetch_message_data_from_api(msg_id)
                
                if message_data:
                    # Update DB with WER
                    if update_intent_accuracy_with_wer(msg_id, message_data):
                        updated_count += 1
                    else:
                        failed_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"Failed to fetch data for message_id: {msg_id}")
                
                if idx % 100 == 0:
                    logger.info(f"Processed {idx}/{len(message_ids)} message_ids... Updated: {updated_count}, Failed: {failed_count}")
                    
            except Exception as e:
                logger.error(f"Error processing message_id {msg_id}: {e}")
                failed_count += 1
                continue
        
        logger.info(f"Update completed: {updated_count} updated, {failed_count} failed out of {len(message_ids)} total")
        
        return {
            "status": "success",
            "message": f"Updated {updated_count} records, {failed_count} failed",
            "total_message_ids": len(message_ids),
            "updated": updated_count,
            "failed": failed_count
        }
        
    except Exception as e:
        logger.error(f"Error updating intent accuracy for last 3 days: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "total_message_ids": 0,
            "updated": 0,
            "failed": 0
        }


def get_intent_accuracy_detail_for_date(target_date: date) -> Dict[str, Any]:
    """
    Get detailed intent accuracy information for a specific date.
    
    Args:
        target_date: Target date to get detail for
    
    Returns:
        Dictionary containing:
        - total_with_intent: Total records with intent not null (records need labeling)
        - total_with_corrected_intent: Total records with corrected_intent
        - incorrect_records: List of records where intent != corrected_intent
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Count total records with intent not null (records need labeling)
            cur.execute("""
                SELECT COUNT(*) 
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND intent IS NOT NULL
            """, (target_date,))
            total_with_intent = cur.fetchone()[0]
            
            # Count total records with corrected_intent
            cur.execute("""
                SELECT COUNT(*) 
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND corrected_intent IS NOT NULL
            """, (target_date,))
            total_with_corrected_intent = cur.fetchone()[0]
            
            # Get records where intent != corrected_intent
            cur.execute("""
                SELECT 
                    message_id,
                    content,
                    corrected_content,
                    intent,
                    corrected_intent,
                    wer,
                    date_time,
                    conversation_id
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND corrected_intent IS NOT NULL
                AND intent IS NOT NULL
                AND intent != corrected_intent
                ORDER BY date_time DESC
            """, (target_date,))
            
            rows = cur.fetchall()
            incorrect_records = []
            for row in rows:
                incorrect_records.append({
                    "message_id": row[0],
                    "content": row[1] or "",
                    "corrected_content": row[2] or "",
                    "intent": row[3] or "",
                    "corrected_intent": row[4] or "",
                    "wer": float(row[5]) if row[5] is not None else None,
                    "date_time": row[6].isoformat() if row[6] else None,
                    "conversation_id": row[7] or ""
                })
            
            return {
                "total_with_intent": total_with_intent,
                "total_with_corrected_intent": total_with_corrected_intent,
                "incorrect_records": incorrect_records,
                "date": target_date.isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error getting intent accuracy detail: {e}")
        return {
            "total_with_intent": 0,
            "total_with_corrected_intent": 0,
            "incorrect_records": [],
            "date": target_date.isoformat()
        }
    finally:
        conn.close()


def get_intent_accuracy_for_date(target_date: date) -> Optional[float]:
    """
    Calculate intent accuracy for a specific date.
    Intent accuracy = (records with corrected_intent matching intent) / (total records with corrected_intent)
    
    Args:
        target_date: Target date to calculate accuracy for
    
    Returns:
        Intent accuracy as percentage (0-100), or None if no data
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Count total records with corrected_intent
            cur.execute("""
                SELECT COUNT(*) 
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND corrected_intent IS NOT NULL
            """, (target_date,))
            total_with_corrected_intent = cur.fetchone()[0]
            
            if total_with_corrected_intent == 0:
                return None
            
            # Count records where corrected_intent matches intent (correct)
            cur.execute("""
                SELECT COUNT(*) 
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND corrected_intent IS NOT NULL
                AND intent IS NOT NULL
                AND intent = corrected_intent
            """, (target_date,))
            correct_count = cur.fetchone()[0]
            
            accuracy = (correct_count / total_with_corrected_intent) * 100 if total_with_corrected_intent > 0 else 0
            return round(accuracy, 2)
            
    except Exception as e:
        logger.error(f"Error calculating intent accuracy: {e}")
        return None
    finally:
        conn.close()


def get_intent_accuracy_metrics_for_date_range(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Calculate intent accuracy metrics for a date range.
    Returns metrics for each day including:
    - Intent accuracy (corrected_intent == intent)
    - Intent accuracy error due to ASR (WER > 0)
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    
    Returns:
        List of dictionaries with date and metrics
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Query to get metrics grouped by date
            # Intent accuracy = (corrected_intent == intent) / (total có corrected_intent)
            # Intent error do ASR = (corrected_intent != intent AND wer > 0) / (total có corrected_intent)
            # Intent error không do ASR = (corrected_intent != intent AND (wer = 0 OR wer IS NULL)) / (total có corrected_intent)
            cur.execute("""
                SELECT 
                    DATE(date_time) as metric_date,
                    COUNT(*) FILTER (WHERE corrected_intent IS NOT NULL) as total_with_corrected_intent,
                    COUNT(*) FILTER (WHERE corrected_intent IS NOT NULL AND intent IS NOT NULL AND intent = corrected_intent) as correct_count,
                    COUNT(*) FILTER (WHERE corrected_intent IS NOT NULL AND intent IS NOT NULL AND intent != corrected_intent AND wer > 0) as incorrect_due_to_wer,
                    COUNT(*) FILTER (WHERE corrected_intent IS NOT NULL AND intent IS NOT NULL AND intent != corrected_intent AND (wer = 0 OR wer IS NULL)) as incorrect_not_asr
                FROM intent_acc_metric
                WHERE DATE(date_time) BETWEEN %s AND %s
                GROUP BY DATE(date_time)
                ORDER BY metric_date ASC
            """, (start_date, end_date))
            
            rows = cur.fetchall()
            
            results = []
            for row in rows:
                metric_date = row[0]
                total = row[1] or 0
                correct_count = row[2] or 0
                incorrect_due_to_wer = row[3] or 0  # incorrect với wer > 0
                incorrect_not_asr = row[4] or 0      # incorrect với wer = 0 hoặc NULL
                
                if total == 0:
                    continue
                
                # Intent accuracy percentage = (corrected_intent == intent) / (total có corrected_intent)
                intent_accuracy = (correct_count / total) * 100 if total > 0 else 0
                
                # Intent accuracy error due to ASR (WER > 0 hoặc NULL) percentage
                intent_error_due_to_asr = (incorrect_due_to_wer / total) * 100 if total > 0 else 0
                
                # Intent accuracy error not due to ASR (WER = 0 hoặc NULL)
                intent_error_not_asr = (incorrect_not_asr / total) * 100 if total > 0 else 0
                
                results.append({
                    "date": metric_date.isoformat() if isinstance(metric_date, date) else str(metric_date),
                    "intent_accuracy": round(intent_accuracy, 2),
                    "intent_error_due_to_asr": round(intent_error_due_to_asr, 2),
                    "intent_error_not_asr": round(intent_error_not_asr, 2),
                    "total_records": total,
                    "correct_count": correct_count,
                    "incorrect_due_to_wer": incorrect_due_to_wer,
                    "incorrect_not_asr": incorrect_not_asr
                })
            
            return results
            
    except Exception as e:
        logger.error(f"Error calculating intent accuracy metrics: {e}")
        return []
    finally:
        conn.close()

