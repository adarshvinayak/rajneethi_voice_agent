"""
Simple script to make a call via the Plivo-LiveKit bridge
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

BRIDGE_SERVER_URL = os.getenv("BRIDGE_SERVER_URL", "http://localhost:8000")


def make_call(to_number: str):
    """Make a call using the bridge API"""
    url = f"{BRIDGE_SERVER_URL}/api/make_call"
    
    payload = {
        "to_number": to_number
    }
    
    print("=" * 70)
    print("Making call via Plivo-LiveKit Bridge")
    print("=" * 70)
    print(f"To: {to_number}")
    print(f"Bridge URL: {BRIDGE_SERVER_URL}")
    print("=" * 70)
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        
        if result.get("success"):
            print("✅ Call initiated successfully!")
            print(f"Call UUID: {result.get('call_uuid')}")
            print(f"Message: {result.get('message', 'N/A')}")
            print("\nThe agent will join the LiveKit room when the call is answered.")
        else:
            print("❌ Call failed!")
            print(f"Error: {result.get('error', 'Unknown error')}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error!")
        print(f"Could not connect to bridge server at {BRIDGE_SERVER_URL}")
        print("\nMake sure the bridge server is running:")
        print("  python plivo_bridge.py")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python make_call.py <phone_number>")
        print("Example: python make_call.py +1234567890")
        sys.exit(1)
    
    to_number = sys.argv[1]
    make_call(to_number)










