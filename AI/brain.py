"""
=========================================
NARVIS AI Brain
Version : 0.4.0
=========================================
"""

from datetime import datetime


class Brain:

    def __init__(self):
        self.name = "NARVIS"

    def think(self, command):

        command = command.lower().strip()

        # Greetings
        if command in ["hi", "hello", "hey"]:
            return "Hello Narottam 👋"

        # Assistant Name
        elif "your name" in command:
            return "My name is NARVIS."

        # Time
        elif "time" in command:
            return datetime.now().strftime("Current Time : %I:%M:%S %p")

        # Date
        elif "date" in command:
            return datetime.now().strftime("Today's Date : %d-%m-%Y")

        # Version
        elif "version" in command:
            return "NARVIS Version 0.4.0"

        # Status
        elif "status" in command:
            return "All systems are running perfectly."

        # Exit
        elif command in ["bye", "exit", "quit"]:
            return "Good Bye Narottam 👋"

        # Default
        else:
            return "Sorry Sir, I don't understand this command yet."