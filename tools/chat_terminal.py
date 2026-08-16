#!/usr/bin/env python3
"""
CHAT TERMINAL - Talk to YoBotz Now!

A robust terminal chat interface that works even with missing dependencies.
Just run and start chatting!
"""

import sys
import os
import time

print("\n" + "="*60)
print("🤖 YOBOTZ TERMINAL CHAT")
print("="*60)
print("Starting chat session...")

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    import yaml
    yaml_available = True
    print("✅ YAML support: OK")
except ImportError:
    yaml_available = False
    print("⚠️  YAML support: Missing (will use defaults)")

class MockReply:
    def __init__(self, text, meta=None):
        self.text = text
        self.meta = meta or {}

class FallbackChatEngine:
    """Local chat engine with no AI dependencies"""
    def __init__(self, business_name):
        self.business_name = business_name
        print(f"🍱 Fallback engine for: {business_name}")
        
        try:
            from smart_engine.core.intent_router import IntentRouter
            from smart_engine.core.session_manager import SessionManager
            from smart_engine.core.response_handler import ResponseHandler
            
            os.makedirs("data/sessions", exist_ok=True)
            session_manager = SessionManager(persistence_file=f"data/sessions/sessions_{business_name}.json")
            
            self.intent_router = IntentRouter(
                business_name=business_name,
                session_manager=session_manager
            )
            
            self.response_handler = ResponseHandler(business_name)
            self.has_menu_system = True
            print("✅ Router engine loaded successfully")
            
        except Exception as e:
            print(f"⚠️  Could not load router engine: {str(e)[:60]}")
            self.has_menu_system = False
            self.intent_router = None
        
    def process_message(self, message, user_id):
        """Process message with router if available"""
        if self.has_menu_system and self.intent_router:
            try:
                session = self.intent_router.session_manager.get_session(user_id)
                return self.intent_router.route_intent(
                    intent="",
                    message=message,
                    session=session,
                    response_handler=self.response_handler
                )
            except Exception as e:
                print(f"⚠️  Router engine error: {str(e)[:50]}")
        
        msg_lower = message.lower()
        
        responses = [
            ("hello", "Hi! Welcome to YoBakery! How can I help you today?"),
            ("hi", "Hello! What would you like to do?"),
            ("menu", "Our menu includes:\n• Artisan Breads\n• Custom Cakes\n• Pastries\n• Coffee & Tea"),
            ("order", "Great! The ordering system is currently being set up. Check back soon!"),
            ("book", "I can help you book a table! What day and time are you looking for?"),
            ("table", "Sure! How many people and what time?"),
            ("thanks", "You're welcome! Let me know if you need anything else."),
            ("bye", "Goodbye! Have a wonderful day!"),
            ("help", "I can help you with:\n• Menu inquiries\n• Booking tables\n• Business hours\n• Contact information")
        ]
        
        for keyword, response in responses:
            if keyword in msg_lower:
                return MockReply(response, {"intent": keyword, "confidence": 0.9})
        
        return MockReply(
            f"I understand you're asking about '{message}'. How can I assist you with {self.business_name}?",
            {"intent": "general", "confidence": 0.5}
        )

chat_engine = None
use_mock = False

try:
    if yaml_available:
        print("🔄 Loading ChatEngine...")
        
        os.environ['DEBUG'] = 'false'
        os.environ['LOG_LEVEL'] = 'INFO'
        
        from smart_engine.core.chat_engine import ChatEngine
        chat_engine = ChatEngine("yo_bakery")
        print("✅ ChatEngine loaded successfully!")
            
    else:
        raise ImportError("YAML not available")
        
except Exception as e:
    error_msg = str(e)
    print(f"⚠️  Could not load ChatEngine: {error_msg[:80]}")
    print("📋 Falling back to local engine...")
    chat_engine = FallbackChatEngine("yo_bakery")
    use_mock = True

session_id = "terminal_chat_" + str(int(time.time()))
print(f"📱 Session ID: {session_id}")
print("💬 Type your messages below (type 'quit' to exit)")
print("-" * 60)

message_count = 0

while True:
    try:
        user_message = input("\nYou: ").strip()
        
        if user_message.lower() in ['quit', 'exit', 'q']:
            print("\n👋 Goodbye! Thanks for chatting.")
            break
            
        if user_message.lower() == 'help':
            print("\n📋 Available commands:")
            print("  quit, exit, q  - End chat")
            print("  help           - Show this help")
            print("  new            - Start new session")
            print("\n💬 Just type normal messages to chat with YoBotz!")
            continue
            
        if user_message.lower() == 'new':
            session_id = "terminal_chat_" + str(int(time.time()))
            print(f"🔄 New session: {session_id}")
            continue
            
        if not user_message:
            continue
        
        message_count += 1
        print("   ", end="", flush=True)  # Indent for bot response
        
        try:
            response = chat_engine.process_message(user_message, session_id)
            
            print(f"🤖: {response.text}")
            
            if hasattr(response, 'meta') and response.meta:
                intent = response.meta.get('intent', '')
                tool_completed = response.meta.get('tool_completed', False)
                stage = response.meta.get('stage', '')
                active_tool = response.meta.get('active_tool', '')
                
                if tool_completed:
                    print(f"   [tool completed]")
                elif stage or intent in ['place_order', 'book_service', 'book_table'] or active_tool:
                    # Don't show "understood as:" during tool flows
                    pass
                elif intent and intent != 'general':
                    print(f"   [understood as: {intent}]")
                    
        except Exception as e:
            print(f"🤖: Sorry, I encountered an error: {str(e)[:50]}")
            print("   Please try rephrasing your message.")
            
    except KeyboardInterrupt:
        print("\n\n👋 Chat ended by user.")
        break
    except EOFError:
        print("\n\n👋 End of input.")
        break

print("\n" + "="*60)
print("📊 CHAT SUMMARY")
print("="*60)
print(f"Session ID: {session_id}")
print(f"Messages: {message_count}")
print(f"Mode: {'MOCK' if use_mock else 'REAL'}")
print("="*60)

print("\n💡 For full features:")
print("   Install: python3 -m pip install pyyaml huggingface-hub")
print("\n🚀 To chat again, run: python3 chat_terminal.py")