"""
Intent Accuracy Module
Handles fetching, processing, and storing intent accuracy data.
"""
from datetime import datetime, date
from typing import Any, Dict, List, Optional
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


def get_conversation_logs(conversation_id: int, monitor_token: str = None) -> Dict[str, Any]:
    """
    Get conversation logs for a conversation ID.
    
    Args:
        conversation_id: The conversation ID
        monitor_token: Token for monitor API (optional, uses hardcoded token if not provided)
    
    Returns:
        Dictionary containing conversation data
    """
    url = f"https://robot-api.hacknao.edu.vn/robot/api/v1/monitor/conversations/{conversation_id}"
    params = {
        "token": monitor_token or MONITOR_TOKEN
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
                 corrected_content, conversation_id, message_id, context_question, corrected_intent)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                records.append((
                    str(user_id),
                    str(bot_id),
                    date_time,
                    user.get("content"),  # USER content
                    user.get("audio"),  # USER audio
                    pair.get("next_bot_intent"),  # Intent from NEXT BOT after USER
                    user.get("pattern"),  # Pattern from USER message
                    user.get("language"),  # Language from USER message
                    user.get("corrected_content"),  # Corrected content from USER message
                    str(conversation_id),
                    message_id,
                    pair.get("context_question"),  # Merged BOT content before USER
                    user.get("corrected_intent")  # Corrected intent from USER message
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
        logger.info(f"Fetching conversation IDs for {date_str}...")
        conversation_ids = get_conversation_ids(date_str, date_str, AUTH_TOKEN)
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


def get_intent_accuracy_for_date(target_date: date) -> Optional[float]:
    """
    Calculate intent accuracy for a specific date.
    Intent accuracy = (records with corrected_intent matching intent) / (total records with intent)
    
    Args:
        target_date: Target date to calculate accuracy for
    
    Returns:
        Intent accuracy as percentage (0-100), or None if no data
    """
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Count total records with intent
            cur.execute("""
                SELECT COUNT(*) 
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND intent IS NOT NULL
            """, (target_date,))
            total_with_intent = cur.fetchone()[0]
            
            if total_with_intent == 0:
                return None
            
            # Count records where corrected_intent matches intent (correct)
            cur.execute("""
                SELECT COUNT(*) 
                FROM intent_acc_metric 
                WHERE DATE(date_time) = %s 
                AND intent IS NOT NULL
                AND corrected_intent IS NOT NULL
                AND intent = corrected_intent
            """, (target_date,))
            correct_count = cur.fetchone()[0]
            
            accuracy = (correct_count / total_with_intent) * 100 if total_with_intent > 0 else 0
            return round(accuracy, 2)
            
    except Exception as e:
        logger.error(f"Error calculating intent accuracy: {e}")
        return None
    finally:
        conn.close()

