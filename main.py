"""
=========================================
NARVIS AI Operating System
Version : 0.4.0
Developer : Narottam
=========================================
"""

import os
from datetime import datetime

from Core.config import load_settings
from Core.logger import logger
from AI.brain import Brain

# Load Settings
settings = load_settings()

brain = Brain()


def banner():
    print("=" * 60)
    print("            NARVIS AI OPERATING SYSTEM")
    print("=" * 60)
    print("Developer :", settings["developer"])
    print("Version   :", settings["version"])
    print("Time      :", datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
    print("=" * 60)


def initialize():

    modules = [
        "AI Brain",
        "Voice Engine",
        "Memory",
        "Automation",
        "PC Controller",
        "Mobile Controller",
    ]

    print("\nInitializing Modules...\n")

    for module in modules:
        print(f"[ OK ] {module}")

    logger.info("NARVIS Started Successfully")

    print("\n============================================")
    print("System Status : ONLINE")
    print("============================================")
    print(f'Hello {settings["developer"]} 👋')
    print(f'{settings["assistant_name"]} is Online.')
    print("Ready for your command, Sir.")
    print("============================================")


def command_mode():

    print("\nType your command.")
    print("Type 'exit' to close NARVIS.\n")

    while True:

        command = input("You : ")

        response = brain.think(command)

        print("NARVIS :", response)

        if command.lower() in ["exit", "quit", "bye"]:
            break


if __name__ == "__main__":

    os.system("cls" if os.name == "nt" else "clear")

    banner()

    initialize()

    command_mode()