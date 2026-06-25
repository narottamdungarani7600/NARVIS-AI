"""
=========================================
NARVIS AI Operating System
Version : 0.3.0
Developer : Narottam
=========================================
"""

import os
from datetime import datetime

from Core.config import load_settings
from Core.logger import logger

# Load Settings
settings = load_settings()
VERSION = settings["version"]


def banner():
    print("=" * 60)
    print("            NARVIS AI OPERATING SYSTEM")
    print("=" * 60)
    print("Developer :", settings["developer"])
    print("Version   :", VERSION)
    print("Time      :", datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
    print("=" * 60)


def initialize():
    modules = [
        "AI Core",
        "Voice Engine",
        "Memory",
        "Automation",
        "PC Controller",
        "Mobile Controller",
    ]

    print("\nInitializing Modules...\n")

    for module in modules:
        print(f"[ OK ] {module}")

    # Save Startup Log
    logger.info("NARVIS Started Successfully")

    print("\n============================================")
    print("System Status : ONLINE")
    print("============================================")
    print(f'Hello {settings["developer"]} 👋')
    print(f'{settings["assistant_name"]} is Online.')
    print("Ready for your command, Sir.")
    print("============================================")


def main():
    os.system("cls" if os.name == "nt" else "clear")
    banner()
    initialize()


if __name__ == "__main__":
    main()