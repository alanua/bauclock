import pytest
from db.models import EventType
from datetime import datetime, timezone

class MockEvent:
    def __init__(self, event_type):
        self.event_type = event_type
        self.timestamp = datetime.now(timezone.utc)

def get_next_event_logic(last_event):
    """Refined copy of logic from worker.py for testing transition rules."""
    if not last_event:
        return "CHECKIN", "PROMPT"
    
    if last_event.event_type == EventType.CHECKIN or last_event.event_type == EventType.PAUSE_END:
        return "CHOICE", "PAUSE_OR_CHECKOUT"
    
    if last_event.event_type == EventType.PAUSE_START:
        return "PAUSE_END", "PROMPT"
    
    if last_event.event_type == EventType.CHECKOUT:
        return "BLOCKED", "ALREADY_DEPARTED"
    
    return None, None

def test_fsm_transitions():
    # 1. No event -> CHECKIN
    event, prompt = get_next_event_logic(None)
    assert event == "CHECKIN"
    
    # 2. CHECKIN -> CHOICE
    event, prompt = get_next_event_logic(MockEvent(EventType.CHECKIN))
    assert event == "CHOICE"
    
    # 3. PAUSE_START -> PAUSE_END
    event, prompt = get_next_event_logic(MockEvent(EventType.PAUSE_START))
    assert event == "PAUSE_END"
    
    # 4. PAUSE_END -> CHOICE
    event, prompt = get_next_event_logic(MockEvent(EventType.PAUSE_END))
    assert event == "CHOICE"
    
    # 5. CHECKOUT -> BLOCKED
    event, prompt = get_next_event_logic(MockEvent(EventType.CHECKOUT))
    assert event == "BLOCKED"
